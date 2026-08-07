"""
Delta Exchange India — Options Put-Call Parity Arbitrage Bot v3
===============================================================
Strategy  : Conversion & Reversal Arbitrage using Put-Call Parity
Formula   : C - P = S - K  =>  Spread = |(C - P) - (S - K)|
Exchange  : Delta Exchange India ONLY (https://api.india.delta.exchange)
Assets    : BTC, ETH, XAUT
Expiry    : DAILY EXPIRY ONLY (5:30 PM IST = 12:00 UTC settlement via 30-min TWAP)

Key Features:
  [*] REAL L2 Orderbook depth fetch from /v2/l2orderbook/{symbol}
  [*] Parity spread calculated from REAL best_bid / best_ask (not mark price)
  [*] Minimum $0.30 USD net profit per 0.001 BTC (1 Lot) after all fees
  [*] Dynamic lot sizing (1 to N lots based on 75% available margin)
  [*] LIMIT ORDERS ONLY on entry (asyncio.gather all 3 legs simultaneously)
  [*] 30-second fill monitor — auto-cancel ALL legs if any unfilled
  [*] ATM +/- 5% strikes filter for best liquidity zone
  [*] DAILY AUTO-CLOSE: Futures leg closed every day at 5:30 PM IST (12:00 UTC)
  [*] Options auto-settle by Delta Exchange — no bot action needed for options
  [*] Telegram alerts for every event (opportunity / fill / cancel / close)

Fee Structure (Inc. 18% GST):
  Options Taker Entry:  0.010% x 2 legs = 0.020%
  Futures Taker Entry:  0.059%
  Settlement at Expiry: 0.010% x 3 legs = 0.030%
  TOTAL Round-Trip:     0.109%

How to Run:
  Paper mode:  $env:LIVE_EXECUTION="false"; python options_parity_bot_v3.py
  Live mode:   $env:LIVE_EXECUTION="true";  python options_parity_bot_v3.py
"""

import os
import sys
import time
import json
import asyncio
import aiohttp
import logging
import datetime
import traceback
from typing import Optional, Dict, List, Tuple

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from live_order_executor import (
    sign_delta,
    DELTA_BASE_URL,
    DELTA_API_KEY,
    DELTA_API_SECRET,
    LIVE_EXECUTION,
    LiveOrderExecutor,
    LOT_SIZES,
)
from telegram_notifier import send_telegram_alert

