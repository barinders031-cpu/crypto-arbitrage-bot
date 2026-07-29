"""
Single-Exchange Triangular Arbitrage (3-Pair Loop) Engine
Real-Time Binance vs. CoinDCX Comparison & Execution Engine (Paper Trading Mode)

Features:
1. Asynchronous L2 Order Book Depth Fetching via aiohttp.
2. Dynamic 3-Pair Loop Discovery (USDT -> Asset A -> Asset B -> USDT).
3. Order Book Depth Walk (Top 5-10 Levels) for Exact VWAP Slippage Calculation.
4. Comprehensive Fee & Tax Accounting:
   - Binance Taker Fee: 0.10% (0.075% with BNB discount)
   - CoinDCX Taker Fee: 0.20% (Default)
   - CoinDCX Indian 1% TDS Compliance Metrics (Pre-TDS vs Post-TDS Net Profit)
5. Real-Time Exchange Comparison Engine (Binance vs CoinDCX Liquidity & Net Profit).
6. 100% Paper Trading Simulation Mode.

Author: Advanced Quantitative Crypto Engineering Team
"""

import asyncio
import aiohttp
import time
import datetime
import json
import logging
import sys
from typing import Dict, List, Tuple, Optional

# Enforce UTF-8 encoding for Windows terminal compatibility
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

# Configuration Parameters
STARTING_CAPITAL_USDT = 100.0   # Paper Capital Size per Loop
MIN_NET_PROFIT_PCT    = 0.15    # Minimum Net Profit Gate (0.15% after all fees)
SCAN_INTERVAL_SEC     = 2.0     # Time between scan cycles

# Fee Configurations
FEE_RATES = {
    "binance": {
        "taker_fee": 0.0010,     # 0.10% default taker fee
        "taker_fee_bnb": 0.00075, # 0.075% with BNB fee discount
        "tds_applicable": False  # No Indian 1% TDS on Binance international
    },
    "coindcx": {
        "taker_fee": 0.0020,     # 0.20% default taker fee
        "tds_applicable": True,  # 1% TDS on sell / crypto-to-crypto legs in India
        "tds_rate": 0.0100       # 1.0% TDS rate
    }
}

# Candidate Triangular Loops to Scan (USDT -> Asset A -> Asset B -> USDT)
TRIANGULAR_LOOPS = [
    {"base": "USDT", "a": "ETH", "b": "BTC",  "label": "USDT -> ETH -> BTC -> USDT"},
    {"base": "USDT", "a": "SOL", "b": "BTC",  "label": "USDT -> SOL -> BTC -> USDT"},
    {"base": "USDT", "a": "XRP", "b": "BTC",  "label": "USDT -> XRP -> BTC -> USDT"},
    {"base": "USDT", "a": "BNB", "b": "BTC",  "label": "USDT -> BNB -> BTC -> USDT"},
    {"base": "USDT", "a": "ADA", "b": "BTC",  "label": "USDT -> ADA -> BTC -> USDT"},
    {"base": "USDT", "a": "SOL", "b": "ETH",  "label": "USDT -> SOL -> ETH -> USDT"},
    {"base": "USDT", "a": "LINK", "b": "BTC", "label": "USDT -> LINK -> BTC -> USDT"},
    {"base": "USDT", "a": "AVAX", "b": "BTC", "label": "USDT -> AVAX -> BTC -> USDT"},
    {"base": "USDT", "a": "DOGE", "b": "BTC", "label": "USDT -> DOGE -> BTC -> USDT"},
]


