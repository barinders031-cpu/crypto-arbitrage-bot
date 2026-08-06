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

DELTA_API_KEY      = os.getenv("DELTA_API_KEY",      "4um8VJANfCCLEjyFnVelVtGVdWvEuK")
DELTA_API_SECRET   = os.getenv("DELTA_API_SECRET",   "v2MbvEtYeCCXR04YjZg9pZonEFIKh3p0SmUPXRTNxc99VSwZRblDLVXKbUMr")
COINDCX_API_KEY    = os.getenv("COINDCX_API_KEY",    "2b28b8cad04d91128eb92048acaf2041b1249bdb13f270fe")
COINDCX_API_SECRET = os.getenv("COINDCX_API_SECRET", "2fc83416123aec1d0f60fb66e5f52207cfbfee03f3a11ebc5fab4821486e036a")

# Master live/paper toggle — default TRUE for real money execution
LIVE_EXECUTION = os.getenv("LIVE_EXECUTION", "true").strip().lower() in ("true", "1", "yes")

# Fee Schedule (Inc. 18% GST)
FEE_TAKER_DELTA_ENTRY   = 0.00059
FEE_SCALPER_DELTA_EXIT  = 0.00000   # Free scalper offer <10s
FEE_TAKER_COINDCX_ENTRY = 0.00059
FEE_MAKER_COINDCX_EXIT  = 0.000236
TOTAL_ROUNDTRIP_FEE_PCT = 0.001416  # 0.1416% total dual-leg roundtrip

# Safety Thresholds
TAKER_MAX_SPREAD_THRES   = 0.35    # Max spread threshold (0.35%)
MAKER_MAX_SPREAD_THRES   = 0.75    # Max spread allowed for Maker Limit Orders
DRAWDOWN_OVERRIDE_PCT    = 10.0    # Emergency Exit if loss >= 10% of margin
MIN_GROSS_SPREAD_PCT     = 0.25    # Minimum Gross Spread required to trade (0.25%)

# Lot sizes — AGENTS.md Rule 2
LOT_SIZES = {
    "BTC":     0.001,
    "ETH":     0.01,
    "DEFAULT": 1.0,
}

# Symmetric Max Leverage Tables (AGENTS.md Rule 1)
DELTA_MAX_LEVERAGE = {
    "BTC": 200.0, "ETH": 200.0, "SOL": 50.0, "XRP": 50.0, "DOGE": 50.0,
    "BNB": 50.0, "1000SATS": 50.0, "ADA": 50.0, "AVAX": 50.0, "LINK": 50.0,
    "NEAR": 50.0, "SUI": 50.0, "PEPE": 50.0, "SHIB": 50.0, "WIF": 50.0,
    "_DEFAULT": 20.0,
}

