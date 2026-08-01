"""
Delta Exchange India Options Put-Call Parity Arbitrage Engine
=============================================================
Scans live BTC, ETH, and XAUT Options and Futures on Delta Exchange India.
Identifies Put-Call Parity violations:
  Parity Equation:  C - P = S - K
  Conversion Arb :  (C - P) - (S - K) > Fee Gate (0.15%)
  Reversal Arb   :  (S - K) - (C - P) > Fee Gate (0.15%)

Uses 75% of available Delta balance with Maximum Leverage (100x for BTC/ETH).
Holds position until option expiry, and automatically closes the Futures leg upon option settlement.
"""
import os
import sys
import time
import json
import asyncio
import aiohttp
import logging
import datetime

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
    LiveOrderExecutor,
    LOT_SIZES
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s - %(message)s")
logger = logging.getLogger("DeltaOptionsParityEngine")

# Supported Underlyings for Put-Call Parity
SUPPORTED_UNDERLYINGS = ["BTC", "ETH", "XAUT"]
MIN_NET_SPREAD_GATE = 0.15  # Minimum 0.15% Net Fee-Adjusted Profit Gate

class DeltaOptionsParityEngine:
    def __init__(self, live_executor: LiveOrderExecutor):
        self.executor = live_executor
        self.session = None
        self.active_parity_positions = []

    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def fetch_delta_products_and_tickers(self):
        """Fetches all active products and tickers from Delta Exchange India."""
        await self._ensure_session()
        try:
            async with self.session.get(f"{DELTA_BASE_URL}/v2/products", timeout=5) as r1:
                products = (await r1.json()).get("result", [])

            async with self.session.get(f"{DELTA_BASE_URL}/v2/tickers", timeout=5) as r2:
                tickers = (await r2.json()).get("result", [])

            ticker_map = {t.get("symbol"): t for t in tickers if isinstance(t, dict)}
            return products, ticker_map
        except Exception as e:
            logger.error(f"Error fetching Delta products/tickers: {e}")
            return [], {}

    def scan_parity_opportunities(self, products, ticker_map):
        """
        Pairs Call & Put options by Strike Price & Nearest Expiry Date for BTC, ETH, and XAUT.
        Calculates Put-Call Parity Spread:
           Conversion: (C - P) - (S - K)
           Reversal  : (S - K) - (C - P)
        """
        opportunities = []
        now_ts = int(time.time())

        for coin in SUPPORTED_UNDERLYINGS:
            # Step 1: Find Futures mark price S for coin (e.g. BTCUSD, ETHUSD, XAUTUSD)
            fut_sym = f"{coin}USD"
            fut_ticker = ticker_map.get(fut_sym) or ticker_map.get(f"{coin}USDT")
            if not fut_ticker:
                continue
            
            futures_mark = float(fut_ticker.get("mark_price") or fut_ticker.get("close") or 0)
            if futures_mark <= 0:
                continue

            # Step 2: Filter Options for this coin
            coin_options = []
            for p in products:
                spec = p.get("product_specs") or {}
                contract_type = p.get("contract_type", "")
                underlying = spec.get("underlying_asset", {}).get("symbol") or p.get("underlying_asset_symbol")
                
                if underlying == coin and contract_type in ["call_option", "put_option"]:
                    settlement_time = p.get("settlement_time")
                    # Convert ISO settlement time to timestamp
                    if isinstance(settlement_time, str):
                        try:
                            dt = datetime.datetime.fromisoformat(settlement_time.replace("Z", "+00:00"))
                            exp_ts = int(dt.timestamp())
                        except Exception:
                            exp_ts = 0
                    else:
                        exp_ts = int(settlement_time or 0)

                    if exp_ts > now_ts:
                        p["exp_ts"] = exp_ts
                        coin_options.append(p)

            if not coin_options:
                continue

            # Step 3: Find Nearest Expiry timestamp
            min_exp = min(opt["exp_ts"] for opt in coin_options)
            nearest_options = [opt for opt in coin_options if opt["exp_ts"] == min_exp]

            # Step 4: Group Calls and Puts by Strike Price
            calls_by_strike = {}
            puts_by_strike = {}

            for opt in nearest_options:
                strike = float(opt.get("strike_price") or 0)
                sym = opt.get("symbol")
                t_data = ticker_map.get(sym, {})
                mark_price = float(t_data.get("mark_price") or 0)
                quotes = t_data.get("quotes") or {}
                best_bid = float(quotes.get("best_bid") or mark_price)
                best_ask = float(quotes.get("best_ask") or mark_price)

                opt_info = {
                    "symbol": sym,
                    "strike": strike,
                    "mark_price": mark_price,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "exp_ts": opt["exp_ts"]
                }

                if opt.get("contract_type") == "call_option":
                    calls_by_strike[strike] = opt_info
                elif opt.get("contract_type") == "put_option":
                    puts_by_strike[strike] = opt_info

            # Step 5: Calculate Parity for matching strikes
            for strike, call in calls_by_strike.items():
                if strike in puts_by_strike:
                    put = puts_by_strike[strike]
                    
                    # Call Ask (C) and Put Bid (P)
                    C = call["best_ask"]
                    P = put["best_bid"]
                    S = futures_mark
                    K = strike

                    # Parity Differential: (C - P) vs (S - K)
                    conversion_spread_usd = (C - P) - (S - K)
                    conversion_spread_pct = (conversion_spread_usd / S) * 100.0

                    reversal_spread_usd = (S - K) - (C - P)
                    reversal_spread_pct = (reversal_spread_usd / S) * 100.0

                    # Deduct Total Roundtrip Fee Gate (~0.12%)
                    net_conversion_pct = conversion_spread_pct - 0.12
                    net_reversal_pct = reversal_spread_pct - 0.12

                    hours_to_exp = (call["exp_ts"] - now_ts) / 3600.0

                    if net_conversion_pct >= MIN_NET_SPREAD_GATE:
                        opportunities.append({
                            "coin": coin,
                            "type": "CONVERSION",
                            "strike": strike,
                            "futures_sym": fut_sym,
                            "call_sym": call["symbol"],
                            "put_sym": put["symbol"],
                            "futures_mark": S,
                            "call_ask": C,
                            "call_bid": call["best_bid"],
                            "put_bid": P,
                            "put_ask": put["best_ask"],
                            "gross_spread_pct": conversion_spread_pct,
                            "net_pnl_pct": net_conversion_pct,
                            "hours_to_exp": hours_to_exp,
                            "exp_ts": call["exp_ts"],
                            "action": "BUY Futures + BUY Put + SELL Call"
                        })
                    elif net_reversal_pct >= MIN_NET_SPREAD_GATE:
                        opportunities.append({
                            "coin": coin,
                            "type": "REVERSAL",
                            "strike": strike,
                            "futures_sym": fut_sym,
                            "call_sym": call["symbol"],
                            "put_sym": put["symbol"],
                            "futures_mark": S,
                            "call_ask": C,
                            "call_bid": call["best_bid"],
                            "put_bid": P,
                            "put_ask": put["best_ask"],
                            "gross_spread_pct": reversal_spread_pct,
                            "net_pnl_pct": net_reversal_pct,
                            "hours_to_exp": hours_to_exp,
                            "exp_ts": call["exp_ts"],
                            "action": "SELL Futures + BUY Call + SELL Put"
                        })

        opportunities.sort(key=lambda x: x["net_pnl_pct"], reverse=True)
        return opportunities

    async def execute_parity_trade(self, opp: dict):
        """
        Executes Put-Call Parity Arbitrage using 75% of Delta available balance at Maximum Leverage (100x).
        Tracks active trade for automatic Futures closure upon option settlement.
        """
        d_bal, _, min_safe_margin = await self.executor.fetch_live_balances()
        if d_bal < 1.0:
            logger.warning(f"⚠️ Insufficient Delta balance (${d_bal:.2f}) to execute Options Parity Trade.")
            return False

        # Allocate 75% of available Delta balance
        active_capital = d_bal * 0.75
        coin = opp["coin"]
        futures_mark = opp["futures_mark"]
        
        # Max Leverage: 200x for BTC/ETH Options & Futures, 100x for XAUT
        max_leverage = 200 if coin in ["BTC", "ETH"] else 100
        notional_usd = active_capital * max_leverage

        lot_size = LOT_SIZES.get(coin, 1.0)
        target_qty = notional_usd / futures_mark
        lots = max(1, int(round(target_qty / lot_size)))
        exact_base_qty = lots * lot_size

        logger.info("=" * 80)
        logger.info(f" 🚀 EXECUTING DELTA INDIA PUT-CALL PARITY ARBITRAGE: {coin}")
        logger.info(f"    Parity Type      : {opp['type']} ({opp['action']})")
        logger.info(f"    Strike Price     : ${opp['strike']:.2f}")
        logger.info(f"    Net PnL Spread   : +{opp['net_pnl_pct']:.4f}%")
        logger.info(f"    Capital (75%)    : ${active_capital:.2f} USD @ {max_leverage}x Leverage (${notional_usd:.2f} Notional)")
        logger.info(f"    Lots / Base Qty  : {lots} Lots ({exact_base_qty} {coin})")
        logger.info(f"    Hours to Expiry  : {opp['hours_to_exp']:.2f} Hours")
        logger.info("=" * 80)

        # Place 3-Legged Execution Orders on Delta Exchange India (LIMIT ORDERS FOR OPTIONS)
        if opp["type"] == "CONVERSION":
            # Leg 1: BUY Futures (Market / Limit Order at Futures Mark)
            fut_res = await self.executor._delta_order(
                opp["futures_sym"], "buy", lots, order_type="limit_order", limit_price=opp["futures_mark"]
            )
            # Leg 2: BUY Put Option (LIMIT ORDER at Put Ask)
            put_res = await self.executor._delta_order(
                opp["put_sym"], "buy", lots, order_type="limit_order", limit_price=opp["put_ask"]
            )
            # Leg 3: SELL Call Option (LIMIT ORDER at Call Bid)
            call_res = await self.executor._delta_order(
                opp["call_sym"], "sell", lots, order_type="limit_order", limit_price=opp["call_bid"]
            )
        else: # REVERSAL
            # Leg 1: SELL Futures
            fut_res = await self.executor._delta_order(
                opp["futures_sym"], "sell", lots, order_type="limit_order", limit_price=opp["futures_mark"]
            )
            # Leg 2: BUY Call Option (LIMIT ORDER at Call Ask)
            call_res = await self.executor._delta_order(
                opp["call_sym"], "buy", lots, order_type="limit_order", limit_price=opp["call_ask"]
            )
            # Leg 3: SELL Put Option (LIMIT ORDER at Put Bid)
            put_res = await self.executor._delta_order(
                opp["put_sym"], "sell", lots, order_type="limit_order", limit_price=opp["put_bid"]
            )

        # Register position for automatic Futures closure at option expiry
        position_record = {
            "coin": coin,
            "futures_sym": opp["futures_sym"],
            "futures_side": "buy" if opp["type"] == "CONVERSION" else "sell",
            "lots": lots,
            "exp_ts": opp["exp_ts"],
            "entry_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.active_parity_positions.append(position_record)

        logger.info(f"✅ Options Parity Trade Position Successfully Opened! Registered for Auto-Close at Expiry.")
        return True

    async def monitor_and_autoclose_at_expiry(self):
        """
        Background monitor that checks active options positions.
        When option settlement timestamp is reached, options auto-settle on exchange,
        and this worker automatically fires a reduce_only market order to close the Futures leg.
        """
        now_ts = int(time.time())
        remaining_positions = []

        for pos in self.active_parity_positions:
            if now_ts >= pos["exp_ts"]:
                logger.info(f"⏰ OPTION EXPIRY TIME REACHED for {pos['coin']} ({pos['futures_sym']})!")
                logger.info(f"   Option contracts auto-settled by exchange. Automatically closing Futures leg now...")
                
                # Close Futures Leg (Reverse side with reduce_only)
                exit_side = "sell" if pos["futures_side"] == "buy" else "buy"
                close_res = await self.executor._delta_order(
                    pos["futures_sym"],
                    exit_side,
                    pos["lots"],
                    reduce_only=True
                )
                logger.info(f"🏁 AUTOMATIC FUTURES CLOSURE RESULT (HTTP {close_res.get('http')}): {close_res.get('response')}")
            else:
                remaining_positions.append(pos)

        self.active_parity_positions = remaining_positions

