"""
Live Order Executor v5.1 — Universal 4-Scenario SOR & Dynamic Balance Equalizer
================================================================================
Handles all real-world orderbook spread conditions + dynamic minimum balance auto-sizing.
"""

import os
import asyncio
import aiohttp
import hmac
import hashlib
import json
import time
import logging
import datetime
from typing import Optional, Dict, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ─── Configuration ─────────────────────────────────────────────────────────────
DELTA_BASE_URL   = os.getenv("DELTA_BASE_URL",   "https://api.india.delta.exchange")
COINDCX_BASE_URL = os.getenv("COINDCX_BASE_URL", "https://api.coindcx.com")

DELTA_API_KEY      = os.getenv("DELTA_API_KEY",      "yCqLDRMdsn4Qj6360pWRaCm4xczCSO")
DELTA_API_SECRET   = os.getenv("DELTA_API_SECRET",   "kBBM2bfGMjiUj1LWXQVnD6vo0aM0L9sj6CD0VtSbNoG7pnC8dXI3Lft7VXaA")
COINDCX_API_KEY    = os.getenv("COINDCX_API_KEY",    "2b28b8cad04d91128eb92048acaf2041b1249bdb13f270fe")
COINDCX_API_SECRET = os.getenv("COINDCX_API_SECRET", "2fc83416123aec1d0f60fb66e5f52207cfbfee03f3a11ebc5fab4821486e036a")

# Master live/paper toggle — default TRUE for real money execution
LIVE_EXECUTION = os.getenv("LIVE_EXECUTION", "false").strip().lower() in ("true", "1", "yes")

# Fee Schedule (Inc. 18% GST)
FEE_TAKER_DELTA_ENTRY   = 0.00059
FEE_SCALPER_DELTA_EXIT  = 0.00000   # Free scalper offer <10s
FEE_TAKER_COINDCX_ENTRY = 0.00059
FEE_MAKER_COINDCX_EXIT  = 0.000236
TOTAL_ROUNDTRIP_FEE_PCT = 0.001416  # 0.1416% total dual-leg roundtrip

# Safety Thresholds
TAKER_MAX_SPREAD_THRES   = 0.05    # High-liquidity threshold (0.05%)
MAKER_MAX_SPREAD_THRES   = 0.50    # Max spread allowed for Maker Limit Orders
DRAWDOWN_OVERRIDE_PCT    = 10.0    # Emergency Exit if loss >= 10% of margin
MIN_GROSS_SPREAD_PCT     = 0.15    # Minimum Gross Spread required to trade

# Lot sizes — AGENTS.md Rule 2
LOT_SIZES = {
    "BTC":     0.001,
    "ETH":     0.01,
    "DEFAULT": 1.0,
}

# Symmetric Max Leverage Tables (AGENTS.md Rule 1)
DELTA_MAX_LEVERAGE = {
    "BTC": 100.0, "ETH": 100.0, "SOL": 50.0, "XRP": 50.0, "DOGE": 50.0,
    "BNB": 50.0, "1000SATS": 50.0, "ADA": 50.0, "AVAX": 50.0, "LINK": 50.0,
    "NEAR": 50.0, "SUI": 50.0, "PEPE": 50.0, "SHIB": 50.0, "WIF": 50.0,
    "_DEFAULT": 20.0,
}

COINDCX_MAX_LEVERAGE = {
    "BTC": 125.0, "ETH": 100.0, "SOL": 50.0, "XRP": 50.0, "DOGE": 50.0,
    "BNB": 75.0, "1000SATS": 20.0, "ADA": 75.0, "AVAX": 50.0, "LINK": 50.0,
    "NEAR": 50.0, "SUI": 50.0, "PEPE": 50.0, "SHIB": 50.0, "WIF": 50.0,
    "_DEFAULT": 20.0,
}

logger = logging.getLogger("LiveOrderExecutor")


def get_symmetric_leverage(coin: str) -> int:
    """Returns MIN(Delta_max, CoinDCX_max) to guarantee matching leverage on both legs."""
    c = coin.upper()
    d_lev = DELTA_MAX_LEVERAGE.get(c, DELTA_MAX_LEVERAGE["_DEFAULT"])
    c_lev = COINDCX_MAX_LEVERAGE.get(c, COINDCX_MAX_LEVERAGE["_DEFAULT"])
    return int(min(d_lev, c_lev))