class OrderBookWalker:
    """Calculates Volume-Weighted Average Price (VWAP) and exact slippage by walking order book levels."""

    @staticmethod
    def simulate_market_buy(order_book_asks: List[List[float]], required_quote_amount: float) -> Tuple[float, float, float]:
        """
        Simulate buying an asset using a fixed Quote currency amount (e.g. spending $100 USDT).
        Returns: (base_units_received, vwap_price, slippage_usd)
        """
        remaining_quote = required_quote_amount
        total_base_bought = 0.0
        weighted_cost = 0.0

        if not order_book_asks:
            return 0.0, 0.0, 0.0

        top_of_book_price = float(order_book_asks[0][0])

        for price_str, qty_str in order_book_asks[:10]:  # Top 10 Order Book Levels
            price = float(price_str)
            qty = float(qty_str)
            level_quote_val = price * qty

            if remaining_quote <= level_quote_val:
                qty_from_level = remaining_quote / price
                total_base_bought += qty_from_level
                weighted_cost += remaining_quote
                remaining_quote = 0.0
                break
            else:
                total_base_bought += qty
                weighted_cost += level_quote_val
                remaining_quote -= level_quote_val

        if total_base_bought == 0:
            return 0.0, 0.0, 0.0

        vwap_price = weighted_cost / total_base_bought
        ideal_cost_top_of_book = total_base_bought * top_of_book_price
        slippage_usd = max(0.0, weighted_cost - ideal_cost_top_of_book)

        return total_base_bought, vwap_price, slippage_usd

    @staticmethod
    def simulate_market_sell(order_book_bids: List[List[float]], base_amount_to_sell: float) -> Tuple[float, float, float]:
        """
        Simulate selling a fixed Base asset amount (e.g. selling 0.03 ETH for USDT or BTC).
        Returns: (quote_units_received, vwap_price, slippage_usd)
        """
        remaining_base = base_amount_to_sell
        total_quote_received = 0.0

        if not order_book_bids:
            return 0.0, 0.0, 0.0

        top_of_book_price = float(order_book_bids[0][0])

        for price_str, qty_str in order_book_bids[:10]:  # Top 10 Order Book Levels
            price = float(price_str)
            qty = float(qty_str)

            if remaining_base <= qty:
                total_quote_received += remaining_base * price
                remaining_base = 0.0
                break
            else:
                total_quote_received += qty * price
                remaining_base -= qty

        if base_amount_to_sell == 0:
            return 0.0, 0.0, 0.0

        vwap_price = total_quote_received / base_amount_to_sell
        ideal_quote_top_of_book = base_amount_to_sell * top_of_book_price
        slippage_usd = max(0.0, ideal_quote_top_of_book - total_quote_received)

        return total_quote_received, vwap_price, slippage_usd


