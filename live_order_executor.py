"""
Live Order Executor - Funding Arbitrage Bot
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

DELTA_BASE_URL   = os.getenv("DELTA_BASE_URL",   "https://api.india.delta.exchange")
COINDCX_BASE_URL = os.getenv("COINDCX_BASE_URL", "https://api.coindcx.com")

DELTA_API_KEY      = os.getenv("DELTA_API_KEY",      "")
DELTA_API_SECRET   = os.getenv("DELTA_API_SECRET",   "")
COINDCX_API_KEY    = os.getenv("COINDCX_API_KEY",    "")
COINDCX_API_SECRET = os.getenv("COINDCX_API_SECRET", "")

LIVE_EXECUTION = os.getenv("LIVE_EXECUTION", "false").strip().lower() == "true"

FEE_TAKER_DELTA_ENTRY   = 0.00059
FEE_SCALPER_DELTA_EXIT  = 0.00000
FEE_TAKER_COINDCX_ENTRY = 0.00059
FEE_MAKER_COINDCX_EXIT  = 0.000236
TOTAL_ROUNDTRIP_FEE_PCT = 0.001416

MAX_SLIP_PCT          = 0.05
DRAWDOWN_OVERRIDE_PCT = 10.0

LOT_SIZES = {"BTC": 0.001, "ETH": 0.01, "DEFAULT": 1.0}

# ── Symmetric Leverage Tables (AGENTS.md: both legs must use same leverage) ──
# Delta Exchange India max leverage per coin
DELTA_MAX_LEVERAGE = {
    "BTC": 100.0, "ETH": 100.0,
    "SOL": 50.0, "XRP": 50.0, "DOGE": 50.0, "BNB": 50.0,
    "1000SATS": 50.0, "ADA": 50.0, "AVAX": 50.0, "LINK": 50.0,
    "NEAR": 50.0, "SUI": 50.0, "PEPE": 50.0, "SHIB": 50.0, "WIF": 50.0,
    "_DEFAULT": 20.0,
}

# CoinDCX (Binance-backed) max leverage per coin
COINDCX_MAX_LEVERAGE = {
    "BTC": 125.0, "ETH": 100.0,
    "SOL": 50.0, "XRP": 50.0, "DOGE": 50.0, "BNB": 75.0,
    "1000SATS": 20.0, "ADA": 75.0, "AVAX": 50.0, "LINK": 50.0,
    "NEAR": 50.0, "SUI": 50.0, "PEPE": 50.0, "SHIB": 50.0, "WIF": 50.0,
    "_DEFAULT": 20.0,
}

def get_symmetric_leverage(coin: str) -> int:
    """
    Returns SYMMETRIC leverage = min(delta_max, coindcx_max).
    Both legs always trade at the SAME leverage — no imbalance between exchanges.
    Example: Delta=100x, CoinDCX=20x → Both use 20x.
    """
    c = coin.upper()
    d_lev = DELTA_MAX_LEVERAGE.get(c, DELTA_MAX_LEVERAGE["_DEFAULT"])
    c_lev = COINDCX_MAX_LEVERAGE.get(c, COINDCX_MAX_LEVERAGE["_DEFAULT"])
    return int(min(d_lev, c_lev))

logger = logging.getLogger("LiveOrderExecutor")



def sign_delta(method: str, path: str, payload_str: str) -> Tuple[str, str]:
    timestamp = str(int(time.time()))
    message   = method + timestamp + path + payload_str
    sig = hmac.new(DELTA_API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return timestamp, sig


def sign_coindcx(payload: dict) -> Tuple[str, str]:
    payload["timestamp"] = int(time.time() * 1000)
    body_str = json.dumps(payload, separators=(",", ":"))
    sig = hmac.new(COINDCX_API_SECRET.encode("utf-8"), body_str.encode("utf-8"), hashlib.sha256).hexdigest()
    return body_str, sig


def calculate_sizing(coin: str, mark_price: float, target_notional_usd: float) -> Tuple[int, float, float]:
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
        self.t_order = aiohttp.ClientTimeout(total=3, connect=1, sock_read=2)
        self.t_scan  = aiohttp.ClientTimeout(total=5, connect=2, sock_read=4)
        mode = "LIVE" if self.live else "PAPER (LIVE_EXECUTION=false)"
        logger.info(f"LiveOrderExecutor initialized - Mode: {mode}")
        if self.live:
            missing = []
            if not DELTA_API_KEY:      missing.append("DELTA_API_KEY")
            if not DELTA_API_SECRET:   missing.append("DELTA_API_SECRET")
            if not COINDCX_API_KEY:    missing.append("COINDCX_API_KEY")
            if not COINDCX_API_SECRET: missing.append("COINDCX_API_SECRET")
            if missing:
                raise EnvironmentError(f"LIVE_EXECUTION=true but missing: {missing}")

    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
            self.session = aiohttp.ClientSession(connector=connector, headers={"User-Agent": "FundingArbitrageBot/3.0"})

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _check_delta_slippage(self, symbol: str, side: str, qty: float) -> Tuple[bool, float]:
        try:
            url = f"{DELTA_BASE_URL}/v2/l2orderbook/{symbol}"
            async with self.session.get(url, timeout=self.t_scan) as resp:
                data = await resp.json()
            book   = data.get("result", {})
            levels = book.get("sell_book" if side.upper() == "BUY" else "buy_book", [])
            if not levels:
                return True, 0.0
            remaining, total_cost = qty, 0.0
            for lvl in levels[:10]:
                px   = float(lvl.get("price", 0))
                sz   = float(lvl.get("size", 0))
                fill = min(remaining, sz)
                total_cost += fill * px
                remaining  -= fill
                if remaining <= 0:
                    break
            if remaining > 0 or total_cost == 0:
                return True, 0.0
            vwap = total_cost / qty
            mid  = float(levels[0].get("price", vwap))
            slip = abs(vwap - mid) / mid * 100.0 if mid > 0 else 0.0
            ok   = slip <= MAX_SLIP_PCT
            logger.info(f"   [Slip] Delta {symbol}: VWAP={vwap:.6f} Mid={mid:.6f} Slip={slip:.4f}% -> {'OK' if ok else 'ABORT'}")
            return ok, slip
        except Exception as e:
            logger.warning(f"   [Slip] Delta OB check failed ({e}) - allowing")
            return True, 0.0

    async def _check_coindcx_slippage(self, symbol: str, side: str, qty: float) -> Tuple[bool, float]:
        try:
            async with self.session.get("https://api.coindcx.com/exchange/ticker", timeout=self.t_scan) as resp:
                data = await resp.json()
            pair   = symbol.replace("B-", "").replace("_", "")
            ticker = next((t for t in data if t.get("market") == pair), None)
            if not ticker:
                return True, 0.0
            best_ask = float(ticker.get("ask") or ticker.get("best_ask") or 0)
            best_bid = float(ticker.get("bid") or ticker.get("best_bid") or 0)
            mid      = (best_ask + best_bid) / 2.0 if best_ask and best_bid else 0.0
            fill_px  = best_ask if side.upper() == "BUY" else best_bid
            slip     = abs(fill_px - mid) / mid * 100.0 if mid > 0 else 0.0
            ok       = slip <= MAX_SLIP_PCT
            logger.info(f"   [Slip] CoinDCX {symbol}: Fill={fill_px:.6f} Mid={mid:.6f} Slip={slip:.4f}% -> {'OK' if ok else 'ABORT'}")
            return ok, slip
        except Exception as e:
            logger.warning(f"   [Slip] CoinDCX OB check failed ({e}) - allowing")
            return True, 0.0

    async def _delta_order(self, symbol: str, side: str, lots: int, reduce_only: bool = False) -> Dict:
        path    = "/v2/orders"
        payload = {"product_symbol": symbol, "size": lots, "side": side.lower(), "order_type": "market_order"}
        if reduce_only:
            payload["is_reduce_only"] = True
        payload_str  = json.dumps(payload)
        t_stamp, sig = sign_delta("POST", path, payload_str)
        headers = {"Content-Type": "application/json", "api-key": DELTA_API_KEY, "timestamp": t_stamp, "signature": sig}
        t0 = time.perf_counter()
        try:
            async with self.session.post(DELTA_BASE_URL + path, data=payload_str, headers=headers, timeout=self.t_order) as resp:
                latency = (time.perf_counter() - t0) * 1000
                body    = await resp.json()
                success = resp.status in (200, 201) and body.get("success", False)
                return {"exchange": "Delta", "success": success, "http": resp.status, "latency_ms": latency, "order_id": body.get("result", {}).get("id"), "response": body}
        except Exception as e:
            return {"exchange": "Delta", "success": False, "http": 0, "latency_ms": 0, "error": str(e)}

    async def _coindcx_order(self, symbol: str, side: str, qty: float, leverage: int = 20, reduce_only: bool = False) -> Dict:
        path    = "/exchange/v1/derivatives/futures/orders/create"
        payload = {"pair": symbol, "side": side.lower(), "order_type": "market_order", "total_quantity": qty, "leverage": leverage}
        if reduce_only:
            payload["reduce_only"] = True
        body_str, sig = sign_coindcx(payload)
        headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig}
        t0 = time.perf_counter()
        try:
            async with self.session.post(COINDCX_BASE_URL + path, data=body_str, headers=headers, timeout=self.t_order) as resp:
                latency = (time.perf_counter() - t0) * 1000
                body    = await resp.json()
                success = resp.status in (200, 201)
                oid     = body.get("id") if isinstance(body, dict) else (body[0].get("id") if isinstance(body, list) and body else None)
                return {"exchange": "CoinDCX", "success": success, "http": resp.status, "latency_ms": latency, "order_id": oid, "response": body}
        except Exception as e:
            return {"exchange": "CoinDCX", "success": False, "http": 0, "latency_ms": 0, "error": str(e)}

    async def execute_entry(self, delta_sym, delta_side, delta_lots, coindcx_sym, coindcx_side, exact_qty, leverage, coin, mark_delta, mark_coindcx, notional_usd, gross_spread_pct) -> Dict:
        await self._ensure_session()
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

        if not self.live:
            await asyncio.sleep(0.015)
            logger.info(f"[{ts}] PAPER ENTRY: {delta_side} {delta_lots}Lots {delta_sym} | {coindcx_side} {exact_qty} {coindcx_sym}")
            return {"status": "PAPER", "latency_ms": 15.0, "delta_lots": delta_lots, "exact_qty": exact_qty, "notional_usd": notional_usd, "leverage": leverage}

        slip_d_ok, slip_d = await self._check_delta_slippage(delta_sym, delta_side, exact_qty)
        slip_c_ok, slip_c = await self._check_coindcx_slippage(coindcx_sym, coindcx_side, exact_qty)
        if not slip_d_ok or not slip_c_ok:
            logger.warning(f"SLIPPAGE GATE ABORT: Delta={slip_d:.4f}% CoinDCX={slip_c:.4f}% (Max={MAX_SLIP_PCT}%)")
            return {"status": "ABORTED_SLIPPAGE", "slip_delta": slip_d, "slip_coindcx": slip_c}

        t0 = time.perf_counter()
        res_d, res_c = await asyncio.gather(
            self._delta_order(delta_sym, delta_side, delta_lots),
            self._coindcx_order(coindcx_sym, coindcx_side, exact_qty, leverage=leverage),
        )
        total_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"[{ts}] LIVE ENTRY ({total_ms:.1f}ms) Delta:HTTP{res_d['http']} OK={res_d['success']} | CoinDCX:HTTP{res_c['http']} OK={res_c['success']}")

        if not res_d["success"] and not res_c["success"]:
            logger.error("BOTH LEGS FAILED")
            return {"status": "BOTH_FAILED", "delta": res_d, "coindcx": res_c}
        if res_c["success"] and not res_d["success"]:
            logger.error("Delta FAILED, emergency closing CoinDCX...")
            rev = "buy" if coindcx_side.upper() == "SELL" else "sell"
            await self._coindcx_order(coindcx_sym, rev, exact_qty, leverage=leverage, reduce_only=True)
            return {"status": "DELTA_FAILED_EMERGENCY_CLOSED", "delta": res_d, "coindcx": res_c}
        if res_d["success"] and not res_c["success"]:
            logger.error("CoinDCX FAILED, emergency closing Delta...")
            rev = "buy" if delta_side.upper() == "SELL" else "sell"
            await self._delta_order(delta_sym, rev, delta_lots, reduce_only=True)
            return {"status": "COINDCX_FAILED_EMERGENCY_CLOSED", "delta": res_d, "coindcx": res_c}

        return {"status": "SUCCESS_LIVE", "latency_ms": total_ms, "delta_order_id": res_d["order_id"], "coindcx_order_id": res_c["order_id"], "delta_lots": delta_lots, "exact_qty": exact_qty, "notional_usd": notional_usd, "leverage": leverage, "mark_delta": mark_delta, "mark_coindcx": mark_coindcx}

    async def execute_exit(self, delta_sym, delta_side, delta_lots, coindcx_sym, coindcx_side, exact_qty, leverage, notional_usd, gross_spread_pct, trigger_reason="Scalper Exit T+2s") -> Dict:
        await self._ensure_session()
        exit_delta_side   = "buy" if delta_side.upper()   == "SELL" else "sell"
        exit_coindcx_side = "buy" if coindcx_side.upper() == "SELL" else "sell"
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

        gross_usd = notional_usd * (gross_spread_pct / 100.0)
        fees_usd  = notional_usd * TOTAL_ROUNDTRIP_FEE_PCT
        net_usd   = gross_usd - fees_usd

        if not self.live:
            await asyncio.sleep(0.015)
            logger.info(f"[{ts}] PAPER EXIT ({trigger_reason}) Gross=+${gross_usd:.4f} Fees=-${fees_usd:.4f} NET=+${net_usd:.4f}")
            return {"status": "PAPER", "net_pnl_usd": net_usd, "gross_usd": gross_usd, "fees_usd": fees_usd}

        t0 = time.perf_counter()
        res_d, res_c = await asyncio.gather(
            self._delta_order(delta_sym, exit_delta_side, delta_lots, reduce_only=True),
            self._coindcx_order(coindcx_sym, exit_coindcx_side, exact_qty, leverage=leverage, reduce_only=True),
        )
        total_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"[{ts}] LIVE EXIT ({trigger_reason}) ({total_ms:.1f}ms) | Gross=+${gross_usd:.4f} Fees=-${fees_usd:.4f} NET=+${net_usd:.4f}")
        return {"status": "SUCCESS_LIVE", "net_pnl_usd": net_usd, "gross_usd": gross_usd, "fees_usd": fees_usd, "latency_ms": total_ms, "delta": res_d, "coindcx": res_c}


_executor_instance: Optional[LiveOrderExecutor] = None

def get_executor() -> LiveOrderExecutor:
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = LiveOrderExecutor()
    return _executor_instance
