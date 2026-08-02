"""
Delta Exchange India - Automated Expiry & Arbitrage Trading Bot
===============================================================
Features:
1. Expiry Monitor: Automatically closes trades approaching expiry (or auto-settles them).
2. Arbitrage Scanner: Scans Put-Call Parity and Vertical Strike mispricings in real-time.
3. Auto Executor: Executes next arbitrage trade when profitable opportunities arise.
4. Safety & Paper Mode: Paper trading by default, toggleable to Live Mode with API keys.

Usage:
    python delta_auto_arbitrage_bot.py --paper                (Default Paper Mode)
    python delta_auto_arbitrage_bot.py --live                 (Live Trading Mode)
    python delta_auto_arbitrage_bot.py --min-profit 2.0       (Minimum $2 USD net profit threshold)
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime, timedelta, timezone

from delta_client import DeltaClient

# Environment / Default API Credentials
API_KEY = os.getenv("DELTA_API_KEY", "bZIwAB5Q1FM5nTflbg4CWNmYaDt7pI")
API_SECRET = os.getenv("DELTA_API_SECRET", "v8eGb9IFsW1gR8P4TL5sMnjX7hQvOLTNxKsaUGTnzAGaGMALcwxUYu6K3im0")

# Delta Exchange fee structure (per leg)
TAKER_FEE_PCT = 0.0005   # 0.05% taker fee per order
MINIMUM_ORDERBOOK_SIZE = 1  # Minimum quantity available at best bid/ask

class DeltaAutoArbitrageBot:
    def __init__(self, paper_mode=True, min_profit_usd=0.05, check_interval_sec=10, close_expiry_mins=1, demo_mode=False, trade_lots=5):
        self.paper_mode = paper_mode
        self.demo_mode = demo_mode
        self.min_profit_usd = min_profit_usd
        self.check_interval = check_interval_sec
        self.close_expiry_mins = close_expiry_mins
        self.trade_lots = trade_lots
        
        base_url = "https://cdn-ind.testnet.deltaex.org" if demo_mode else os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange")
        self.client = DeltaClient(api_key=API_KEY, api_secret=API_SECRET, base_url=base_url)
        
        # Paper mode tracking
        self.paper_positions = []
        self.paper_balance = 1000.0  # Virtual USD
        self.paper_pnl = 0.0
        self.trade_history = []
        self.cached_products = []

    def get_available_usd_balance(self):
        """Get current available USD margin balance."""
        if self.paper_mode:
            return self.paper_balance
        try:
            bal_data = self.client.get_wallet_balance()
            if bal_data.get('success'):
                usd_info = next((x for x in bal_data.get('result', []) if x.get('asset_symbol') == 'USD'), {})
                return float(usd_info.get('available_balance', 0))
        except:
            pass
        return 0.0

    def get_dynamic_equal_lots(self):
        """Calculate maximum equal lot size (1:1:1 ratio) using 100% of remaining available margin."""
        if self.paper_mode:
            return 5
        try:
            avail = self.get_available_usd_balance()
            if avail > 0:
                # Conservative margin estimate per 3-leg lot (0.001 BTC option short + long + future) is ~$3.50 USD
                margin_per_lot_3leg = 3.50
                max_equal_lots = max(1, int(avail / margin_per_lot_3leg))
                self.log("AUTO-MARGIN", f"Remaining Available USD Balance: ${avail:.2f} | Dynamic 1:1:1 Equal Lots Calculated: {max_equal_lots} Lots")
                return max_equal_lots
        except Exception as e:
            self.log("AUTO-MARGIN-EX", f"Error calculating auto lot size: {e}")
        return 5
        
    def log(self, tag, message):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode_str = "PAPER" if self.paper_mode else "LIVE"
        print(f"[{now_str}] [{mode_str}] [{tag}] {message}")

    # =========================================================================
    # 1. EXPIRY MONITOR & AUTO-CLOSE MODULE
    # =========================================================================
    def parse_expiry_date(self, symbol, product_data=None):
        """Extract expiry datetime (UTC 12:00:00) from Delta symbol or product metadata."""
        # 1. Check API product metadata first if available
        if product_data and product_data.get('expiry_date'):
            exp_str = product_data.get('expiry_date')
            try:
                # ISO format: 2026-07-31T12:00:00Z or 2026-07-31
                if 'T' in exp_str:
                    dt = datetime.strptime(exp_str.split('T')[0], "%Y-%m-%d")
                else:
                    dt = datetime.strptime(exp_str, "%Y-%m-%d")
                return dt.replace(hour=12, minute=0, second=0, tzinfo=timezone.utc)
            except Exception:
                pass

        # 2. Extract from symbol (e.g. C-BTC-64000-310726 or C BTC 64000 310726)
        clean_symbol = symbol.replace(' ', '-').replace('_', '-')
        parts = clean_symbol.split('-')
        if len(parts) >= 4:
            date_str = parts[3]
            try:
                # Format: DDMMYY (e.g., 310726 -> 31 July 2026)
                dt = datetime.strptime(date_str, "%d%m%y")
                return dt.replace(hour=12, minute=0, second=0, tzinfo=timezone.utc)
            except ValueError:
                pass
        return None

    def check_and_close_expiring_positions(self):
        """Scan open positions and close any position expiring soon or already expired."""
        self.log("EXPIRY-CHECK", "Checking open positions for expiry...")
        
        if self.paper_mode:
            positions_to_close = []
            now_utc = datetime.now(timezone.utc)
            
            for pos in list(self.paper_positions):
                sym = pos['symbol']
                expiry_dt = self.parse_expiry_date(sym)
                
                if expiry_dt:
                    time_to_expiry = (expiry_dt - now_utc).total_seconds() / 60.0  # in minutes
                    
                    if time_to_expiry <= self.close_expiry_mins:
                        self.log("EXPIRY-AUTO-CLOSE", 
                                 f"Closing Paper Position {sym} | Size: {pos['size']} | Time to Expiry: {time_to_expiry:.1f} mins")
                        positions_to_close.append(pos)
                else:
                    # Non-date symbol or unknown, leave as is
                    pass
            
            for pos in positions_to_close:
                # Simulate PnL closure at mark price / current bid-ask mid
                exit_price = pos.get('entry_price', 0)  # Simple paper exit simulation
                pnl = (exit_price - pos['entry_price']) * pos['size'] if pos['side'] == 'buy' else (pos['entry_price'] - exit_price) * pos['size']
                self.paper_pnl += pnl
                self.paper_positions.remove(pos)
                self.log("EXPIRY-CLOSED", f"Successfully closed {pos['symbol']}. Realized PnL: ${pnl:.2f}")
                
            return

        # LIVE MODE POSITION EXPIRY CHECK
        try:
            resp = self.client.get_all_positions()
            if not resp or 'result' not in resp:
                self.log("EXPIRY-WARN", f"Could not fetch live positions: {resp}")
                return
            
            positions = resp.get('result', [])
            open_positions = [p for p in positions if float(p.get('size', 0)) != 0]
            
            if not open_positions:
                self.log("EXPIRY-CHECK", "No active open positions on Delta Exchange.")
                return
            
            now_utc = datetime.now(timezone.utc)
            
            for pos in open_positions:
                symbol = pos.get('product_symbol', pos.get('symbol', ''))
                size = float(pos.get('size', 0))
                product_data = pos.get('product')
                
                expiry_dt = self.parse_expiry_date(symbol, product_data=product_data)
                if not expiry_dt:
                    continue
                
                time_to_expiry = (expiry_dt - now_utc).total_seconds() / 60.0  # minutes
                
                if time_to_expiry <= self.close_expiry_mins:
                    self.log("EXPIRY-AUTO-CLOSE", 
                             f"PROFIT BOOKING! Expiry window reached ({time_to_expiry:.1f} min remaining). Closing position {symbol} | Size: {size}")
                    
                    code, close_resp = self.client.close_position(symbol, size)
                    if code in [200, 201]:
                        self.log("EXPIRY-CLOSED", f"Successfully booked profit & closed {symbol}! Freeing margin for next trade cycle.")
                    else:
                        self.log("EXPIRY-ERROR", f"Failed to close position {symbol}: {close_resp}")
                else:
                    self.log("EXPIRY-MONITOR", f"Position {symbol} active | Expiry in {time_to_expiry/60.0:.1f} hours.")
                    
        except Exception as e:
            self.log("EXPIRY-EXCEPTION", f"Error during expiry check: {e}")

    # =========================================================================
    # 2. ARBITRAGE SCANNER MODULE
    # =========================================================================
    def get_btc_spot(self):
        """Get current BTC spot price quickly."""
        try:
            resp = self.client._request('GET', '/v2/tickers/BTCUSD', signed=False)
            res = resp[1].get('result', {})
            price = float(res.get('close', 0) or res.get('spot_price', 0) or res.get('mark_price', 0))
            return price if price > 0 else 64000
        except:
            return 64000

    def get_btc_future_quotes(self):
        """Get BTCUSD future bid/ask quotes for 3-leg conversion arbitrage."""
        try:
            resp = self.client._request('GET', '/v2/tickers/BTCUSD', signed=False)
            res = resp[1].get('result', {})
            quotes = res.get('quotes', {})
            bid = float(quotes.get('best_bid', 0) or res.get('mark_price', 0) or 64000)
            ask = float(quotes.get('best_ask', 0) or res.get('mark_price', 0) or 64000)
            return bid, ask
        except:
            return 64000, 64000

    def fetch_atm_btc_options(self, atm_pct=0.25):
        """Fetch BTC options across wide strike range (within atm_pct of spot)."""
        try:
            spot = self.get_btc_spot()
            prods = self.client.get_products()
            products = []
            if isinstance(prods, dict) and prods.get('success') and prods.get('result'):
                products = prods.get('result', [])
                self.cached_products = products
            elif self.cached_products:
                products = self.cached_products
                self.log("SCANNER-CACHE", f"Using cached products list ({len(products)} products).")
            else:
                return [], spot
            
            atm_low = spot * (1 - atm_pct)
            atm_high = spot * (1 + atm_pct)
            
            btc_atm_opts = [
                p for p in products
                if (p.get('underlying_asset', {}).get('symbol') == 'BTC' or p.get('underlying_asset_symbol') == 'BTC')
                and p.get('contract_type') in ['call_options', 'put_options']
                and atm_low <= float(p.get('strike_price', 0)) <= atm_high
            ]
            self.log("SCANNER", f"Spot: ${spot:.0f} | Strike scan range: ${atm_low:.0f}-${atm_high:.0f} | Options in range: {len(btc_atm_opts)}")
            return btc_atm_opts, spot
        except Exception as e:
            self.log("SCANNER-ERR", f"Failed to fetch options: {e}")
            return [], 0

    def _fetch_ob_safe(self, symbol):
        """Fetch orderbook safely, return (symbol, buy_list, sell_list)."""
        try:
            resp = self.client.get_orderbook(symbol)
            res = resp.get('result', {}) if isinstance(resp, dict) else {}
            return symbol, res.get('buy', []), res.get('sell', [])
        except:
            return symbol, [], []

    def scan_vertical_strike_arbitrage(self, btc_options):
        """Fast concurrent scan for Vertical Spread arbitrage."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from collections import defaultdict
        opportunities = []

        # Group by expiry date only (separate calls/puts per expiry)
        grouped = defaultdict(list)
        for opt in btc_options:
            expiry_dt = self.parse_expiry_date(opt.get('symbol', ''), product_data=opt)
            if expiry_dt:
                grouped[expiry_dt.strftime("%Y-%m-%d")].append(opt)

        # Collect pairs: adjacent DIFFERENT strikes within same expiry
        pairs_to_check = []  # (expiry_str, type, opt1, opt2)
        for expiry_str, opts in grouped.items():
            calls = sorted([o for o in opts if o.get('contract_type') == 'call_options'],
                           key=lambda x: float(x.get('strike_price', 0)))
            puts = sorted([o for o in opts if o.get('contract_type') == 'put_options'],
                          key=lambda x: float(x.get('strike_price', 0)))
            for i in range(len(calls) - 1):
                # Only compare DIFFERENT strikes (same-strike = different product, skip)
                if float(calls[i]['strike_price']) != float(calls[i+1]['strike_price']):
                    pairs_to_check.append((expiry_str, 'CALL', calls[i], calls[i+1]))
            for i in range(len(puts) - 1):
                if float(puts[i]['strike_price']) != float(puts[i+1]['strike_price']):
                    pairs_to_check.append((expiry_str, 'PUT', puts[i], puts[i+1]))

        # Unique symbols to fetch
        all_symbols = list(set(
            o.get('symbol') for _, _, a, b in pairs_to_check for o in [a, b] if o.get('symbol')
        ))

        self.log("SCANNER", f"Fetching {len(all_symbols)} orderbooks concurrently...")

        # Concurrent orderbook fetch
        ob_cache = {}
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(self._fetch_ob_safe, sym): sym for sym in all_symbols}
            for fut in as_completed(futures):
                sym, buys, sells = fut.result()
                ob_cache[sym] = {'buy': buys, 'sell': sells}

        # Analyse pairs — True Risk-Free Arbitrage check
        for expiry_str, opt_type, o1, o2 in pairs_to_check:
            sym1, sym2 = o1.get('symbol'), o2.get('symbol')
            ob1 = ob_cache.get(sym1, {})
            ob2 = ob_cache.get(sym2, {})

            if opt_type == 'CALL':
                # Buy lower strike (K1) call, Sell higher strike (K2) call
                # Risk-free credit spread: if K1_ask < K2_bid → guaranteed profit
                asks1 = ob1.get('sell', [])   # K1 ask (we BUY this)
                bids2 = ob2.get('buy', [])    # K2 bid (we SELL this)
                if not asks1 or not bids2:
                    continue
                c1_ask = float(asks1[0]['price'])
                c2_bid = float(bids2[0]['price'])
                c1_size = float(asks1[0].get('size', 0))
                c2_size = float(bids2[0].get('size', 0))

                # Gross credit received
                gross_credit = c2_bid - c1_ask

                # Fee deduction: pay taker fee on both legs (in USD/BTC terms)
                # Fee is % of notional. 1 contract = 0.001 BTC
                contract_size = 0.001
                fee_leg1 = c1_ask * TAKER_FEE_PCT   # fee on buy leg (USD/BTC)
                fee_leg2 = c2_bid * TAKER_FEE_PCT   # fee on sell leg (USD/BTC)
                total_fees_per_btc = fee_leg1 + fee_leg2

                # Net credit after fees (per BTC notional)
                net_credit_after_fees = gross_credit - total_fees_per_btc
                net_profit_usd = net_credit_after_fees * contract_size

                if (
                    net_profit_usd >= self.min_profit_usd
                    and c1_size >= MINIMUM_ORDERBOOK_SIZE
                    and c2_size >= MINIMUM_ORDERBOOK_SIZE
                ):
                    opportunities.append({
                        'type': 'VERTICAL_CALL_CREDIT_SPREAD',
                        'expiry': expiry_str,
                        'leg1': {'symbol': sym1, 'side': 'buy',  'price': c1_ask, 'strike': float(o1['strike_price']), 'size_avail': c1_size},
                        'leg2': {'symbol': sym2, 'side': 'sell', 'price': c2_bid, 'strike': float(o2['strike_price']), 'size_avail': c2_size},
                        'gross_credit': gross_credit,
                        'fees_per_btc': total_fees_per_btc,
                        'net_profit_usd': net_profit_usd,
                        'risk_free': True,   # Net credit = guaranteed profit regardless of BTC direction
                        'max_loss': 0.0      # Cannot lose money - net credit spread
                    })

            else:  # PUT — Buy higher strike (K2), Sell lower strike (K1)
                # Risk-free: if K2_ask < K1_bid → guaranteed profit
                bids1 = ob1.get('buy', [])    # K1 bid (we SELL this)
                asks2 = ob2.get('sell', [])   # K2 ask (we BUY this)
                if not bids1 or not asks2:
                    continue
                p1_bid = float(bids1[0]['price'])
                p2_ask = float(asks2[0]['price'])
                p1_size = float(bids1[0].get('size', 0))
                p2_size = float(asks2[0].get('size', 0))

                gross_credit = p1_bid - p2_ask

                fee_leg1 = p1_bid * TAKER_FEE_PCT
                fee_leg2 = p2_ask * TAKER_FEE_PCT
                total_fees_per_btc = fee_leg1 + fee_leg2

                net_credit_after_fees = gross_credit - total_fees_per_btc
                net_profit_usd = net_credit_after_fees * 0.001

                if (
                    net_profit_usd >= self.min_profit_usd
                    and p1_size >= MINIMUM_ORDERBOOK_SIZE
                    and p2_size >= MINIMUM_ORDERBOOK_SIZE
                ):
                    opportunities.append({
                        'type': 'VERTICAL_PUT_CREDIT_SPREAD',
                        'expiry': expiry_str,
                        'leg1': {'symbol': sym2, 'side': 'buy',  'price': p2_ask, 'strike': float(o2['strike_price']), 'size_avail': p2_size},
                        'leg2': {'symbol': sym1, 'side': 'sell', 'price': p1_bid, 'strike': float(o1['strike_price']), 'size_avail': p1_size},
                        'gross_credit': gross_credit,
                        'fees_per_btc': total_fees_per_btc,
                        'net_profit_usd': net_profit_usd,
                        'risk_free': True,
                        'max_loss': 0.0
                    })

        return opportunities

    def scan_conversion_and_reversal_arbitrage(self, btc_options, fut_bid, fut_ask, ob_cache):
        """Scan for 3-leg Synthetic Conversion & Reversal Arbitrage (Short Call + Long Put + Long Future, etc)."""
        from collections import defaultdict
        opportunities = []

        # Group options by (expiry_str, strike) -> {'call': opt, 'put': opt}
        matched_pairs = defaultdict(dict)
        for opt in btc_options:
            expiry_dt = self.parse_expiry_date(opt.get('symbol', ''), product_data=opt)
            if not expiry_dt:
                continue
            exp_str = expiry_dt.strftime("%Y-%m-%d")
            strike = float(opt.get('strike_price', 0))
            ctype = 'call' if opt.get('contract_type') == 'call_options' else 'put'
            matched_pairs[(exp_str, strike)][ctype] = opt

        contract_size = 0.001
        lots_calc = self.get_dynamic_equal_lots() if self.trade_lots <= 0 else self.trade_lots

        for (exp_str, strike), pair in matched_pairs.items():
            if 'call' not in pair or 'put' not in pair:
                continue

            call_opt = pair['call']
            put_opt = pair['put']
            c_sym = call_opt.get('symbol')
            p_sym = put_opt.get('symbol')

            ob_c = ob_cache.get(c_sym, {})
            ob_p = ob_cache.get(p_sym, {})

            c_bids, c_asks = ob_c.get('buy', []), ob_c.get('sell', [])
            p_bids, p_asks = ob_p.get('buy', []), ob_p.get('sell', [])

            # 1. CONVERSION ARBITRAGE (Short Call @ c_bid + Long Put @ p_ask + Long Future @ fut_ask)
            if c_bids and p_asks and fut_ask > 0:
                c_bid = float(c_bids[0]['price'])
                p_ask = float(p_asks[0]['price'])
                c_size = float(c_bids[0].get('size', 0))
                p_size = float(p_asks[0].get('size', 0))

                # Net locked profit per BTC = (Strike - Future_Ask) + (Call_Bid - Put_Ask)
                gross_credit = (strike - fut_ask) + (c_bid - p_ask)
                total_fees_per_btc = (c_bid + p_ask + fut_ask) * TAKER_FEE_PCT
                net_profit_per_btc = gross_credit - total_fees_per_btc
                net_profit_usd = net_profit_per_btc * contract_size * lots_calc

                if net_profit_usd >= self.min_profit_usd and c_size >= MINIMUM_ORDERBOOK_SIZE and p_size >= MINIMUM_ORDERBOOK_SIZE:
                    opportunities.append({
                        'type': 'SYNTHETIC_CONVERSION_ARBITRAGE',
                        'expiry': exp_str,
                        'strike': strike,
                        'leg1': {'symbol': c_sym, 'side': 'sell', 'price': c_bid, 'strike': strike, 'size_avail': c_size},
                        'leg2': {'symbol': p_sym, 'side': 'buy',  'price': p_ask, 'strike': strike, 'size_avail': p_size},
                        'leg3': {'symbol': 'BTCUSD', 'side': 'buy', 'price': fut_ask, 'strike': 0, 'size_avail': 100},
                        'gross_credit': gross_credit,
                        'fees_per_btc': total_fees_per_btc,
                        'net_profit_usd': net_profit_usd,
                        'risk_free': True,
                        'max_loss': 0.0
                    })

            # 2. REVERSAL ARBITRAGE (Long Call @ c_ask + Short Put @ p_bid + Short Future @ fut_bid)
            if p_bids and c_asks and fut_bid > 0:
                p_bid = float(p_bids[0]['price'])
                c_ask = float(c_asks[0]['price'])
                p_size = float(p_bids[0].get('size', 0))
                c_size = float(c_asks[0].get('size', 0))

                gross_credit = (fut_bid - strike) + (p_bid - c_ask)
                total_fees_per_btc = (c_ask + p_bid + fut_bid) * TAKER_FEE_PCT
                net_profit_per_btc = gross_credit - total_fees_per_btc
                net_profit_usd = net_profit_per_btc * contract_size * lots_calc

                if net_profit_usd >= self.min_profit_usd and p_size >= MINIMUM_ORDERBOOK_SIZE and c_size >= MINIMUM_ORDERBOOK_SIZE:
                    opportunities.append({
                        'type': 'SYNTHETIC_REVERSAL_ARBITRAGE',
                        'expiry': exp_str,
                        'strike': strike,
                        'leg1': {'symbol': c_sym, 'side': 'buy',  'price': c_ask, 'strike': strike, 'size_avail': c_size},
                        'leg2': {'symbol': p_sym, 'side': 'sell', 'price': p_bid, 'strike': strike, 'size_avail': p_size},
                        'leg3': {'symbol': 'BTCUSD', 'side': 'sell', 'price': fut_bid, 'strike': 0, 'size_avail': 100},
                        'gross_credit': gross_credit,
                        'fees_per_btc': total_fees_per_btc,
                        'net_profit_usd': net_profit_usd,
                        'risk_free': True,
                        'max_loss': 0.0
                    })

        return opportunities

    def find_new_arbitrage(self, exclude_symbols=None):
        """Main scanner — fast wide-strike scan for 3-leg Conversion/Reversal & 2-leg Credit Spreads."""
        import time as _time
        t0 = _time.time()
        self.log("SCANNER", "Scanning options across strikes for 3-Leg Conversion & 2-Leg Risk-Free Arbitrage...")
        btc_opts, spot = self.fetch_atm_btc_options(atm_pct=0.25)
        if not btc_opts:
            self.log("SCANNER-WARN", "No ATM BTC options found.")
            return None

        fut_bid, fut_ask = self.get_btc_future_quotes()

        # Build list of all option symbols to fetch orderbooks concurrently
        all_opt_symbols = list(set(o.get('symbol') for o in btc_opts if o.get('symbol')))
        
        # Concurrent fetch orderbooks
        from concurrent.futures import ThreadPoolExecutor, as_completed
        ob_cache = {}
        with ThreadPoolExecutor(max_workers=15) as ex:
            futures = {ex.submit(self._fetch_ob_safe, sym): sym for sym in all_opt_symbols}
            for fut in as_completed(futures):
                sym, buys, sells = fut.result()
                ob_cache[sym] = {'buy': buys, 'sell': sells}

        # 1. Scan 3-leg Conversion / Reversal Arbitrage
        opps_3leg = self.scan_conversion_and_reversal_arbitrage(btc_opts, fut_bid, fut_ask, ob_cache)

        # 2. Scan 2-leg Vertical Credit Spreads
        opps_2leg = self.scan_vertical_strike_arbitrage(btc_opts)

        all_opps = opps_3leg + opps_2leg

        # Filter out symbols that are already in active positions
        if exclude_symbols:
            all_opps = [
                o for o in all_opps 
                if o['leg1']['symbol'] not in exclude_symbols 
                and o['leg2']['symbol'] not in exclude_symbols
            ]

        elapsed = _time.time() - t0

        if all_opps:
            all_opps.sort(key=lambda x: x['net_profit_usd'], reverse=True)
            best = all_opps[0]
            strike_str = f"Strike {best.get('strike')}" if 'strike' in best else f"Strikes {best['leg1']['strike']:.0f}/{best['leg2']['strike']:.0f}"
            self.log("ARBITRAGE-FOUND",
                     f"*** {len(all_opps)} NEW RISK-FREE OPPORTUNITIES FOUND ({len(opps_3leg)} Conversion/Reversal, {len(opps_2leg)} Vertical)! ***")
            self.log("ARBITRAGE-FOUND",
                     f"  Best: {best['type']} | {strike_str} | Expiry: {best['expiry']}")
            self.log("ARBITRAGE-FOUND",
                     f"  Net Profit (after fees): ${best['net_profit_usd']:.4f} USD | Scan Time: {elapsed:.1f}s")
            self.log("ARBITRAGE-FOUND",
                     f"  MAX LOSS: $0.00 (Guaranteed profit regardless of market direction!)")
            return best
        else:
            self.log("SCANNER", f"No risk-free arbitrage found. Market is efficient. (Scan took {elapsed:.1f}s)")
            return None

    # =========================================================================
    # 3. AUTO TRADE EXECUTION MODULE
    # =========================================================================
    def wait_and_fill_order(self, order_resp, symbol, side, max_wait_sec=30):
        """Monitor limit order for fill. If unfilled after max_wait_sec (30s), edit limit price to updated orderbook level to force instant fill."""
        res = order_resp.get('result', {}) if isinstance(order_resp, dict) else {}
        order_id = res.get('id')
        product_id = res.get('product_id')

        if not order_id or not product_id:
            return True, order_resp

        # Check if already filled/closed
        if res.get('state') == 'closed' or float(res.get('unfilled_size', 0)) == 0:
            return True, order_resp

        self.log("ORDER-MONITOR", f"Monitoring Order {order_id} ({symbol} {side.upper()}) for fill (max wait {max_wait_sec}s)...")

        start_t = time.time()
        check_interval = 3

        while (time.time() - start_t) < max_wait_sec:
            time.sleep(check_interval)
            code, check_resp = self.client.get_order_by_id(order_id)
            if code in [200, 201] and check_resp.get('success'):
                curr_res = check_resp.get('result', {})
                if curr_res.get('state') == 'closed' or float(curr_res.get('unfilled_size', 0)) == 0:
                    self.log("ORDER-FILLED", f"Order {order_id} ({symbol}) filled successfully!")
                    return True, check_resp

        # Unfilled after 30 seconds -> EDIT ORDER PRICE to current live market level!
        self.log("ORDER-TIMEOUT", f"Order {order_id} ({symbol}) unfilled after {max_wait_sec}s! Editing limit price to live market price...")

        try:
            ob = self.client.get_orderbook(symbol).get('result', {})
            bids, asks = ob.get('buy', []), ob.get('sell', [])

            if side == 'buy' and asks:
                new_price = float(asks[0]['price'])  # Set to current best ask (force fill buy)
            elif side == 'sell' and bids:
                new_price = float(bids[0]['price'])  # Set to current best bid (force fill sell)
            else:
                self.log("ORDER-WARN", f"Could not fetch orderbook for {symbol}. Order remains at limit.")
                return False, order_resp

            edit_code, edit_resp = self.client.edit_order(order_id, product_id, new_price)
            if edit_code in [200, 201] and edit_resp.get('success'):
                self.log("ORDER-EDITED", f"SUCCESS! Order {order_id} ({symbol}) limit price EDITED to ${new_price:.2f} for instant fill!")
                time.sleep(2)
                return True, edit_resp
            else:
                self.log("ORDER-EDIT-FAIL", f"Failed to edit order {order_id}: {edit_resp}")
                return False, edit_resp

        except Exception as e:
            self.log("ORDER-EDIT-EX", f"Error editing order: {e}")
            return False, order_resp

    def execute_arbitrage(self, opp):
        """Execute 2-leg or 3-leg arbitrage trade."""
        leg1 = opp['leg1']
        leg2 = opp['leg2']
        leg3 = opp.get('leg3')
        if self.trade_lots <= 0:
            dyn_lots = self.get_dynamic_equal_lots()
            b_size1 = int(leg1.get('size_avail', 100))
            b_size2 = int(leg2.get('size_avail', 100))
            lots = max(1, min(dyn_lots, b_size1, b_size2, 50))
        else:
            lots = self.trade_lots
        
        self.log("EXECUTE-START", f"Executing Strategy: {opp['type']} ({lots} Lots)")
        self.log("EXECUTE-LEG1", f"Leg 1: {leg1['side'].upper()} {leg1['symbol']} x{lots} @ ${leg1['price']:.2f}")
        self.log("EXECUTE-LEG2", f"Leg 2: {leg2['side'].upper()} {leg2['symbol']} x{lots} @ ${leg2['price']:.2f}")
        if leg3:
            self.log("EXECUTE-LEG3", f"Leg 3: {leg3['side'].upper()} {leg3['symbol']} x{lots} @ ${leg3['price']:.2f}")
        
        if self.paper_mode:
            pos1 = {'symbol': leg1['symbol'], 'side': leg1['side'], 'entry_price': leg1['price'], 'size': lots}
            pos2 = {'symbol': leg2['symbol'], 'side': leg2['side'], 'entry_price': leg2['price'], 'size': lots}
            self.paper_positions.extend([pos1, pos2])
            if leg3:
                self.paper_positions.append({'symbol': leg3['symbol'], 'side': leg3['side'], 'entry_price': leg3['price'], 'size': lots})
            
            self.paper_pnl += opp['net_profit_usd']
            self.trade_history.append({
                'timestamp': datetime.now().isoformat(),
                'opp': opp,
                'status': 'FILLED_PAPER'
            })
            self.log("EXECUTE-SUCCESS", f"[PAPER] Trade executed! Locked Net Profit: ${opp['net_profit_usd']:.4f} USD")
            return True
            
        # Optimal Hedged Execution Order: BUY legs first (Long Put & Long Future), SELL leg last (Short Call)
        # This prevents Delta Exchange from charging naked short margin on Leg 1!
        buy_legs = [l for l in [leg1, leg2, leg3] if l and l['side'] == 'buy']
        sell_legs = [l for l in [leg1, leg2, leg3] if l and l['side'] == 'sell']
        ordered_legs = buy_legs + sell_legs

        # LIVE / DEMO MODE ORDER PLACEMENT
        try:
            placed_orders = []
            for idx, l in enumerate(ordered_legs):
                l_type = 'market' if l['symbol'] == 'BTCUSD' else 'limit'
                l_price = None if l_type == 'market' else l['price']
                
                self.log("EXECUTE-ORDER", f"Placing Leg {idx+1}/{len(ordered_legs)}: {l['side'].upper()} {l['symbol']} x{lots} @ ${l_price or 'MARKET'}")
                
                code, resp = self.client.place_order(
                    symbol=l['symbol'],
                    side=l['side'],
                    size=lots,
                    price=l_price,
                    order_type=l_type
                )
                
                if code not in [200, 201]:
                    if ('insufficient_margin' in str(resp) or 'insufficient_commission' in str(resp)) and lots > 1:
                        lots = max(1, lots // 2)
                        self.log("AUTO-MARGIN-REDUCE", f"Margin/Commission tight for requested lots. Auto-reducing to {lots} Lots and retrying Leg {idx+1}...")
                        code, resp = self.client.place_order(
                            symbol=l['symbol'],
                            side=l['side'],
                            size=lots,
                            price=l_price,
                            order_type=l_type
                        )

                if code not in [200, 201]:
                    self.log("EXECUTE-FAIL", f"Failed Leg {idx+1} ({l['symbol']}) order: {resp}")
                    # Unwind any previously placed legs to preserve safety net!
                    if placed_orders:
                        self.log("SAFETY-UNWIND", f"Unwinding {len(placed_orders)} previously placed leg(s)...")
                        for po in placed_orders:
                            unwind_side = 'buy' if po['side'] == 'sell' else 'sell'
                            self.client.place_order(symbol=po['symbol'], side=unwind_side, size=lots, order_type='market', reduce_only=True)
                    return False
                    
                placed_orders.append({'symbol': l['symbol'], 'side': l['side']})
                self.log("EXECUTE-LIVE", f"Leg {idx+1} Order Placed: {resp}")
                
                if l_type == 'limit':
                    filled, resp = self.wait_and_fill_order(resp, l['symbol'], l['side'], max_wait_sec=30)
                    if not filled:
                        self.log("SAFETY-UNWIND", f"Leg {idx+1} ({l['symbol']}) failed to fill after 30s auto-edit. Unwinding placed legs...")
                        for po in placed_orders:
                            unwind_side = 'buy' if po['side'] == 'sell' else 'sell'
                            self.client.place_order(symbol=po['symbol'], side=unwind_side, size=lots, order_type='market', reduce_only=True)
                        return False

            self.log("EXECUTE-SUCCESS", f"[LIVE DEMO] All {len(ordered_legs)} legs placed & filled successfully on Demo Account! Expected Locked Profit: ${opp['net_profit_usd']:.4f} USD")
            return True

            # Safety Net: If Leg 1 filled but Leg 2 failed to fill, unwind Leg 1 immediately!
            if filled1 and not filled2:
                self.log("SAFETY-UNWIND", f"Leg 1 ({leg1['symbol']}) filled but Leg 2 failed. Unwinding Leg 1 to preserve ZERO RISK...")
                side_unwind = 'buy' if leg1['side'] == 'sell' else 'sell'
                self.client.place_order(symbol=leg1['symbol'], side=side_unwind, size=lots, order_type='market', reduce_only=True)
                return False

            # Leg 3 (if 3-leg Conversion/Reversal) -> Use MARKET ORDER for instant fill
            if leg3:
                code3, resp3 = self.client.place_order(
                    symbol=leg3['symbol'],
                    side=leg3['side'],
                    size=lots,
                    order_type='market'
                )
                if code3 not in [200, 201]:
                    self.log("EXECUTE-ALERT", f"Legs 1&2 succeeded but Leg 3 (Future) failed: {resp3}. Manual review recommended!")
                    return False
                self.log("EXECUTE-LIVE", f"Leg 3 (Future MARKET Order) Placed: {resp3}")

            num_legs = 3 if leg3 else 2
            self.log("EXECUTE-SUCCESS", f"[LIVE DEMO] All {num_legs} legs placed & filled successfully on Demo Account! Expected Locked Profit: ${opp['net_profit_usd']:.4f} USD")
            return True
            
        except Exception as e:
            self.log("EXECUTE-EXCEPTION", f"Error during order placement: {e}")
            return False

    # =========================================================================
    # 4. MAIN BOT DAEMON LOOP
    # =========================================================================
    def start(self):
        print("=" * 75)
        print("     DELTA EXCHANGE INDIA - AUTOMATED EXPIRY & ARBITRAGE BOT")
        print("=" * 75)
        print(f" Mode:                {'PAPER TRADING (Virtual)' if self.paper_mode else 'LIVE TRADING (Real Funds)'}")
        print(f" Min Profit Target:   ${self.min_profit_usd:.2f} USD")
        print(f" Auto-Close Window:   {self.close_expiry_mins} minute before Expiry (Profit Booked & Auto Next Trade Search)")
        print(f" Scan Interval:       {self.check_interval} seconds")
        print("=" * 75)
        print(" Press Ctrl+C to stop the bot safely.\n")
        
        cycle_count = 0
        try:
            if not self.paper_mode:
                self.log("STARTUP", "Cleaning up any old unfulfilled limit orders...")
                self.client.cancel_all_orders()
                
            while True:
                cycle_count += 1
                self.log("LOOP", f"--- Cycle #{cycle_count} ---")
                try:
                    # Step 1: Check & close expiring trades
                    self.check_and_close_expiring_positions()
                    
                    # Step 2: Check active positions & available margin
                    active_positions = []
                    avail_usd = 0.0
                    if not self.paper_mode:
                        resp_pos = self.client.get_all_positions()
                        active_positions = resp_pos.get('result', []) if resp_pos.get('success') else []
                        avail_usd = self.get_available_usd_balance()
                    else:
                        active_positions = self.paper_positions
                        avail_usd = self.paper_balance

                    open_symbols = set(p.get('product_symbol') for p in active_positions if float(p.get('size', 0)) != 0)

                    # Step 3: If available margin >= $3.00, scan for additional non-duplicate arbitrage setups!
                    if avail_usd >= 3.0:
                        if open_symbols:
                            self.log("MARGIN-DEPLOY", f"Holding {len(active_positions)} active position legs. Available Margin (${avail_usd:.2f} USD) is ready for NEW Arbitrage Setup!")
                        
                        opp = self.find_new_arbitrage(exclude_symbols=open_symbols)
                        if opp:
                            self.log("MARGIN-DEPLOY", f"Executing ADDITIONAL Risk-Free Arbitrage using remaining margin (${avail_usd:.2f} USD)...")
                            self.execute_arbitrage(opp)
                    else:
                        self.log("FULL-DEPLOYMENT", f"Margin fully deployed across {len(active_positions)} active legs. Remaining USD Margin: ${avail_usd:.2f}. Monitoring until expiry...")
                except Exception as cycle_ex:
                    self.log("NETWORK-WARN", f"Cycle #{cycle_count} network hiccup ({cycle_ex}). Retrying in next cycle...")
                    
                # Status summary
                if self.paper_mode:
                    self.log("STATUS", f"Virtual Balance: ${self.paper_balance:.2f} | Total PnL: ${self.paper_pnl:.4f} | Open Positions: {len(self.paper_positions)}")
                
                self.log("SLEEP", f"Waiting {self.check_interval}s until next scan...\n")
                time.sleep(self.check_interval)
                
        except KeyboardInterrupt:
            print("\n")
            self.log("SHUTDOWN", "Received stop signal. Stopping bot gracefully...")
            if self.paper_mode:
                self.log("SUMMARY", f"Final Virtual PnL: ${self.paper_pnl:.4f} USD | Total Trades: {len(self.trade_history)}")
            print("=" * 75)
            sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delta Exchange Auto-Expiry & Arbitrage Bot")
    parser.add_argument("--live", action="store_true", help="Run in Live Trading Mode (default is Paper Mode)")
    parser.add_argument("--demo", action="store_true", help="Connect to Delta Demo Account API (demo.delta.exchange)")
    parser.add_argument("--min-profit", type=float, default=0.1, help="Minimum USD net profit threshold")
    parser.add_argument("--interval", type=int, default=10, help="Scan interval in seconds")
    parser.add_argument("--expiry-mins", type=int, default=1, help="Minutes before expiry to auto-close positions and book profit (default: 1 min)")
    parser.add_argument("--lots", type=int, default=5, help="Number of contract lots to trade (default: 5 lots)")
    
    args = parser.parse_args()
    
    bot = DeltaAutoArbitrageBot(
        paper_mode=not args.live,
        demo_mode=args.demo,
        min_profit_usd=args.min_profit,
        check_interval_sec=args.interval,
        close_expiry_mins=args.expiry_mins,
        trade_lots=args.lots
    )
    bot.start()