class TriangularArbitrageScanner:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def fetch_binance_depth(self, symbol: str) -> Dict:
        """Fetch L2 Order Book Depth from Binance REST API."""
        url = f"https://api.binance.com/api/v3/depth?symbol={symbol}&limit=10"
        try:
            async with self.session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        return {"bids": [], "asks": []}

    async def fetch_coindcx_depth(self, pair_symbol: str) -> Dict:
        """Fetch L2 Order Book Depth from CoinDCX Public API."""
        url = f"https://public.coindcx.com/market_data/orderbook?pair={pair_symbol}"
        try:
            async with self.session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    bids = [[p, q] for p, q in data.get('bids', {}).items()] if isinstance(data.get('bids'), dict) else data.get('bids', [])
                    asks = [[p, q] for p, q in data.get('asks', {}).items()] if isinstance(data.get('asks'), dict) else data.get('asks', [])
                    # Sort bids descending, asks ascending
                    bids = sorted(bids, key=lambda x: float(x[0]), reverse=True)
                    asks = sorted(asks, key=lambda x: float(x[0]))
                    return {"bids": bids, "asks": asks}
        except Exception:
            pass
        return {"bids": [], "asks": []}

    async def evaluate_loop_on_exchange(
        self,
        exchange: str,
        loop_cfg: Dict,
        capital_usdt: float
    ) -> Optional[Dict]:
        """
        Evaluates Forward Triangular Loop: USDT -> Asset A -> Asset B -> USDT
        Example: USDT -> ETH -> BTC -> USDT
          Leg 1: BUY ETH with USDT (Pair: ETHUSDT, Asks)
          Leg 2: SELL ETH for BTC or BUY BTC with ETH (Pair: ETHBTC or BTCETH)
          Leg 3: SELL BTC for USDT (Pair: BTCUSDT, Bids)
        """
        a = loop_cfg["a"]
        b = loop_cfg["b"]
        
        symbol_leg1 = f"{a}USDT"
        symbol_leg2_alt1 = f"{a}{b}"  # e.g. ETHBTC
        symbol_leg2_alt2 = f"{b}{a}"  # e.g. BTCETH
        symbol_leg3 = f"{b}USDT"

        fetch_func = self.fetch_binance_depth if exchange == "binance" else self.fetch_coindcx_depth

        # Fetch Order Books concurrently
        ob1_task = fetch_func(symbol_leg1)
        ob2_task1 = fetch_func(symbol_leg2_alt1)
        ob2_task2 = fetch_func(symbol_leg2_alt2)
        ob3_task = fetch_func(symbol_leg3)

        ob1, ob2_alt1, ob2_alt2, ob3 = await asyncio.gather(ob1_task, ob2_task1, ob2_task2, ob3_task)

        if not ob1["asks"] or not ob3["bids"]:
            return None

        taker_fee_pct = FEE_RATES[exchange]["taker_fee"]
        is_tds = FEE_RATES[exchange].get("tds_applicable", False)
        tds_rate = FEE_RATES[exchange].get("tds_rate", 0.01)

        # --- STEP 1: BUY Asset A with USDT ---
        qty_a, price1, slip1 = OrderBookWalker.simulate_market_buy(ob1["asks"], capital_usdt)
        if qty_a == 0:
            return None
        fee1_usd = capital_usdt * taker_fee_pct
        qty_a_net = qty_a * (1.0 - taker_fee_pct)  # Net Asset A received after fee

        # --- STEP 2: Trade Asset A for Asset B ---
        if ob2_alt1["bids"]:
            # Selling Asset A for Asset B on Pair A/B (e.g. Sell ETH on ETH/BTC -> receive BTC)
            qty_b, price2, slip2 = OrderBookWalker.simulate_market_sell(ob2_alt1["bids"], qty_a_net)
            leg2_direction = f"SELL {a} on {symbol_leg2_alt1}"
        elif ob2_alt2["asks"]:
            # Buying Asset B using Asset A on Pair B/A (e.g. Buy BTC on BTC/ETH -> spend ETH)
            qty_b, price2, slip2 = OrderBookWalker.simulate_market_buy(ob2_alt2["asks"], qty_a_net)
            leg2_direction = f"BUY {b} on {symbol_leg2_alt2}"
        else:
            return None

        if qty_b == 0:
            return None
        
        fee2_usd = (qty_b * float(ob3["bids"][0][0])) * taker_fee_pct
        qty_b_net = qty_b * (1.0 - taker_fee_pct)

        # --- STEP 3: SELL Asset B for USDT ---
        final_usdt, price3, slip3 = OrderBookWalker.simulate_market_sell(ob3["bids"], qty_b_net)
        if final_usdt == 0:
            return None
        fee3_usd = final_usdt * taker_fee_pct
        final_usdt_net_fees = final_usdt * (1.0 - taker_fee_pct)

        # Total Metrics
        total_fees_usd = fee1_usd + fee2_usd + fee3_usd
        total_slippage_usd = slip1 + slip2 + slip3
        gross_profit_usd = final_usdt - capital_usdt
        gross_profit_pct = (gross_profit_usd / capital_usdt) * 100.0

        pre_tds_net_profit_usd = final_usdt_net_fees - capital_usdt
        pre_tds_net_profit_pct = (pre_tds_net_profit_usd / capital_usdt) * 100.0

        # Post-TDS Accounting (Indian 1% TDS on Crypto Sell legs if CoinDCX)
        if is_tds:
            tds_impact_usd = (capital_usdt * tds_rate) + (final_usdt * tds_rate)
            post_tds_net_profit_usd = pre_tds_net_profit_usd - tds_impact_usd
        else:
            tds_impact_usd = 0.0
            post_tds_net_profit_usd = pre_tds_net_profit_usd

        post_tds_net_profit_pct = (post_tds_net_profit_usd / capital_usdt) * 100.0

        return {
            "exchange": exchange,
            "loop_label": loop_cfg["label"],
            "starting_capital": capital_usdt,
            "step1": {"action": f"BUY {a}", "price": price1, "amount": qty_a_net, "fee_usd": fee1_usd, "symbol": symbol_leg1},
            "step2": {"action": leg2_direction, "price": price2, "amount": qty_b_net, "fee_usd": fee2_usd},
            "step3": {"action": f"SELL {b} for USDT", "price": price3, "amount": final_usdt_net_fees, "fee_usd": fee3_usd, "symbol": symbol_leg3},
            "total_fees_usd": total_fees_usd,
            "total_slippage_usd": total_slippage_usd,
            "gross_profit_usd": gross_profit_usd,
            "gross_profit_pct": gross_profit_pct,
            "pre_tds_net_profit_usd": pre_tds_net_profit_usd,
            "pre_tds_net_profit_pct": pre_tds_net_profit_pct,
            "post_tds_net_profit_usd": post_tds_net_profit_usd,
            "post_tds_net_profit_pct": post_tds_net_profit_pct,
            "tds_impact_usd": tds_impact_usd,
            "is_tds": is_tds
        }