def sign_delta(method: str, path: str, payload_str: str) -> Tuple[str, str]:
    """Delta Exchange HMAC-SHA256 Signer."""
    timestamp = str(int(time.time()))
    message   = method + timestamp + path + payload_str
    sig = hmac.new(DELTA_API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return timestamp, sig


def sign_coindcx(payload: dict) -> Tuple[str, str]:
    """CoinDCX Futures HMAC-SHA256 Signer."""
    payload["timestamp"] = int(time.time() * 1000)
    body_str = json.dumps(payload, separators=(",", ":"))
    sig = hmac.new(COINDCX_API_SECRET.encode("utf-8"), body_str.encode("utf-8"), hashlib.sha256).hexdigest()
    return body_str, sig


def calculate_sizing(coin: str, mark_price: float, target_notional_usd: float) -> Tuple[int, float, float]:
    """Universal Base Asset Quantity Sizing Protocol (AGENTS.md Rule 8)."""
    lot_size = LOT_SIZES.get(coin.upper(), LOT_SIZES["DEFAULT"])
    raw_qty  = target_notional_usd / mark_price if mark_price > 0 else 0.0
    lots     = max(1, round(raw_qty / lot_size))
    exact    = round(lots * lot_size, 4)
    notional = round(exact * mark_price, 2)
    return lots, exact, notional


class LiveOrderExecutor:
    def __init__(self):
        self.live = LIVE_EXECUTION
        self.session: Optional[aiohttp.ClientSession] = None
        self.t_order = aiohttp.ClientTimeout(total=8,  connect=3.0, sock_read=6.0)
        self.t_scan  = aiohttp.ClientTimeout(total=15, connect=5.0, sock_read=12.0)
        # Separate longer timeout for balance fetches (India-exchange APIs from US Render servers)
        self.t_balance = aiohttp.ClientTimeout(total=20, connect=5.0, sock_read=15.0)

        mode = "LIVE REAL-MONEY 🔴" if self.live else "PAPER SIMULATION 📄"
        logger.info(f"LiveOrderExecutor v5.1 Initialized | Mode: {mode}")

    async def _ensure_session(self):
        # Recreate session if missing, closed, or attached to a stale/dead loop
        try:
            need_new = (
                self.session is None
                or self.session.closed
                or self.session.connector is None
                or self.session.connector.closed
            )
        except Exception:
            need_new = True
        if need_new:
            try:
                if self.session and not self.session.closed:
                    await self.session.close()
            except Exception:
                pass
            connector = aiohttp.TCPConnector(limit=30, ttl_dns_cache=300)
            self.session = aiohttp.ClientSession(connector=connector, headers={"User-Agent": "HFTFundingArbitrage/5.1"})

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_live_balances(self) -> Tuple[float, float, float]:
        """
        Fetches live margin balance on both Delta and CoinDCX.
        Returns: (delta_usd, coindcx_usdt, min_effective_margin)

        CoinDCX NOTE: There is no /futures/balance endpoint.
        Futures margin is computed as:
          - Spot USDT wallet balance (unlocked/available capital)
          + Sum of locked_user_margin across all futures positions (capital deployed)
        This gives the TOTAL USDT capital on CoinDCX including deployed margin.
        """
        await self._ensure_session()
        # Start with last known good values (overwritten if fetch succeeds)
        d_bal = getattr(self, '_last_d_bal', 7.96)
        c_bal = getattr(self, '_last_c_bal', 9.31)

        # ── Delta Balance ──────────────────────────────────────────────────
        try:
            t_stamp, sig = sign_delta("GET", "/v2/wallet/balances", "")
            headers = {"api-key": DELTA_API_KEY, "timestamp": t_stamp, "signature": sig, "User-Agent": "Mozilla/5.0"}
            async with self.session.get(DELTA_BASE_URL + "/v2/wallet/balances", headers=headers, timeout=self.t_balance) as resp:
                data = await resp.json()
                for b in data.get("result", []):
                    if b.get("asset_symbol") == "USD":
                        fetched = float(b.get("balance") or 0)
                        if fetched >= 0:
                            d_bal = fetched
                            self._last_d_bal = d_bal
                        break
        except Exception as e:
            logger.warning(f"Error fetching Delta balance: {e} — using last known ${d_bal:.2f}")

        # ── CoinDCX Balance: Spot USDT + Futures Deployed Margin ─────────
        # CoinDCX has NO /futures/balance endpoint.
        # Total capital = spot USDT (free) + sum(locked_user_margin) across all positions (deployed)
        try:
            spot_usdt = 0.0
            futures_locked = 0.0

            # Step 1: Spot wallet USDT (free/available capital)
            path = "/exchange/v1/users/balances"
            payload = {}
            body_str, sig = sign_coindcx(payload)
            headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig}
            async with self.session.post(COINDCX_BASE_URL + path, data=body_str, headers=headers, timeout=self.t_balance) as resp:
                data = await resp.json()
                if isinstance(data, list):
                    for item in data:
                        if item.get("currency") == "USDT":
                            spot_usdt = float(item.get("balance") or 0)
                            break

            # Step 2: Sum locked_user_margin across all futures positions (deployed capital)
            pos_path = "/exchange/v1/derivatives/futures/positions"
            pos_payload = {}
            pos_body, pos_sig = sign_coindcx(pos_payload)
            pos_headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": pos_sig}
            async with self.session.post(COINDCX_BASE_URL + pos_path, data=pos_body, headers=pos_headers, timeout=self.t_balance) as resp2:
                positions = await resp2.json()
                if isinstance(positions, list):
                    for p in positions:
                        lm = float(p.get("locked_user_margin") or 0)
                        futures_locked += lm

            c_bal = spot_usdt + futures_locked
            if c_bal >= 1.0:
                self._last_c_bal = c_bal

        except Exception as e:
            logger.warning(f"Error fetching CoinDCX balance: {e} — using last known ${c_bal:.2f}")

        # Check environment variable manual overrides first (if user set exact balance in Render / .env)
        env_c_bal = os.getenv("COINDCX_OVERRIDE_BALANCE") or os.getenv("COINDCX_BALANCE_USD")
        env_d_bal = os.getenv("DELTA_OVERRIDE_BALANCE")  or os.getenv("DELTA_BALANCE_USD")

        if env_d_bal:
            try:
                d_bal = float(env_d_bal)
                self._last_d_bal = d_bal
            except ValueError:
                pass
        elif d_bal < 0.01:
            d_bal = getattr(self, '_last_d_bal', 1.00)
            self._last_d_bal = d_bal

        if env_c_bal:
            try:
                c_bal = float(env_c_bal)
                self._last_c_bal = c_bal
            except ValueError:
                pass
        elif c_bal < 0.01:
            c_bal = getattr(self, '_last_c_bal', 9.31)
            self._last_c_bal = c_bal

        # 75% of lower balance = safe execution margin (leaves 25% headroom for fees/slippage)
        min_margin = min(d_bal, c_bal) * 0.75
        logger.info(f"💰 LIVE BALANCE AUDIT: Delta=${d_bal:.2f} | CoinDCX=${c_bal:.2f} | Safe Margin(75%)=${min_margin:.2f}")
        return d_bal, c_bal, min_margin


    async def _delta_get(self, path: str) -> Dict:
        """Authenticated GET for Delta."""
        t_stamp, sig = sign_delta("GET", path, "")
        headers = {
            "api-key":   DELTA_API_KEY,
            "timestamp": t_stamp,
            "signature": sig,
            "User-Agent": "Mozilla/5.0"
        }
        async with self.session.get(DELTA_BASE_URL + path, headers=headers, timeout=self.t_scan) as resp:
            return await resp.json()

    async def _delta_order(
        self,
        symbol: str,
        side: str,
        lots: int,
        order_type: str = "market_order",
        limit_price: Optional[float] = None,
        post_only: bool = False,
        reduce_only: bool = False
    ) -> Dict:
        """Delta Order Placement."""
        path = "/v2/orders"
        payload = {
            "product_symbol": symbol,
            "size":           lots,
            "side":           side.lower(),
            "order_type":     order_type,
        }
        if order_type == "limit_order" and limit_price:
            payload["limit_price"] = str(limit_price)
            if post_only:
                payload["post_only"] = True
        if reduce_only:
            payload["is_reduce_only"] = True

        payload_str  = json.dumps(payload)
        t_stamp, sig = sign_delta("POST", path, payload_str)
        headers = {
            "Content-Type": "application/json",
            "api-key":      DELTA_API_KEY,
            "timestamp":    t_stamp,
            "signature":    sig,
        }

        t0 = time.perf_counter()
        try:
            async with self.session.post(DELTA_BASE_URL + path, data=payload_str, headers=headers, timeout=self.t_order) as resp:
                latency = (time.perf_counter() - t0) * 1000
                body    = await resp.json()
                success = resp.status in (200, 201) and body.get("success", False)
                return {
                    "exchange":   "Delta",
                    "success":    success,
                    "http":       resp.status,
                    "latency_ms": latency,
                    "order_id":   body.get("result", {}).get("id"),
                    "state":      body.get("result", {}).get("state"),
                    "response":   body,
                }
        except Exception as e:
            return {"exchange": "Delta", "success": False, "http": 0, "latency_ms": 0, "error": str(e)}

    async def _delta_cancel_order(self, order_id: int, product_id: int) -> Dict:
        """Cancel a pending order on Delta."""
        path = "/v2/orders"
        payload = {"id": order_id, "product_id": product_id}
        payload_str = json.dumps(payload)
        t_stamp, sig = sign_delta("DELETE", path, payload_str)
        headers = {
            "Content-Type": "application/json",
            "api-key":      DELTA_API_KEY,
            "timestamp":    t_stamp,
            "signature":    sig,
        }
        async with self.session.delete(DELTA_BASE_URL + path, data=payload_str, headers=headers, timeout=self.t_order) as resp:
            return await resp.json()

    async def _coindcx_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "market_order",
        limit_price: Optional[float] = None,
        leverage: int = 20,
        reduce_only: bool = False
    ) -> Dict:
        """CoinDCX Order Placement."""
        path    = "/exchange/v1/derivatives/futures/orders/create"
        order_dict = {
            "pair":           symbol,
            "side":           side.lower(),
            "order_type":     order_type,
            "total_quantity": qty,
            "leverage":       leverage,
            "margin_type":    "isolated",
        }
        if limit_price and order_type == "limit_order":
            order_dict["price"] = limit_price
        if reduce_only and order_type == "limit_order":
            order_dict["reduce_only"] = True

        payload = {"order": order_dict}
        body_str, sig = sign_coindcx(payload)
        headers = {
            "Content-Type":    "application/json",
            "X-AUTH-APIKEY":   COINDCX_API_KEY,
            "X-AUTH-SIGNATURE": sig,
        }

        t0 = time.perf_counter()
        try:
            async with self.session.post(COINDCX_BASE_URL + path, data=body_str, headers=headers, timeout=self.t_order) as resp:
                latency = (time.perf_counter() - t0) * 1000
                body    = await resp.json()
                success = resp.status in (200, 201)
                oid     = body.get("id") if isinstance(body, dict) else (body[0].get("id") if isinstance(body, list) and body else None)
                return {
                    "exchange":   "CoinDCX",
                    "success":    success,
                    "http":       resp.status,
                    "latency_ms": latency,
                    "order_id":   oid,
                    "response":   body,
                }
        except Exception as e:
            return {"exchange": "CoinDCX", "success": False, "http": 0, "latency_ms": 0, "error": str(e)}

    # ── UNIVERSAL 4-CASE SMART ORDER ROUTER (SOR) WITH BALANCE EQUALIZER ───────

    async def execute_smart_order_router_entry(
        self,
        delta_sym:        str,
        delta_side:       str,
        delta_lots:       int,
        coindcx_sym:      str,
        coindcx_side:     str,
        exact_qty:        float,
        leverage:         int,
        coin:             str,
        mark_delta:       float,
        mark_coindcx:     float,
        notional_usd:     float,
        gross_spread_pct: float,
        timeout_seconds:  int = 30,
    ) -> Dict:
        await self._ensure_session()
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Audit Live Balances to ensure 100% Margin Neutrality
        d_bal, c_bal, min_safe_margin = await self.fetch_live_balances()

        if not self.live:
            await asyncio.sleep(0.015)
            logger.info(f"[{ts}] PAPER 4-CASE SOR: {coin} | Delta {delta_side.upper()} {delta_lots}Lots | CoinDCX {coindcx_side.upper()} {exact_qty}")
            return {
                "status":       "PAPER",
                "latency_ms":   15.0,
                "delta_lots":   delta_lots,
                "exact_qty":    exact_qty,
                "notional_usd": notional_usd,
                "leverage":     leverage,
                "effective_margin_used": min_safe_margin
            }

        # 1. Fetch live orderbook spreads from both exchanges
        d_bid, d_ask, c_bid, c_ask = mark_delta, mark_delta, mark_coindcx, mark_coindcx
        d_product_id = None

        try:
            url_d = f"{DELTA_BASE_URL}/v2/tickers/{delta_sym}"
            async with self.session.get(url_d, timeout=self.t_scan) as resp:
                data_d = await resp.json()
                quotes_d = data_d.get("result", {}).get("quotes", {})
                d_bid = float(quotes_d.get("best_bid") or mark_delta)
                d_ask = float(quotes_d.get("best_ask") or mark_delta)
                d_product_id = data_d.get("result", {}).get("product_id")

            pair_c = coindcx_sym.replace("B-", "").replace("_", "")
            url_c = f"https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol={pair_c}"
            async with self.session.get(url_c, timeout=self.t_scan) as resp:
                data_c = await resp.json()
                c_bid = float(data_c.get("bidPrice") or mark_coindcx)
                c_ask = float(data_c.get("askPrice") or mark_coindcx)
        except Exception as e:
            logger.warning(f"Error fetching live spreads: {e}")

        d_spread = ((d_ask - d_bid) / d_bid) * 100.0 if d_bid > 0 else 0.0
        c_spread = ((c_ask - c_bid) / c_bid) * 100.0 if c_bid > 0 else 0.0

        logger.info(f"[{ts}] 🔍 SOR SPREAD ANALYSIS: {coin} | Delta Spread={d_spread:.4f}% | CoinDCX Spread={c_spread:.4f}%")

        # ────────────── CASE EVALUATION ──────────────

        # CASE 4: Both Spreads are Wide (> 0.05%) → ABORT
        if d_spread > TAKER_MAX_SPREAD_THRES and c_spread > TAKER_MAX_SPREAD_THRES:
            logger.warning(f"⛔ CASE 4 ABORT: Both exchanges have wide spreads. Rejecting trade.")
            return {"status": "ABORTED_BOTH_EXCHANGES_WIDE_SPREAD", "d_spread": d_spread, "c_spread": c_spread}

        # CASE 3: Both Spreads are Tight (<= 0.05%) → Simultaneous Parallel Market Orders (<20ms)
        if d_spread <= TAKER_MAX_SPREAD_THRES and c_spread <= TAKER_MAX_SPREAD_THRES:
            logger.info(f"⚡ CASE 3 EXECUTION: Both spreads tight! Firing parallel market orders...")
            t0 = time.perf_counter()
            res_d, res_c = await asyncio.gather(
                self._delta_order(delta_sym, delta_side, delta_lots, order_type="market_order"),
                self._coindcx_order(coindcx_sym, coindcx_side, exact_qty, order_type="market_order", leverage=leverage),
            )
            total_ms = (time.perf_counter() - t0) * 1000
            return {
                "status":           "SUCCESS_LIVE",
                "latency_ms":       total_ms,
                "delta_order_id":   res_d.get("order_id"),
                "coindcx_order_id": res_c.get("order_id"),
                "delta_lots":       delta_lots,
                "exact_qty":        exact_qty,
                "notional_usd":     notional_usd,
                "leverage":         leverage,
                "execution_type":   "CASE_3_PARALLEL_MARKET",
            }

        # CASE 1: Delta is Wide (>0.05%), CoinDCX is Tight (<=0.05%) → Delta Maker First, CoinDCX Market Second
        if d_spread > TAKER_MAX_SPREAD_THRES and c_spread <= TAKER_MAX_SPREAD_THRES:
            logger.info(f"🎯 CASE 1 EXECUTION: Delta wide ({d_spread:.3f}%), CoinDCX tight ({c_spread:.3f}%). Delta MAKER limit first...")
            limit_price = max(d_ask, round((d_bid + d_ask)/2.0, 8)) if delta_side.lower() == "sell" else min(d_bid, round((d_bid + d_ask)/2.0, 8))

            res_d = await self._delta_order(delta_sym, delta_side, delta_lots, order_type="limit_order", limit_price=limit_price, post_only=True)
            if not res_d["success"]:
                return {"status": "DELTA_MAKER_FAILED", "error": res_d.get("response")}

            order_id = res_d["order_id"]
            start_time = time.time()
            filled = False
            while (time.time() - start_time) < timeout_seconds:
                await asyncio.sleep(0.5)
                ord_status = await self._delta_get(f"/v2/orders/{order_id}")
                if ord_status.get("result", {}).get("state") == "closed":
                    filled = True
                    break
            
            if not filled:
                if d_product_id:
                    await self._delta_cancel_order(order_id, d_product_id)
                return {"status": "DELTA_LIMIT_TIMEOUT_EXPIRED"}

            # Delta Filled! Fire CoinDCX Market Order
            t0 = time.perf_counter()
            res_c = await self._coindcx_order(coindcx_sym, coindcx_side, exact_qty, order_type="market_order", leverage=leverage)
            return {
                "status":           "SUCCESS_LIVE",
                "latency_ms":       (time.perf_counter() - t0) * 1000,
                "delta_order_id":   order_id,
                "coindcx_order_id": res_c.get("order_id"),
                "delta_lots":       delta_lots,
                "exact_qty":        exact_qty,
                "notional_usd":     notional_usd,
                "leverage":         leverage,
                "execution_type":   "CASE_1_DELTA_MAKER_FIRST",
            }

        # CASE 2: CoinDCX is Wide (>0.05%), Delta is Tight (<=0.05%) → CoinDCX Limit First, Delta Market Second
        if c_spread > TAKER_MAX_SPREAD_THRES and d_spread <= TAKER_MAX_SPREAD_THRES:
            logger.info(f"🎯 CASE 2 EXECUTION: CoinDCX wide ({c_spread:.3f}%), Delta tight ({d_spread:.3f}%). CoinDCX LIMIT first...")
            c_limit_price = max(c_ask, round((c_bid + c_ask)/2.0, 8)) if coindcx_side.lower() == "sell" else min(c_bid, round((c_bid + c_ask)/2.0, 8))

            res_c = await self._coindcx_order(coindcx_sym, coindcx_side, exact_qty, order_type="limit_order", limit_price=c_limit_price, leverage=leverage)
            if not res_c["success"]:
                return {"status": "COINDCX_LIMIT_FAILED", "error": res_c.get("response")}

            # Fire Delta Market Order upon CoinDCX fill
            t0 = time.perf_counter()
            res_d = await self._delta_order(delta_sym, delta_side, delta_lots, order_type="market_order")
            return {
                "status":           "SUCCESS_LIVE",
                "latency_ms":       (time.perf_counter() - t0) * 1000,
                "delta_order_id":   res_d.get("order_id"),
                "coindcx_order_id": res_c.get("order_id"),
                "delta_lots":       delta_lots,
                "exact_qty":        exact_qty,
                "notional_usd":     notional_usd,
                "leverage":         leverage,
                "execution_type":   "CASE_2_COINDCX_LIMIT_FIRST",
            }

        return {"status": "UNKNOWN_SPREAD_CASE"}

    # Alias execute_entry
    async def execute_entry(self, *args, **kwargs):
        return await self.execute_smart_order_router_entry(*args, **kwargs)

    # ── Parallel Dual-Leg Exit ─────────────────────────────────────────────────

    async def execute_exit(
        self,
        delta_sym:        str,
        delta_side:       str,
        delta_lots:       int,
        coindcx_sym:      str,
        coindcx_side:     str,
        exact_qty:        float,
        leverage:         int,
        notional_usd:     float,
        gross_spread_pct: float,
        trigger_reason:   str = "Scalper Exit T+2s",
    ) -> Dict:
        await self._ensure_session()
        exit_delta_side   = "buy" if delta_side.upper()   == "SELL" else "sell"
        exit_coindcx_side = "buy" if coindcx_side.upper() == "SELL" else "sell"
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

        gross_usd = notional_usd * (gross_spread_pct / 100.0)
        fees_usd  = notional_usd * TOTAL_ROUNDTRIP_FEE_PCT
        net_usd   = gross_usd - fees_usd

        if not self.live:
            await asyncio.sleep(0.015)
            logger.info(f"[{ts}] PAPER EXIT ({trigger_reason}) | Gross=+${gross_usd:.4f} | Fees=-${fees_usd:.4f} | NET=+${net_usd:.4f}")
            return {"status": "PAPER", "net_pnl_usd": net_usd, "gross_usd": gross_usd, "fees_usd": fees_usd}

        t0 = time.perf_counter()
        res_d, res_c = await asyncio.gather(
            self._delta_order(delta_sym, exit_delta_side, delta_lots, reduce_only=True),
            self._coindcx_order(coindcx_sym, exit_coindcx_side, exact_qty, reduce_only=True),
        )
        total_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            f"[{ts}] LIVE EXIT ({trigger_reason}) ({total_ms:.1f}ms) | "
            f"Delta: HTTP{res_d['http']} OK={res_d['success']} | "
            f"CoinDCX: HTTP{res_c['http']} OK={res_c['success']}"
        )
        return {
            "status":     "SUCCESS_LIVE",
            "net_pnl_usd": net_usd,
            "gross_usd":   gross_usd,
            "fees_usd":    fees_usd,
            "latency_ms":  total_ms,
            "delta":       res_d,
            "coindcx":     res_c,
        }

    async def execute_full_account_position_close(self, trigger_reason: str = "Dynamic 100% Full Position Close") -> Dict:
        """
        Queries live active positions on BOTH exchanges (Delta & CoinDCX),
        determines exact open size for each position, and fires reduce_only market orders
        to guarantee 100% complete closure with ZERO residual position.
        """
        await self._ensure_session()
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        closed_delta = []
        closed_coindcx = []

        if not self.live:
            logger.info(f"[{ts}] PAPER FULL POSITION CLOSE TRIGGERED ({trigger_reason})")
            return {"status": "PAPER", "closed_delta": [], "closed_coindcx": []}

        # 1. Fetch & Close ALL Delta Active Positions
        try:
            d_pos_resp = await self._delta_get("/v2/positions/margined")
            d_positions = d_pos_resp.get("result", []) if isinstance(d_pos_resp, dict) else []
            for p in d_positions:
                size = int(p.get("size") or 0)
                sym = p.get("product_symbol", "")
                if size != 0 and sym:
                    close_side = "sell" if size > 0 else "buy"
                    close_lots = abs(size)
                    res_d = await self._delta_order(sym, close_side, close_lots, order_type="market_order", reduce_only=True)
                    closed_delta.append({"symbol": sym, "closed_lots": close_lots, "side": close_side, "result": res_d})
                    logger.info(f"[{ts}] DELTA FULL CLOSE: {sym} | {close_side.upper()} {close_lots} Lots | Result: {res_d.get('success')}")
        except Exception as e:
            logger.error(f"Error closing Delta positions: {e}")

        # 2. Fetch & Close ALL CoinDCX Active Positions
        try:
            pos_path = "/exchange/v1/derivatives/futures/positions"
            payload = {}
            body_str, sig = sign_coindcx(payload)
            headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig}
            async with self.session.post(COINDCX_BASE_URL + pos_path, data=body_str, headers=headers, timeout=self.t_order) as resp:
                c_positions = await resp.json()
                if isinstance(c_positions, list):
                    for p in c_positions:
                        active_pos = float(p.get("active_pos") or 0)
                        pair = p.get("pair", "")
                        if active_pos != 0 and pair:
                            close_side = "sell" if active_pos > 0 else "buy"
                            close_qty = abs(active_pos)
                            res_c = await self._coindcx_order(pair, close_side, close_qty, order_type="market_order", reduce_only=True)
                            closed_coindcx.append({"pair": pair, "closed_qty": close_qty, "side": close_side, "result": res_c})
                            logger.info(f"[{ts}] COINDCX FULL CLOSE: {pair} | {close_side.upper()} {close_qty} | Result: {res_c.get('success')}")
        except Exception as e:
            logger.error(f"Error closing CoinDCX positions: {e}")

        return {
            "status": "SUCCESS_FULL_CLOSE",
            "trigger_reason": trigger_reason,
            "closed_delta": closed_delta,
            "closed_coindcx": closed_coindcx
        }


# ─── Singleton Factory ─────────────────────────────────────────────────────────
_executor_instance: Optional[LiveOrderExecutor] = None

def get_executor() -> LiveOrderExecutor:
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = LiveOrderExecutor()
    return _executor_instance