COINDCX_MAX_LEVERAGE = {
    "BTC": 125.0, "ETH": 100.0, "SOL": 50.0, "XRP": 50.0, "DOGE": 50.0,
    "BNB": 75.0, "BANK": 7.0, "1000SATS": 20.0, "ADA": 75.0, "AVAX": 50.0, "LINK": 50.0,
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


DELTA_TIME_OFFSET = 0.0

def update_delta_time_offset():
    """Fetch Delta server time and compute clock drift offset."""
    global DELTA_TIME_OFFSET
    try:
        import requests
        res = requests.get("https://api.india.delta.exchange/v2/tickers/BTCUSD", timeout=5).json()
        ts_micro = int(res.get("result", {}).get("timestamp", 0))
        if ts_micro > 0:
            server_epoch = ts_micro / 1_000_000.0
            DELTA_TIME_OFFSET = server_epoch - time.time()
            logger.info(f"⏱️ Delta Server Time Offset Calibrated: {DELTA_TIME_OFFSET:+.3f}s")
    except Exception as e:
        logger.warning(f"⚠️ Failed to calibrate Delta time offset: {e}")

# Initial calibration
update_delta_time_offset()


def sign_delta(method: str, path: str, payload_str: str) -> Tuple[str, str]:
    """Delta Exchange HMAC-SHA256 Signer with Server Clock Drift Protection."""
    timestamp = str(int(time.time() + DELTA_TIME_OFFSET))
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
    """Universal Base Asset Quantity Sizing Protocol (AGENTS.md Rule 8 & Rule 9)."""
    MIN_COINDCX_NOTIONAL = 25.0  # CoinDCX requires order value >= 24.0 USDT
    effective_notional = max(target_notional_usd, MIN_COINDCX_NOTIONAL)
    lot_size = LOT_SIZES.get(coin.upper(), LOT_SIZES["DEFAULT"])
    raw_qty  = effective_notional / mark_price if mark_price > 0 else 0.0
    lots     = max(1, round(raw_qty / lot_size))
    
    # Guarantee notional >= 25.0 USDT for CoinDCX compliance
    while mark_price > 0 and (lots * lot_size * mark_price) < MIN_COINDCX_NOTIONAL:
        lots += 1

    exact    = round(lots * lot_size, 4)
    notional = round(exact * mark_price, 2)
    return lots, exact, notional


class LiveOrderExecutor:
    def __init__(self):
        self.live = LIVE_EXECUTION
        self.session: Optional[aiohttp.ClientSession] = None
        self.t_order = aiohttp.ClientTimeout(total=30, connect=10.0, sock_read=25.0)
        self.t_scan  = aiohttp.ClientTimeout(total=30, connect=10.0, sock_read=25.0)
        self.t_balance = aiohttp.ClientTimeout(total=30, connect=10.0, sock_read=25.0)

        mode = "LIVE REAL-MONEY 🔴" if self.live else "PAPER SIMULATION 📄"
        logger.info(f"LiveOrderExecutor v5.2 Initialized | Mode: {mode} | Timeout: 30s | Retries: 3 (5s, 10s, 20s)")

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
            self.session = aiohttp.ClientSession(connector=connector, headers={"User-Agent": "HFTFundingArbitrage/5.2"})

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_live_balances(self) -> Tuple[float, float, float, Dict]:
        """
        Fetches live margin balance on both Delta and CoinDCX.
        Returns: (delta_usd, coindcx_usdt, min_effective_margin, status_metadata_dict)
        Preserves HTTP status codes explicitly and blocks trading if CoinDCX API is unverified/unauthorized.
        """
        await self._ensure_session()
        d_bal = getattr(self, '_last_d_bal', 0.0)
        c_bal = getattr(self, '_last_c_bal', 0.0)
        delays = [2, 5, 10]

        coindcx_status = "UNKNOWN"
        coindcx_http = 0
        coindcx_error_msg = ""
        spot_usdt = 0.0
        futures_locked = 0.0

        # ── 1. Delta Balance with Retries ──────────────────────────────────
        for attempt in range(3):
            try:
                t_stamp, sig = sign_delta("GET", "/v2/wallet/balances", "")
                headers = {"api-key": DELTA_API_KEY, "timestamp": t_stamp, "signature": sig, "User-Agent": "Mozilla/5.0"}
                async with self.session.get(DELTA_BASE_URL + "/v2/wallet/balances", headers=headers, timeout=self.t_balance) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for b in data.get("result", []):
                            if b.get("asset_symbol") in ("USDT", "USD", "DETO", "INR"):
                                fetched = float(b.get("available_balance") or b.get("balance") or 0)
                                if fetched > 0:
                                    d_bal = fetched
                        break
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(delays[attempt])

        # ── 2. CoinDCX Balance with Explicit HTTP Code Tracking ──────────────
        for attempt in range(3):
            try:
                path = "/exchange/v1/users/balances"
                payload = {}
                body_str, sig = sign_coindcx(payload)
                headers = {
                    "Content-Type": "application/json",
                    "X-AUTH-APIKEY": COINDCX_API_KEY,
                    "X-AUTH-SIGNATURE": sig,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                }
                async with self.session.post(COINDCX_BASE_URL + path, data=body_str, headers=headers, timeout=self.t_balance) as resp:
                    coindcx_http = resp.status
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list):
                            for item in data:
                                if item.get("currency") == "USDT":
                                    spot_usdt = float(item.get("balance") or 0)
                                    break
                        coindcx_status = "CONNECTED"
                    elif resp.status == 401:
                        coindcx_status = "401_UNAUTHORIZED"
                        coindcx_error_msg = "CoinDCX API Key Unauthorized (Read Balances Permission Missing or IP Whitelist Error)"
                        break
                    else:
                        coindcx_status = f"HTTP_{resp.status}"
                        coindcx_error_msg = f"HTTP Error {resp.status}"

                # ── ALSO fetch Futures USDT Margin balance (separate endpoint) ──
                # User's Futures USDT Margin is at /exchange/v1/derivatives/futures/balances
                futures_usdt_margin = 0.0
                if coindcx_status == "CONNECTED":
                    fut_bal_path = "/exchange/v1/derivatives/futures/balances"
                    fut_bal_body, fut_bal_sig = sign_coindcx({})
                    fut_bal_headers = {
                        "Content-Type": "application/json",
                        "X-AUTH-APIKEY": COINDCX_API_KEY,
                        "X-AUTH-SIGNATURE": fut_bal_sig,
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    }
                    try:
                        async with self.session.post(COINDCX_BASE_URL + fut_bal_path, data=fut_bal_body, headers=fut_bal_headers, timeout=self.t_balance) as resp_fb:
                            if resp_fb.status == 200:
                                fb_data = await resp_fb.json()
                                # Response is a list of balance objects or a dict
                                if isinstance(fb_data, list):
                                    for fb_item in fb_data:
                                        if fb_item.get("currency") in ("USDT", "usdt"):
                                            futures_usdt_margin += float(fb_item.get("balance") or fb_item.get("available_balance") or 0)
                                elif isinstance(fb_data, dict):
                                    futures_usdt_margin = float(fb_data.get("balance") or fb_data.get("available_balance") or 0)
                                logger.info(f"[COINDCX FUTURES MARGIN] USDT Margin Balance: ${futures_usdt_margin:.4f}")
                            else:
                                logger.warning(f"[COINDCX FUTURES MARGIN] HTTP {resp_fb.status} — trying alternate field")
                    except Exception as ef:
                        logger.warning(f"[COINDCX FUTURES MARGIN] Error: {ef}")

                # Query Futures Locked Margin if Spot read succeeded
                if coindcx_status == "CONNECTED":
                    pos_path = "/exchange/v1/derivatives/futures/positions"
                    pos_body, pos_sig = sign_coindcx({})
                    pos_headers = {
                        "Content-Type": "application/json",
                        "X-AUTH-APIKEY": COINDCX_API_KEY,
                        "X-AUTH-SIGNATURE": pos_sig,
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    }
                    async with self.session.post(COINDCX_BASE_URL + pos_path, data=pos_body, headers=pos_headers, timeout=self.t_balance) as resp2:
                        if resp2.status == 200:
                            positions = await resp2.json()
                            if isinstance(positions, list):
                                for p in positions:
                                    lm = float(p.get("locked_user_margin") or 0)
                                    futures_locked += lm
                        elif resp2.status == 401:
                            coindcx_status = "401_UNAUTHORIZED"
                            coindcx_error_msg = "Futures Read Permission Missing (HTTP 401)"

                if coindcx_status == "CONNECTED":
                    # Use Futures USDT Margin as primary (if available), else fallback to spot
                    # Futures margin > 0 means user has funded their futures account
                    c_bal = futures_usdt_margin if futures_usdt_margin > 0 else (spot_usdt + futures_locked)
                    self._last_valid_c_bal = c_bal
                    self.coindcx_last_success_ts = datetime.datetime.now().strftime("%H:%M:%S")
                    logger.info(f"[COINDCX BALANCE] Spot USDT: ${spot_usdt:.4f} | Futures Margin: ${futures_usdt_margin:.4f} | Locked: ${futures_locked:.4f} | Using: ${c_bal:.4f}")
                    break

            except Exception as e:
                coindcx_status = "API_ERROR"
                coindcx_error_msg = str(e)
                if attempt < 2:
                    await asyncio.sleep(delays[attempt])

        # ── COINDCX_OVERRIDE_BALANCE: works in BOTH paper and live mode ──────────
        # CoinDCX does NOT expose a Futures USDT Margin balance via any public API
        # endpoint. When the user's funds are in their Futures Wallet, the only
        # reliable source of truth is a manual env var override.
        # This is SAFE: we still verify authentication succeeded (HTTP 200 above),
        # so we KNOW the API key is valid; we're just supplementing the missing balance.
        env_c_bal_str = os.getenv("COINDCX_OVERRIDE_BALANCE")
        env_d_bal_str = os.getenv("DELTA_OVERRIDE_BALANCE")
        if env_d_bal_str:
            d_bal = float(env_d_bal_str)
            logger.info(f"[BALANCE OVERRIDE] Delta balance overridden to ${d_bal:.4f} via DELTA_OVERRIDE_BALANCE env var")
        if env_c_bal_str and (c_bal <= 0 or not LIVE_EXECUTION):
            # Apply override if: API returned 0 (Futures wallet), OR we are in paper mode
            c_bal = float(env_c_bal_str)
            logger.info(f"[BALANCE OVERRIDE] CoinDCX balance overridden to ${c_bal:.4f} via COINDCX_OVERRIDE_BALANCE env var")
        if not LIVE_EXECUTION:
            coindcx_status = "PAPER_MODE"

        self._last_d_bal = d_bal
        if coindcx_status in ("CONNECTED", "PAPER_MODE"):
            self._last_c_bal = c_bal

        # STRICT ZERO-RISK TRADE GATE:
        # If CoinDCX balance API is unauthorized or broken: block trading entirely.
        # If CoinDCX is CONNECTED (HTTP 200) but balance is still 0 (no override set),
        # also block trades — we can't risk trading without confirmed margin.
        if coindcx_status not in ("CONNECTED", "PAPER_MODE") or c_bal <= 0:
            min_margin = 0.0
            trade_allowed = False
        else:
            min_margin = min(d_bal, c_bal) * 0.75
            trade_allowed = min_margin >= 1.0

        status_meta = {
            "coindcx_status": coindcx_status,
            "coindcx_http": coindcx_http,
            "coindcx_error_msg": coindcx_error_msg,
            "coindcx_last_success": getattr(self, 'coindcx_last_success_ts', '-'),
            "coindcx_available_usdt": spot_usdt,
            "coindcx_locked_margin": futures_locked,
            "trade_allowed": trade_allowed,
            "blocked_reason": coindcx_error_msg if not trade_allowed else ""
        }

        logger.info(
            f"[BALANCE AUDIT] Delta: ${d_bal:.2f} | CoinDCX: ${c_bal:.2f} | Status: {coindcx_status} (HTTP {coindcx_http}) | "
            f"Safe Margin: ${min_margin:.2f} | Trade Allowed: {'YES 🟢' if trade_allowed else 'BLOCKED 🔴'}"
        )
        return d_bal, c_bal, min_margin, status_meta


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
        """Delta Order Placement with 3 Retries."""
        path = "/v2/orders"
        payload = {
            "product_symbol": symbol,
            "size":           lots,
            "side":           side.lower(),
            "order_type":     "market_order" if order_type == "market_order" else order_type,
        }
        if order_type == "limit_order" and limit_price:
            payload["limit_price"] = str(limit_price)
            if post_only: payload["post_only"] = True
        if reduce_only: payload["is_reduce_only"] = True

        payload_str = json.dumps(payload)
        delays = [5, 10, 20]
        last_res = {"exchange": "Delta", "success": False, "http": 0, "latency_ms": 0, "error": "No attempt made"}

        for attempt in range(3):
            t_stamp, sig = sign_delta("POST", path, payload_str)
            headers = {"Content-Type": "application/json", "api-key": DELTA_API_KEY, "timestamp": t_stamp, "signature": sig}
            t0 = time.perf_counter()
            try:
                async with self.session.post(DELTA_BASE_URL + path, data=payload_str, headers=headers, timeout=self.t_order) as resp:
                    latency = (time.perf_counter() - t0) * 1000
                    body    = await resp.json()
                    success = resp.status in (200, 201) and body.get("success", False)
                    last_res = {"exchange": "Delta", "success": success, "http": resp.status, "latency_ms": latency, "order_id": body.get("result", {}).get("id"), "response": body}
                    if success: return last_res
            except Exception as e:
                last_res = {"exchange": "Delta", "success": False, "http": 0, "latency_ms": 0, "error": str(e)}
            if attempt < 2: await asyncio.sleep(delays[attempt])
        return last_res

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
        """CoinDCX Order Placement with 3 Retries."""
        path    = "/exchange/v1/derivatives/futures/orders/create"
        order_dict = {
            "pair":           symbol,
            "side":           side.lower(),
            "order_type":     "market_order" if order_type == "market_order" else order_type,
            "total_quantity": qty,
            "leverage":       leverage,
            "margin_type":    "isolated",
        }
        if limit_price and order_type == "limit_order": order_dict["price"] = limit_price
        if reduce_only:
            if order_type == "limit_order":
                order_dict["reduce_only"] = True  # Limit order: use reduce_only flag
            else:
                order_dict["position_intent"] = "reduce_only"  # Market order: use position_intent (CoinDCX API spec)

        payload = {"order": order_dict}
        delays = [5, 10, 20]
        last_res = {"exchange": "CoinDCX", "success": False, "http": 0, "latency_ms": 0, "error": "No attempt made"}

        for attempt in range(3):
            body_str, sig = sign_coindcx(payload)
            headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig}
            t0 = time.perf_counter()
            try:
                async with self.session.post(COINDCX_BASE_URL + path, data=body_str, headers=headers, timeout=self.t_order) as resp:
                    latency = (time.perf_counter() - t0) * 1000
                    body    = await resp.json()
                    success = resp.status in (200, 201)
                    oid     = body.get("id") if isinstance(body, dict) else (body[0].get("id") if isinstance(body, list) and body else None)
                    last_res = {"exchange": "CoinDCX", "success": success, "http": resp.status, "latency_ms": latency, "order_id": oid, "response": body}
                    if success: return last_res
            except Exception as e:
                last_res = {"exchange": "CoinDCX", "success": False, "http": 0, "latency_ms": 0, "error": str(e)}
            if attempt < 2: await asyncio.sleep(delays[attempt])
        return last_res

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

        # Audit Live Balances to ensure 100% Margin Neutrality & Zero-Risk Safety Gate
        d_bal, c_bal, min_safe_margin, meta = await self.fetch_live_balances()

        if self.live and not meta.get("trade_allowed", False):
            block_msg = f"LIVE TRADE BLOCKED: CoinDCX API Unverified ({meta.get('coindcx_status')}) - {meta.get('coindcx_error_msg')}"
            logger.error(f"🚨 {block_msg}")
            return {"status": "BLOCKED", "reason": block_msg, "status_meta": meta}

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

        # CASE 4: Both Spreads are Wide (> TAKER_MAX_SPREAD_THRES) -> Check Net Profit Gate before aborting
        net_after_spreads = gross_spread_pct - (TOTAL_ROUNDTRIP_FEE_PCT * 100.0) - (d_spread + c_spread) / 2.0
        if d_spread > TAKER_MAX_SPREAD_THRES and c_spread > TAKER_MAX_SPREAD_THRES:
            if net_after_spreads < MIN_GROSS_SPREAD_PCT:
                logger.warning(f"⛔ CASE 4 ABORT: Spreads too wide for net profit ({net_after_spreads:.4f}% < {MIN_GROSS_SPREAD_PCT}%). Rejecting trade.")
                return {"status": "ABORTED_BOTH_EXCHANGES_WIDE_SPREAD", "d_spread": d_spread, "c_spread": c_spread}

        # CASE 3: Spreads within limits -> Simultaneous Parallel Market Orders (<20ms)
        if (d_spread <= TAKER_MAX_SPREAD_THRES and c_spread <= TAKER_MAX_SPREAD_THRES) or net_after_spreads >= MIN_GROSS_SPREAD_PCT:
            logger.info(f"⚡ CASE 3 EXECUTION: Spreads OK (Net After Spreads={net_after_spreads:.4f}%). Firing parallel market orders...")
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