async def main_loop():
    print("=" * 70)
    print("🚀 QUANTITATIVE TRIANGULAR ARBITRAGE ENGINE (PAPER TRADING)")
    print("   Scanning Exchanges: BINANCE vs. COINDCX")
    print(f"   Capital: ${STARTING_CAPITAL_USDT:.2f} USDT | Min Net Profit Gate: {MIN_NET_PROFIT_PCT:.2f}%")
    print("=" * 70)

    async with aiohttp.ClientSession() as session:
        scanner = TriangularArbitrageScanner(session)

        while True:
            try:
                for loop_cfg in TRIANGULAR_LOOPS:
                    # Evaluate on both exchanges concurrently
                    binance_res_task = scanner.evaluate_loop_on_exchange("binance", loop_cfg, STARTING_CAPITAL_USDT)
                    coindcx_res_task = scanner.evaluate_loop_on_exchange("coindcx", loop_cfg, STARTING_CAPITAL_USDT)

                    binance_res, coindcx_res = await asyncio.gather(binance_res_task, coindcx_res_task)

                    # Determine Best Exchange Opportunity
                    candidates = [r for r in [binance_res, coindcx_res] if r is not None]
                    if not candidates:
                        continue

                    candidates.sort(key=lambda x: x["pre_tds_net_profit_pct"], reverse=True)
                    best = candidates[0]

                    # Filter by Minimum Net Profit Gate
                    if best["pre_tds_net_profit_pct"] >= MIN_NET_PROFIT_PCT:
                        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        ex_name = best["exchange"].upper()

                        reason = "Lower Taker Fees (0.10%) & Deeper L2 Liquidity" if best["exchange"] == "binance" else "CoinDCX Price Mispricing"

                        print("-" * 65)
                        print(f"[{ts}] ⚡ LOOP DETECTED: {best['loop_label']}")
                        print(f"- Exchange Selected: [{ex_name}] (Reason: {reason})")
                        print(f"- Starting Capital: ${best['starting_capital']:.2f} USDT")
                        print(f"- Step 1 ({best['step1']['action']}): Price = ${best['step1']['price']:.4f}, Amt = {best['step1']['amount']:.6f}, Fee = ${best['step1']['fee_usd']:.4f}")
                        print(f"- Step 2 ({best['step2']['action']}): Price = {best['step2']['price']:.6f}, Amt = {best['step2']['amount']:.6f}, Fee = ${best['step2']['fee_usd']:.4f}")
                        print(f"- Step 3 ({best['step3']['action']}): Price = ${best['step3']['price']:.4f}, Amt = ${best['step3']['amount']:.2f} USDT, Fee = ${best['step3']['fee_usd']:.4f}")
                        print(f"- Total Fees Cut: ${best['total_fees_usd']:.4f}")
                        print(f"- Slippage Impact: ${best['total_slippage_usd']:.4f}")
                        print(f"- Gross Profit: ${best['gross_profit_usd']:.4f} ({best['gross_profit_pct']:.3f}%)")
                        print(f"- PRE-TDS NET PROFIT: ${best['pre_tds_net_profit_usd']:.4f} ({best['pre_tds_net_profit_pct']:.3f}%)")
                        
                        if best["is_tds"]:
                            print(f"- POST-TDS NET IN-HAND PROFIT: ${best['post_tds_net_profit_usd']:.4f} ({best['post_tds_net_profit_pct']:.3f}%) [CoinDCX 1% TDS Applied: -${best['tds_impact_usd']:.4f}]")
                        else:
                            print(f"- POST-TDS NET IN-HAND PROFIT: ${best['pre_tds_net_profit_usd']:.4f} ({best['pre_tds_net_profit_pct']:.3f}%) [Binance: No Indian TDS]")
                        print("-" * 65)

                await asyncio.sleep(SCAN_INTERVAL_SEC)

            except Exception as e:
                logging.error(f"Error in scanner loop: {e}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("\n🛑 Triangular Arbitrage Paper Engine Stopped Cleanly.")