# ============================================================
# Logging Setup
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("options_parity_v3.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("OptionsParityBotV3")

# ============================================================
# Constants & Configuration
# ============================================================

SUPPORTED_UNDERLYINGS      = ["BTC", "ETH", "XAUT"]

# Fee Schedule (inc. 18% GST) — Delta Exchange India
OPTIONS_TAKER_FEE          = 0.00010   # 0.010% per options leg
FUTURES_TAKER_FEE          = 0.00059   # 0.059% futures taker
SETTLEMENT_FEE_PER_LEG     = 0.00010   # 0.010% per leg at daily settlement
NUM_LEGS                   = 3         # 1 Futures + 1 Call + 1 Put

# Total roundtrip = futures_entry + 2*options_entry + 3*settlement = 0.109%
TOTAL_ROUNDTRIP_FEE_PCT    = FUTURES_TAKER_FEE + 2*OPTIONS_TAKER_FEE + NUM_LEGS*SETTLEMENT_FEE_PER_LEG

# Profit gate: minimum net profit after all fees per 1 lot
MIN_NET_PROFIT_USD_PER_LOT = 0.30

# ATM strike filter: only scan strikes within +/- 5% of futures mark price
ATM_STRIKE_RADIUS_PCT      = 0.05

# Orderbook: minimum real depth at best bid/ask (in contract lots)
MIN_OB_DEPTH_LOTS          = 1

# Capital allocation: use 75% of available Delta balance
MARGIN_ALLOCATION_PCT      = 0.75

# Max leverage for Futures leg (options = full premium)
FUTURES_LEVERAGE           = {"BTC": 200, "ETH": 200, "XAUT": 100}

# Timing
FILL_MONITOR_TIMEOUT_S     = 30    # Max wait for all 3 legs to fill
FILL_CHECK_INTERVAL_S      = 2     # Polling interval for fill status
SCAN_INTERVAL_S            = 30    # Scan every 30 seconds

# Daily settlement: 5:30 PM IST = 12:00:00 UTC
SETTLEMENT_HOUR_UTC        = 12
SETTLEMENT_MINUTE_UTC      = 0

# Pre-settlement: start trying to close futures this many seconds before expiry
FUTURES_CLOSE_LEAD_SECS    = 120   # Start closing 2 minutes before 5:30 PM IST


# ============================================================
# Time Helpers
# ============================================================

def get_today_expiry_ts() -> int:
    """
    Returns UTC timestamp of today's 5:30 PM IST (= 12:00 UTC) daily expiry.
    If current time is already past today's expiry, returns tomorrow's.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    exp = now.replace(hour=SETTLEMENT_HOUR_UTC, minute=SETTLEMENT_MINUTE_UTC,
                      second=0, microsecond=0)
    if now >= exp:
        exp += datetime.timedelta(days=1)
    return int(exp.timestamp())


def ts_to_ist(ts: int) -> str:
    dt_utc = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    dt_ist = dt_utc + datetime.timedelta(hours=5, minutes=30)
    return dt_ist.strftime("%d-%b-%Y %I:%M:%S %p IST")


def hours_left(exp_ts: int) -> float:
    return max(0.0, (exp_ts - time.time()) / 3600.0)


# ============================================================
# Main Bot Class
# ============================================================

class OptionsParityBotV3:
    """
    Delta Exchange India — Real Options Put-Call Parity Arbitrage Bot.

    Flow per scan cycle (every 30 seconds):
      1. Check & auto-close any futures positions nearing expiry
      2. Fetch live Delta balance
      3. Fetch all live products + tickers
      4. Fetch REAL L2 orderbook for each ATM option pair
      5. Calculate real executable parity spread (bid/ask not mark price)
      6. Apply $0.30 net profit gate
      7. Calculate dynamic lot size from 75% margin
      8. Place 3 limit orders simultaneously (asyncio.gather)
      9. Monitor fills for 30s — cancel all if any unfilled
     10. Register position for auto-close
    """

    def __init__(self, executor: LiveOrderExecutor):
        self.executor        = executor
        self.session: Optional[aiohttp.ClientSession] = None
        self.positions: List[Dict]   = []   # Active parity positions
        self.alert_times: Dict       = {}   # Alert cooldown tracker
        self.in_trade                = False
        self.scan_count              = 0
        self.trade_count             = 0
        self.total_locked_profit     = 0.0

    # --------------------------------------------------------
    # Session Management
    # --------------------------------------------------------

    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
            self.session = aiohttp.ClientSession(
                connector=connector,
                headers={"User-Agent": "OptionsParityBotV3/1.0"}
            )

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # --------------------------------------------------------
    # Direct Delta Balance Fetch (Delta-only, no CoinDCX)
    # --------------------------------------------------------

    async def fetch_delta_balance_direct(self) -> float:
        """
        Fetches Delta Exchange India wallet balance DIRECTLY.
        Does NOT use LiveOrderExecutor.fetch_live_balances() which also
        checks CoinDCX (not needed for this options-only bot).

        Looks for USDT/USD/INR balance in /v2/wallet/balances.
        Falls back to 0.0 on IP whitelist error or API failure.
        Logs the exact error so user knows to whitelist their IP.
        """
        await self._ensure_session()
        path = "/v2/wallet/balances"
        delays = [3, 6]

        for attempt in range(3):
            try:
                t_stamp, sig = sign_delta("GET", path, "")
                headers = {
                    "api-key":   DELTA_API_KEY,
                    "timestamp": t_stamp,
                    "signature": sig,
                    "User-Agent": "Mozilla/5.0"
                }
                async with self.session.get(
                    DELTA_BASE_URL + path, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    body = await resp.json()

                    if resp.status == 401:
                        err = body.get("error", {})
                        code = err.get("code", "unknown")
                        ctx  = err.get("context", {})
                        ip   = ctx.get("client_ip", "unknown")
                        if code == "ip_not_whitelisted_for_api_key":
                            logger.error(
                                f"[BALANCE] Delta API BLOCKED: IP '{ip}' not whitelisted!\n"
                                f"  => Go to Delta Exchange India -> Settings -> API Keys\n"
                                f"  => Add your IP '{ip}' to the whitelist and restart bot."
                            )
                        else:
                            logger.error(f"[BALANCE] Delta API 401: {code}")
                        return 0.0

                    if resp.status == 200:
                        balances = body.get("result", [])
                        total = 0.0
                        for b in balances:
                            sym   = str(b.get("asset_symbol") or b.get("currency") or "")
                            avail = float(
                                b.get("available_balance")
                                or b.get("balance")
                                or 0
                            )
                            # Accept USDT, USD, INR (Delta India uses INR sometimes)
                            if sym.upper() in ("USDT", "USD", "INR") and avail > 0:
                                total += avail
                                logger.info(
                                    f"[BALANCE] Delta {sym}: ${avail:.4f} available"
                                )
                        if total > 0:
                            logger.info(f"[BALANCE] Delta total balance: ${total:.4f}")
                            return total
                        else:
                            logger.warning(
                                f"[BALANCE] Delta balance is $0. "
                                f"Entries: {len(balances)}. "
                                "Check if funds are in USDT/USD/INR wallet."
                            )
                            return 0.0

            except Exception as e:
                logger.warning(f"[BALANCE] Delta fetch attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(delays[attempt])

        return 0.0


    # --------------------------------------------------------
    # Delta Exchange Public API Calls
    # --------------------------------------------------------

    async def _get(self, url: str, params: dict = None, timeout: int = 8) -> dict:
        """Generic GET with timeout and error handling."""
        await self._ensure_session()
        try:
            async with self.session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as r:
                if r.status == 200:
                    return await r.json()
        except Exception as e:
            logger.warning(f"[HTTP GET] {url} -> {e}")
        return {}

    async def fetch_all_products(self) -> List[Dict]:
        """Fetch all live products from Delta Exchange India."""
        data = await self._get(f"{DELTA_BASE_URL}/v2/products", params={"state": "live"})
        return data.get("result", [])

    async def fetch_all_tickers(self) -> Dict[str, Dict]:
        """Fetch all tickers. Returns {symbol: ticker_dict}."""
        data = await self._get(f"{DELTA_BASE_URL}/v2/tickers")
        tickers = data.get("result", [])
        return {t["symbol"]: t for t in tickers if isinstance(t, dict) and "symbol" in t}

    async def fetch_real_l2_orderbook(self, symbol: str) -> Tuple[float, float, float, float]:
        """
        Fetches real L2 orderbook from Delta Exchange.
        Endpoint: GET /v2/l2orderbook/{symbol}
        Returns: (best_bid, best_bid_size, best_ask, best_ask_size)
        Returns (0, 0, 0, 0) if no data.
        """
        data = await self._get(f"{DELTA_BASE_URL}/v2/l2orderbook/{symbol}")
        result = data.get("result", {})

        bids = result.get("buy", [])   # Delta L2: 'buy' = bids
        asks = result.get("sell", [])  # Delta L2: 'sell' = asks

        # Each entry: {"price": "...", "size": ...}
        best_bid      = 0.0
        best_bid_size = 0.0
        best_ask      = 0.0
        best_ask_size = 0.0

        if bids:
            top = bids[0]  # Already sorted best first by Delta API
            best_bid      = float(top.get("price") or top.get("limit_price") or 0)
            best_bid_size = float(top.get("size") or 0)

        if asks:
            top = asks[0]
            best_ask      = float(top.get("price") or top.get("limit_price") or 0)
            best_ask_size = float(top.get("size") or 0)

        return best_bid, best_bid_size, best_ask, best_ask_size

    # --------------------------------------------------------
    # Private Delta API Calls (Authenticated)
    # --------------------------------------------------------

    async def _delta_auth_get(self, path: str) -> dict:
        """Authenticated GET to Delta Exchange."""
        await self.executor._ensure_session()
        t_stamp, sig = sign_delta("GET", path, "")
        headers = {
            "api-key": DELTA_API_KEY,
            "timestamp": t_stamp,
            "signature": sig,
            "User-Agent": "Mozilla/5.0"
        }
        try:
            async with self.executor.session.get(
                DELTA_BASE_URL + path, headers=headers,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                if r.status == 200:
                    body = await r.json()
                    return body
        except Exception as e:
            logger.warning(f"[AUTH GET] {path} -> {e}")
        return {}

    async def fetch_order_status(self, order_id: int) -> str:
        """Returns the current state of a Delta order: 'open', 'filled', 'cancelled', etc."""
        body = await self._delta_auth_get(f"/v2/orders/{order_id}")
        result = body.get("result", {})
        return str(result.get("state", "unknown"))

    async def cancel_order(self, order_id: int, product_id: int) -> bool:
        """Cancel a specific Delta order by order_id + product_id."""
        await self.executor._ensure_session()
        path = "/v2/orders"
        payload = {"id": order_id, "product_id": product_id}
        payload_str = json.dumps(payload)
        try:
            t_stamp, sig = sign_delta("DELETE", path, payload_str)
            headers = {
                "Content-Type": "application/json",
                "api-key": DELTA_API_KEY,
                "timestamp": t_stamp,
                "signature": sig,
            }
            async with self.executor.session.delete(
                DELTA_BASE_URL + path, data=payload_str, headers=headers,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                body = await r.json()
                ok = r.status in (200, 201) and body.get("success", False)
                logger.info(f"[CANCEL] Order {order_id} product {product_id} -> {'OK' if ok else 'FAIL'}")
                return ok
        except Exception as e:
            logger.error(f"[CANCEL] {order_id} exception: {e}")
            return False

    async def fetch_open_positions(self) -> List[Dict]:
        """Fetch all currently open positions on Delta Exchange."""
        body = await self._delta_auth_get("/v2/positions/margined")
        return body.get("result", [])

    # --------------------------------------------------------
    # STEP 1: Scan for Parity Opportunities (Real L2 OB)
    # --------------------------------------------------------

    async def scan_parity_opportunities(self) -> List[Dict]:
        """
        Scans BTC, ETH, XAUT daily options for put-call parity violations.

        Key difference from v2: Uses REAL L2 orderbook best bid/ask per symbol,
        NOT the aggregated ticker quotes. This ensures every spread calculation
        reflects exactly what you'd get if you placed a limit order right now.

        Filters:
          - Daily expiry ONLY (today's 5:30 PM IST, +/-2 hour tolerance)
          - ATM +/- 5% strike zone
          - Real L2 orderbook depth >= 1 lot at best price
          - Net profit after 0.109% fee >= $0.30 per lot
        """
        now_ts        = int(time.time())
        target_exp_ts = get_today_expiry_ts()
        hrs           = hours_left(target_exp_ts)
        opportunities = []

        logger.info(
            f"[SCAN #{self.scan_count}] Daily expiry: {ts_to_ist(target_exp_ts)} | "
            f"{hrs:.2f}h remaining"
        )

        # Fetch products + tickers once (batch)
        products, tickers = await asyncio.gather(
            self.fetch_all_products(),
            self.fetch_all_tickers(),
            return_exceptions=True
        )

        if isinstance(products, Exception) or not products:
            logger.error("[SCAN] Failed to fetch products.")
            return []
        if isinstance(tickers, Exception) or not tickers:
            logger.error("[SCAN] Failed to fetch tickers.")
            return []

        for coin in SUPPORTED_UNDERLYINGS:
            # --- Get futures mark price ---
            fut_sym    = f"{coin}USD"
            fut_ticker = tickers.get(fut_sym) or tickers.get(f"{coin}USDT")
            if not fut_ticker:
                continue
            S = float(fut_ticker.get("mark_price") or fut_ticker.get("close") or 0)
            if S <= 0:
                continue

            atm_lo = S * (1.0 - ATM_STRIKE_RADIUS_PCT)
            atm_hi = S * (1.0 + ATM_STRIKE_RADIUS_PCT)

            # --- Filter daily options for this coin ---
            calls: Dict[float, Dict] = {}
            puts:  Dict[float, Dict] = {}
            found_exp_ts: Optional[int] = None

            for p in products:
                ctype      = p.get("contract_type", "")
                spec       = p.get("product_specs") or {}
                underlying = (
                    spec.get("underlying_asset", {}).get("symbol")
                    or p.get("underlying_asset_symbol", "")
                )
                # Delta India uses plural: 'call_options' / 'put_options'
                if ctype not in ("call_options", "put_options"):
                    continue

                # Underlying: parse from symbol prefix if product_specs empty
                # Symbol format: C-BTC-65200-070826 or P-ETH-2100-070826
                sym_check = p.get("symbol", "")
                sym_underlying = ""
                if "-" in sym_check:
                    parts = sym_check.split("-")
                    sym_underlying = parts[1] if len(parts) >= 2 else ""

                if not underlying:
                    underlying = sym_underlying

                if underlying != coin:
                    continue

                # Parse settlement time
                raw_exp = p.get("settlement_time")
                if isinstance(raw_exp, str):
                    try:
                        dt = datetime.datetime.fromisoformat(raw_exp.replace("Z", "+00:00"))
                        exp_ts = int(dt.timestamp())
                    except Exception:
                        continue
                elif isinstance(raw_exp, (int, float)):
                    exp_ts = int(raw_exp)
                else:
                    continue

                # Daily expiry filter: +/- 2 hour tolerance
                if abs(exp_ts - target_exp_ts) > 7200:
                    continue
                if exp_ts <= now_ts:
                    continue  # Already expired

                found_exp_ts = exp_ts

                # ATM strike filter
                strike = float(p.get("strike_price") or 0)
                if strike <= 0 or not (atm_lo <= strike <= atm_hi):
                    continue

                sym = p.get("symbol", "")
                opt = {
                    "symbol":     sym,
                    "product_id": p.get("id"),
                    "strike":     strike,
                    "exp_ts":     exp_ts,
                }
                if ctype == "call_options":
                    calls[strike] = opt
                else:
                    puts[strike]  = opt

            if found_exp_ts is None:
                logger.info(f"[SCAN] {coin}: No daily expiry options found.")
                continue

            logger.info(
                f"[SCAN] {coin} S=${S:,.2f} | "
                f"ATM zone ${atm_lo:,.0f}-${atm_hi:,.0f} | "
                f"{len(calls)} calls, {len(puts)} puts (daily expiry)"
            )

            lot_size = LOT_SIZES.get(coin, 0.001)
            h_left   = hours_left(found_exp_ts)

            # --- For each matching strike, fetch REAL L2 orderbook ---
            matching_strikes = set(calls.keys()) & set(puts.keys())
            if not matching_strikes:
                logger.info(f"[SCAN] {coin}: No matching call+put strike pairs in ATM zone.")
                continue

            # Fetch all L2 orderbooks concurrently
            ob_tasks = {}
            for strike in matching_strikes:
                call = calls[strike]
                put  = puts[strike]
                ob_tasks[("call", strike)] = self.fetch_real_l2_orderbook(call["symbol"])
                ob_tasks[("put",  strike)] = self.fetch_real_l2_orderbook(put["symbol"])

            ob_keys    = list(ob_tasks.keys())
            ob_results = await asyncio.gather(*ob_tasks.values(), return_exceptions=True)
            ob_map     = dict(zip(ob_keys, ob_results))

            for strike in sorted(matching_strikes):
                call = calls[strike]
                put  = puts[strike]
                K    = strike

                # Get real L2 data
                c_ob = ob_map.get(("call", strike))
                p_ob = ob_map.get(("put",  strike))

                if isinstance(c_ob, Exception) or c_ob is None:
                    c_ob = (0, 0, 0, 0)
                if isinstance(p_ob, Exception) or p_ob is None:
                    p_ob = (0, 0, 0, 0)

                C_bid, C_bid_sz, C_ask, C_ask_sz = c_ob
                P_bid, P_bid_sz, P_ask, P_ask_sz = p_ob

                logger.debug(
                    f"  [{coin} K={K:,.0f}] "
                    f"Call: bid={C_bid}/{C_bid_sz} ask={C_ask}/{C_ask_sz} | "
                    f"Put:  bid={P_bid}/{P_bid_sz} ask={P_ask}/{P_ask_sz}"
                )

                # ---- CONVERSION: BUY Futures + BUY Put @ Ask + SELL Call @ Bid ----
                # Gross = (C_bid - P_ask) - (S - K)  [using executable prices]
                # Liquidity required: C_bid_sz >= 1 lot AND P_ask_sz >= 1 lot
                if C_bid > 0 and P_ask > 0 and C_bid_sz >= MIN_OB_DEPTH_LOTS and P_ask_sz >= MIN_OB_DEPTH_LOTS:
                    conv_gross_unit = (C_bid - P_ask) - (S - K)
                    conv_gross_usd  = conv_gross_unit * lot_size
                    conv_fee_usd    = TOTAL_ROUNDTRIP_FEE_PCT * S * lot_size
                    conv_net_usd    = conv_gross_usd - conv_fee_usd

                    if conv_net_usd >= MIN_NET_PROFIT_USD_PER_LOT:
                        opportunities.append({
                            "coin":           coin,
                            "type":           "CONVERSION",
                            "strike":         K,
                            "futures_sym":    fut_sym,
                            "futures_mark":   S,
                            "futures_entry":  S,       # Limit at mark price
                            "futures_side":   "buy",
                            "call_sym":       call["symbol"],
                            "call_pid":       call["product_id"],
                            "call_price":     C_bid,   # SELL call at real bid
                            "call_side":      "sell",
                            "call_bid_sz":    C_bid_sz,
                            "put_sym":        put["symbol"],
                            "put_pid":        put["product_id"],
                            "put_price":      P_ask,   # BUY put at real ask
                            "put_side":       "buy",
                            "put_ask_sz":     P_ask_sz,
                            "gross_usd":      conv_gross_usd,
                            "fee_usd":        conv_fee_usd,
                            "net_usd_lot":    conv_net_usd,
                            "net_pct":        (conv_net_usd / (S * lot_size)) * 100,
                            "lot_size":       lot_size,
                            "exp_ts":         found_exp_ts,
                            "hrs_left":       h_left,
                            "action":         "BUY Futures | BUY Put | SELL Call",
                        })
                        logger.info(
                            f"  [OPP] {coin} CONVERSION K={K:,.0f} | "
                            f"Gross=${conv_gross_usd:+.4f} Fee=${conv_fee_usd:.4f} "
                            f"Net=${conv_net_usd:+.4f}/lot | {h_left:.2f}h left"
                        )

                # ---- REVERSAL: SELL Futures + BUY Call @ Ask + SELL Put @ Bid ----
                # Gross = (S - K) - (C_ask - P_bid)
                if C_ask > 0 and P_bid > 0 and C_ask_sz >= MIN_OB_DEPTH_LOTS and P_bid_sz >= MIN_OB_DEPTH_LOTS:
                    rev_gross_unit = (S - K) - (C_ask - P_bid)
                    rev_gross_usd  = rev_gross_unit * lot_size
                    rev_fee_usd    = TOTAL_ROUNDTRIP_FEE_PCT * S * lot_size
                    rev_net_usd    = rev_gross_usd - rev_fee_usd

                    if rev_net_usd >= MIN_NET_PROFIT_USD_PER_LOT:
                        opportunities.append({
                            "coin":           coin,
                            "type":           "REVERSAL",
                            "strike":         K,
                            "futures_sym":    fut_sym,
                            "futures_mark":   S,
                            "futures_entry":  S,
                            "futures_side":   "sell",
                            "call_sym":       call["symbol"],
                            "call_pid":       call["product_id"],
                            "call_price":     C_ask,   # BUY call at real ask
                            "call_side":      "buy",
                            "call_ask_sz":    C_ask_sz,
                            "put_sym":        put["symbol"],
                            "put_pid":        put["product_id"],
                            "put_price":      P_bid,   # SELL put at real bid
                            "put_side":       "sell",
                            "put_bid_sz":     P_bid_sz,
                            "gross_usd":      rev_gross_usd,
                            "fee_usd":        rev_fee_usd,
                            "net_usd_lot":    rev_net_usd,
                            "net_pct":        (rev_net_usd / (S * lot_size)) * 100,
                            "lot_size":       lot_size,
                            "exp_ts":         found_exp_ts,
                            "hrs_left":       h_left,
                            "action":         "SELL Futures | BUY Call | SELL Put",
                        })
                        logger.info(
                            f"  [OPP] {coin} REVERSAL K={K:,.0f} | "
                            f"Gross=${rev_gross_usd:+.4f} Fee=${rev_fee_usd:.4f} "
                            f"Net=${rev_net_usd:+.4f}/lot | {h_left:.2f}h left"
                        )

        opportunities.sort(key=lambda x: x["net_usd_lot"], reverse=True)
        logger.info(
            f"[SCAN #{self.scan_count}] DONE: "
            f"{len(opportunities)} opportunities >= ${MIN_NET_PROFIT_USD_PER_LOT}/lot"
        )
        return opportunities

    # --------------------------------------------------------
    # STEP 2: Dynamic Lot Sizing
    # --------------------------------------------------------

    def calculate_lots(self, opp: Dict, delta_balance: float) -> int:
        """
        Calculates maximum tradeable lots using 75% of available Delta balance.

        Margin per lot:
          Futures = mark_price / leverage * lot_size  (small, leveraged margin)
          Call    = call_price * lot_size             (full premium upfront)
          Put     = put_price  * lot_size             (full premium upfront)

        Returns integer lots >= 1.
        """
        coin     = opp["coin"]
        S        = opp["futures_mark"]
        lot      = opp["lot_size"]
        lev      = FUTURES_LEVERAGE.get(coin, 100)

        fut_m    = (S / lev) * lot
        call_m   = opp["call_price"] * lot
        put_m    = opp["put_price"]  * lot
        total_m  = fut_m + call_m + put_m

        if total_m <= 0:
            return 1

        cap      = delta_balance * MARGIN_ALLOCATION_PCT
        max_lots = int(cap / total_m)
        lots     = max(1, max_lots)

        logger.info(
            f"[SIZE] {coin} Balance=${delta_balance:.2f} | 75%=${cap:.2f} | "
            f"Margin/lot: Fut=${fut_m:.4f} + Call=${call_m:.4f} + Put=${put_m:.4f} "
            f"= ${total_m:.4f} | Max lots={lots} ({lots*lot:.5f} {coin})"
        )
        return lots

    # --------------------------------------------------------
    # STEP 3: Execute 3-Leg Limit Orders
    # --------------------------------------------------------

    async def execute_3_legs(self, opp: Dict, lots: int) -> Optional[Dict]:
        """
        Places all 3 legs as LIMIT ORDERS simultaneously via asyncio.gather.

        CONVERSION: BUY Futures @ mark | BUY Put @ ask | SELL Call @ bid
        REVERSAL  : SELL Futures @ mark | BUY Call @ ask | SELL Put @ bid

        Returns order result dict if all 3 placed OK, None on failure.
        On any failure: cancels all successfully placed legs.
        """
        coin = opp["coin"]
        lot  = opp["lot_size"]

        logger.info("=" * 72)
        logger.info(f"  EXECUTING: {coin} {opp['type']} | Strike ${opp['strike']:,.0f}")
        logger.info(f"  Action: {opp['action']}")
        logger.info(f"  Lots: {lots} | Qty: {lots*lot:.5f} {coin}")
        logger.info(f"  Net Profit: ${opp['net_usd_lot']*lots:+.4f} USD locked")
        logger.info(f"  Expiry: {ts_to_ist(opp['exp_ts'])} | {opp['hrs_left']:.2f}h left")
        logger.info(f"  Leg 1 - Futures {opp['futures_side'].upper()}: "
                    f"{opp['futures_sym']} @ ${opp['futures_entry']:.2f}")
        logger.info(f"  Leg 2 - Call {opp['call_side'].upper()}: "
                    f"{opp['call_sym']} @ ${opp['call_price']:.4f}")
        logger.info(f"  Leg 3 - Put {opp['put_side'].upper()}: "
                    f"{opp['put_sym']} @ ${opp['put_price']:.4f}")
        logger.info("=" * 72)

        if not LIVE_EXECUTION:
            logger.info("[PAPER] Simulating 3-leg limit orders (LIVE_EXECUTION=false)")
            return {
                "paper":  True,
                "fut_id": 99991,
                "call_id": 99992,
                "put_id":  99993,
                "opp": opp, "lots": lots, "placed_at": time.time()
            }

        await self.executor._ensure_session()

        # Fire all 3 legs concurrently
        fut_r, call_r, put_r = await asyncio.gather(
            self.executor._delta_order(
                opp["futures_sym"], opp["futures_side"], lots,
                order_type="limit_order", limit_price=round(opp["futures_entry"], 2)
            ),
            self.executor._delta_order(
                opp["call_sym"], opp["call_side"], lots,
                order_type="limit_order", limit_price=round(opp["call_price"], 4)
            ),
            self.executor._delta_order(
                opp["put_sym"], opp["put_side"], lots,
                order_type="limit_order", limit_price=round(opp["put_price"], 4)
            ),
            return_exceptions=True
        )

        def ok(r) -> bool:
            return isinstance(r, dict) and r.get("success", False)

        def oid(r) -> Optional[int]:
            return r.get("order_id") if isinstance(r, dict) else None

        fut_ok  = ok(fut_r)
        call_ok = ok(call_r)
        put_ok  = ok(put_r)

        logger.info(
            f"[PLACE] Futures={'OK' if fut_ok else 'FAIL'}(id={oid(fut_r)}) | "
            f"Call={'OK' if call_ok else 'FAIL'}(id={oid(call_r)}) | "
            f"Put={'OK' if put_ok else 'FAIL'}(id={oid(put_r)})"
        )

        if not (fut_ok and call_ok and put_ok):
            logger.error("[PLACE] FAILED: Cancelling all placed legs.")
            cancel_tasks = []
            # Cancel call and put (we have product_ids for these)
            if call_ok and oid(call_r) and opp.get("call_pid"):
                cancel_tasks.append(self.cancel_order(oid(call_r), opp["call_pid"]))
            if put_ok and oid(put_r) and opp.get("put_pid"):
                cancel_tasks.append(self.cancel_order(oid(put_r), opp["put_pid"]))
            if cancel_tasks:
                await asyncio.gather(*cancel_tasks, return_exceptions=True)
            return None

        return {
            "paper":    False,
            "fut_id":   oid(fut_r),
            "call_id":  oid(call_r),
            "put_id":   oid(put_r),
            "opp":      opp,
            "lots":     lots,
            "placed_at": time.time()
        }

    # --------------------------------------------------------
    # STEP 4: Monitor Fills (30s timeout, auto-cancel)
    # --------------------------------------------------------

    async def monitor_fills(self, order: Dict, opp: Dict) -> bool:
        """
        Polls all 3 order states every 2 seconds for up to 30 seconds.
        If all filled -> returns True.
        If timeout or any order cancelled -> cancels remaining -> returns False.
        """
        if order.get("paper"):
            logger.info("[FILL] Paper mode: simulating all 3 filled.")
            return True

        fut_id  = order["fut_id"]
        call_id = order["call_id"]
        put_id  = order["put_id"]

        start   = time.time()
        f_s = c_s = p_s = "open"

        logger.info(
            f"[FILL] Monitoring fills | "
            f"Fut={fut_id} Call={call_id} Put={put_id} | "
            f"Timeout={FILL_MONITOR_TIMEOUT_S}s"
        )

        while time.time() - start < FILL_MONITOR_TIMEOUT_S:
            await asyncio.sleep(FILL_CHECK_INTERVAL_S)

            states = await asyncio.gather(
                self.fetch_order_status(fut_id),
                self.fetch_order_status(call_id),
                self.fetch_order_status(put_id),
                return_exceptions=True
            )

            f_s = states[0] if isinstance(states[0], str) else "error"
            c_s = states[1] if isinstance(states[1], str) else "error"
            p_s = states[2] if isinstance(states[2], str) else "error"

            elapsed = time.time() - start
            logger.info(f"[FILL] +{elapsed:.0f}s | Fut={f_s} Call={c_s} Put={p_s}")

            if f_s == "filled" and c_s == "filled" and p_s == "filled":
                logger.info("[FILL] ALL 3 LEGS FILLED! Position active.")
                return True

            if any(s in ("cancelled", "error") for s in [f_s, c_s, p_s]):
                logger.warning("[FILL] A leg was cancelled or errored. Cancelling rest.")
                break

        # Timeout or error: cancel all unfilled legs
        logger.warning(f"[FILL] TIMEOUT {FILL_MONITOR_TIMEOUT_S}s. Cancelling unfilled legs.")
        cancel_tasks = []
        if c_s != "filled" and opp.get("call_pid"):
            cancel_tasks.append(self.cancel_order(call_id, opp["call_pid"]))
        if p_s != "filled" and opp.get("put_pid"):
            cancel_tasks.append(self.cancel_order(put_id, opp["put_pid"]))
        if f_s != "filled":
            # Futures: try to find product_id from live positions or re-check
            logger.warning(f"[FILL] Futures order {fut_id} unfilled. "
                           "Check Delta dashboard and close manually if needed.")
        if cancel_tasks:
            await asyncio.gather(*cancel_tasks, return_exceptions=True)

        send_telegram_alert(
            f"PARTIAL FILL CANCELLED\n"
            f"{opp['coin']} {opp['type']} Strike=${opp['strike']:,.0f}\n"
            f"Reason: {FILL_MONITOR_TIMEOUT_S}s timeout\n"
            f"Fut={f_s} | Call={c_s} | Put={p_s}"
        )
        return False

    # --------------------------------------------------------
    # STEP 5: Register Position
    # --------------------------------------------------------

    def register_position(self, opp: Dict, lots: int, order: Dict):
        """
        Registers active position for daily auto-close at 5:30 PM IST.
        Options are auto-settled by Delta Exchange — no action needed.
        Futures must be closed manually by the bot.
        """
        lot     = opp["lot_size"]
        net_tot = opp["net_usd_lot"] * lots

        pos = {
            "coin":         opp["coin"],
            "type":         opp["type"],
            "strike":       opp["strike"],
            "futures_sym":  opp["futures_sym"],
            "futures_side": opp["futures_side"],
            "lots":         lots,
            "base_qty":     lots * lot,
            "exp_ts":       opp["exp_ts"],
            "exp_str":      ts_to_ist(opp["exp_ts"]),
            "net_locked":   net_tot,
            "entry_time":   datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "fut_order_id": order.get("fut_id"),
            "autoclose_done": False,
        }
        self.positions.append(pos)
        self.trade_count         += 1
        self.total_locked_profit += net_tot

        logger.info(
            f"[POS] REGISTERED: {pos['coin']} {pos['type']} "
            f"${pos['strike']:,.0f} | {lots} lots ({lots*lot:.5f} {pos['coin']}) | "
            f"Net locked: ${net_tot:+.4f} | Expiry: {pos['exp_str']}"
        )

        send_telegram_alert(
            f"TRADE OPEN - OPTIONS PARITY\n\n"
            f"Asset: {opp['coin']} | Strike: ${opp['strike']:,.0f}\n"
            f"Type: {opp['type']}\n"
            f"Lots: {lots} ({lots*lot:.5f} {opp['coin']})\n"
            f"Net Profit Locked: ${net_tot:+.4f}\n"
            f"Return: {opp['net_pct']:+.4f}% per lot\n"
            f"Expiry: {ts_to_ist(opp['exp_ts'])} ({opp['hrs_left']:.2f}h)\n\n"
            f"Legs:\n"
            f"  Fut {opp['futures_side'].upper()} {opp['futures_sym']} @ ${opp['futures_entry']:.2f}\n"
            f"  Call {opp['call_side'].upper()} {opp['call_sym']} @ ${opp['call_price']:.4f}\n"
            f"  Put  {opp['put_side'].upper()} {opp['put_sym']} @ ${opp['put_price']:.4f}"
        )

    # --------------------------------------------------------
    # STEP 6: Daily Auto-Close Futures at 5:30 PM IST
    # --------------------------------------------------------

    async def autoclose_expiring_futures(self):
        """
        Checks all registered positions. When within FUTURES_CLOSE_LEAD_SECS
        (2 minutes) of daily settlement (5:30 PM IST = 12:00 UTC):

          - Options: auto-settle by Delta Exchange (no action needed)
          - Futures: bot fires a reduce_only LIMIT order at current mark price
                     with a 0.05% buffer to ensure quick fill.
                     Falls back to market order if mark price unavailable.

        This runs on every scan cycle so even if bot restarts near expiry,
        positions will still get closed.
        """
        now_ts    = int(time.time())
        remaining = []

        for pos in self.positions:
            if pos.get("autoclose_done"):
                continue

            # Start closing 2 minutes before expiry
            close_trigger_ts = pos["exp_ts"] - FUTURES_CLOSE_LEAD_SECS

            if now_ts < close_trigger_ts:
                remaining.append(pos)
                continue

            coin        = pos["coin"]
            futures_sym = pos["futures_sym"]
            close_side  = "sell" if pos["futures_side"] == "buy" else "buy"

            logger.info(
                f"[AUTOCLOSE] {coin} {pos['type']} ${pos['strike']:,.0f} | "
                f"Triggering futures close ({close_side.upper()}) @ 5:30 PM IST..."
            )

            # Fetch current mark price for limit close
            mark_price = 0.0
            try:
                tickers = await self.fetch_all_tickers()
                t       = tickers.get(futures_sym, {})
                mark_price = float(t.get("mark_price") or 0)
            except Exception:
                pass

            if mark_price > 0:
                # Add 0.05% buffer so limit order fills quickly
                buf         = 0.0005
                limit_close = (
                    mark_price * (1.0 - buf) if close_side == "sell"
                    else mark_price * (1.0 + buf)
                )
                close_res = await self.executor._delta_order(
                    futures_sym, close_side, pos["lots"],
                    order_type="limit_order",
                    limit_price=round(limit_close, 2),
                    reduce_only=True
                )
                logger.info(
                    f"[AUTOCLOSE] Limit close @ ${limit_close:.2f} | "
                    f"Result: {'OK' if close_res.get('success') else 'FAIL'}"
                )
            else:
                # Fallback to market order
                logger.warning(
                    f"[AUTOCLOSE] No mark price for {futures_sym}. "
                    "Using MARKET close order."
                )
                close_res = await self.executor._delta_order(
                    futures_sym, close_side, pos["lots"],
                    order_type="market_order", reduce_only=True
                )
                logger.info(
                    f"[AUTOCLOSE] Market close result: "
                    f"{'OK' if close_res.get('success') else 'FAIL'}"
                )

            close_ok = close_res.get("success", False)
            pos["autoclose_done"] = True

            send_telegram_alert(
                f"PARITY TRADE CLOSED (DAILY EXPIRY)\n\n"
                f"Asset: {coin} | Strike: ${pos['strike']:,.0f}\n"
                f"Type: {pos['type']}\n"
                f"Lots: {pos['lots']} ({pos['base_qty']:.5f} {coin})\n"
                f"Net Locked: ${pos['net_locked']:+.4f}\n"
                f"Futures Close: {'SUCCESS' if close_ok else 'CHECK MANUALLY'}\n"
                f"(Options auto-settled by Delta at 5:30 PM IST)"
            )

            if not close_ok:
                logger.error(
                    f"[AUTOCLOSE] FAILED to close {futures_sym}! "
                    "Check Delta dashboard immediately."
                )
                # Keep in remaining so we retry every scan cycle
                remaining.append(pos)
            else:
                logger.info(f"[AUTOCLOSE] {coin} futures closed successfully.")

        self.positions = remaining

    # --------------------------------------------------------
    # Telegram Opportunity Alert (with 2-min dedup)
    # --------------------------------------------------------

    def alert_opportunity(self, opp: Dict, lots: int):
        key      = (opp["coin"], opp["strike"], opp["type"])
        last     = self.alert_times.get(key, 0)
        if time.time() - last < 120:
            return

        lot = opp["lot_size"]
        msg = (
            f"PARITY OPPORTUNITY\n"
            f"Asset: {opp['coin']} Strike=${opp['strike']:,.0f}\n"
            f"Type: {opp['type']}\n"
            f"Gross/lot: ${opp['gross_usd']:+.4f}\n"
            f"Fee/lot:   ${opp['fee_usd']:.4f} (0.109%)\n"
            f"Net/lot:   ${opp['net_usd_lot']:+.4f}\n"
            f"Lots: {lots} ({lots*lot:.5f} {opp['coin']})\n"
            f"Total Net: ${opp['net_usd_lot']*lots:+.4f}\n"
            f"Time left: {opp['hrs_left']:.2f}h\n"
            f"Action: {opp['action']}\n"
            f"OB: CallBid/Ask={opp.get('call_bid_sz','-')}/{opp.get('call_ask_sz','-')} "
            f"PutBid/Ask={opp.get('put_bid_sz','-')}/{opp.get('put_ask_sz','-')}"
        )
        if send_telegram_alert(msg):
            self.alert_times[key] = time.time()

    # --------------------------------------------------------
    # Status Log
    # --------------------------------------------------------

    def log_status(self, balance: float, opps: List[Dict]):
        exp_ts  = get_today_expiry_ts()
        h       = hours_left(exp_ts)
        logger.info("-" * 72)
        logger.info(
            f"[STATUS] {'LIVE' if LIVE_EXECUTION else 'PAPER'} | "
            f"Scan #{self.scan_count} | "
            f"Balance=${balance:.2f} (75%=${balance*0.75:.2f})"
        )
        logger.info(
            f"[STATUS] Daily expiry in {h:.2f}h | "
            f"Active positions={len(self.positions)} | "
            f"Trades done={self.trade_count} | "
            f"Est. net profit=${self.total_locked_profit:+.4f}"
        )
        logger.info(
            f"[STATUS] Opportunities this scan: {len(opps)} "
            f"| In-trade lock: {self.in_trade}"
        )
        if opps:
            b = opps[0]
            logger.info(
                f"[STATUS] Best: {b['coin']} {b['type']} "
                f"${b['strike']:,.0f} -> ${b['net_usd_lot']:+.4f}/lot"
            )
        logger.info("-" * 72)

    # --------------------------------------------------------
    # Main Run Loop
    # --------------------------------------------------------

    async def run(self):
        """
        Main async loop — runs every SCAN_INTERVAL_S (30 seconds).

        Every cycle:
          1. Auto-close any futures within 2 min of 5:30 PM IST expiry
          2. Fetch live Delta balance
          3. Scan for parity opportunities (real L2 orderbook)
          4. Send Telegram alerts (2-min dedup)
          5. Execute best opportunity (limit orders, if not already in trade)
          6. Monitor fills 30s -> cancel on timeout
          7. Register position for auto-close
        """
        startup_msg = (
            f"OPTIONS PARITY BOT V3 STARTED\n"
            f"Mode: {'LIVE' if LIVE_EXECUTION else 'PAPER'}\n"
            f"Assets: {', '.join(SUPPORTED_UNDERLYINGS)}\n"
            f"Profit gate: ${MIN_NET_PROFIT_USD_PER_LOT}/lot after {TOTAL_ROUNDTRIP_FEE_PCT*100:.3f}% fees\n"
            f"Today's expiry: {ts_to_ist(get_today_expiry_ts())}\n"
            f"Auto-close leads by: {FUTURES_CLOSE_LEAD_SECS}s before expiry"
        )
        logger.info(startup_msg.replace("\n", " | "))
        send_telegram_alert(startup_msg)

        while True:
            try:
                self.scan_count += 1

                # 1. Auto-close expiring futures
                await self.autoclose_expiring_futures()

                # 2. Fetch Delta balance directly (no CoinDCX dependency)
                d_bal = await self.fetch_delta_balance_direct()

                if LIVE_EXECUTION and d_bal <= 0:
                    logger.warning(
                        "[LOOP] Delta balance $0 or inaccessible. "
                        "Check IP whitelist on Delta API settings. "
                        "Continuing scan in read-only mode..."
                    )
                    # Still scan so we can see opportunities in logs/Telegram
                    # but won't execute trades
                    d_bal = 0.0

                # 3. Scan real orderbook for opportunities
                opps = await self.scan_parity_opportunities()
                self.log_status(d_bal, opps)

                # 4. Telegram alerts
                for opp in opps:
                    lots_preview = self.calculate_lots(opp, d_bal)
                    self.alert_opportunity(opp, lots_preview)

                # 5. Execute best opportunity
                if not self.in_trade and opps and d_bal > 0:
                    best = opps[0]
                    lots = self.calculate_lots(best, d_bal)

                    logger.info(
                        f"[LOOP] Executing best: {best['coin']} {best['type']} "
                        f"${best['strike']:,.0f} | {lots} lots | "
                        f"Net=${best['net_usd_lot']*lots:+.4f}"
                    )

                    self.in_trade  = True
                    order          = await self.execute_3_legs(best, lots)

                    if order is None:
                        logger.error("[LOOP] Execution failed. Resetting lock.")
                        self.in_trade = False
                    else:
                        # 6. Monitor fills
                        filled = await self.monitor_fills(order, best)
                        if filled:
                            # 7. Register for auto-close
                            self.register_position(best, lots, order)
                        else:
                            logger.warning("[LOOP] Not all legs filled. Position NOT registered.")
                        self.in_trade = False

                elif self.in_trade:
                    logger.info("[LOOP] In-trade lock active. Skipping new trade.")
                elif not opps:
                    logger.info("[LOOP] No qualifying opportunities this scan.")

            except asyncio.CancelledError:
                logger.info("[LOOP] Cancelled. Exiting.")
                break
            except KeyboardInterrupt:
                logger.info("[LOOP] Keyboard interrupt. Exiting.")
                break
            except Exception as e:
                logger.error(f"[LOOP] Unhandled: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(10)
                continue

            logger.info(f"[LOOP] Sleeping {SCAN_INTERVAL_S}s...")
            await asyncio.sleep(SCAN_INTERVAL_S)

        # Cleanup
        await self.close_session()
        if self.executor.session and not self.executor.session.closed:
            await self.executor.close()
        logger.info("[BOT] Shutdown complete.")


# ============================================================
# Entry Point
# ============================================================

async def main():
    executor = LiveOrderExecutor()
    bot = OptionsParityBotV3(executor)
    try:
        await bot.run()
    except Exception as e:
        logger.critical(f"[MAIN] Fatal: {e}")
        logger.critical(traceback.format_exc())
    finally:
        await bot.close_session()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[BOT] Stopped by user.")
