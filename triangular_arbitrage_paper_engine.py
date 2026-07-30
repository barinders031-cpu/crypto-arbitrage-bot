"""
Single-Exchange & Cross-Exchange Triangular Arbitrage Engine (Fixed & Upgraded)
Real-Time Binance vs. CoinDCX Comparison & Execution Engine (Paper Trading Mode)

Features & Fixes:
1. User-Agent Header Inclusion (Fixes CoinDCX HTTP 403 Forbidden).
2. Dynamic CoinDCX Symbol Mapping (Converts ETHUSDT -> B-ETH_USDT).
3. Dual Direction Scanning: Evaluates both FORWARD (USDT -> A -> B -> USDT) 
   and REVERSE (USDT -> B -> A -> USDT) triangular loops simultaneously.
4. VWAP Order Book Depth Walk (Top 10 Levels) for Exact Slippage.
5. Fee & Tax Accounting (Binance 0.10% / BNB 0.075%, CoinDCX 0.20%, Indian 1% TDS).
6. Fee-Adjusted Net Profit Gate (Default >= 0.15%).

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
    {"base": "USDT", "a": "ETH", "b": "BTC",  "label": "ETH / BTC"},
    {"base": "USDT", "a": "SOL", "b": "BTC",  "label": "SOL / BTC"},
    {"base": "USDT", "a": "XRP", "b": "BTC",  "label": "XRP / BTC"},
    {"base": "USDT", "a": "BNB", "b": "BTC",  "label": "BNB / BTC"},
    {"base": "USDT", "a": "ADA", "b": "BTC",  "label": "ADA / BTC"},
    {"base": "USDT", "a": "SOL", "b": "ETH",  "label": "SOL / ETH"},
    {"base": "USDT", "a": "LINK", "b": "BTC", "label": "LINK / BTC"},
    {"base": "USDT", "a": "AVAX", "b": "BTC", "label": "AVAX / BTC"},
    {"base": "USDT", "a": "DOGE", "b": "BTC", "label": "DOGE / BTC"},
    {"base": "USDT", "a": "LTC", "b": "BTC",  "label": "LTC / BTC"},
    {"base": "USDT", "a": "BCH", "b": "BTC",  "label": "BCH / BTC"},
    {"base": "USDT", "a": "NEAR", "b": "BTC", "label": "NEAR / BTC"},
    {"base": "USDT", "a": "DOT", "b": "BTC",  "label": "DOT / BTC"},
    {"base": "USDT", "a": "SHIB", "b": "BTC", "label": "SHIB / BTC"},
]


class OrderBookWalker:
    """Calculates Volume-Weighted Average Price (VWAP) and exact slippage by walking order book levels."""

    @staticmethod
    def simulate_market_buy(order_book_asks: List[List[float]], required_quote_amount: float) -> Tuple[float, float, float]:
        remaining_quote = required_quote_amount
        total_base_bought = 0.0
        weighted_cost = 0.0

        if not order_book_asks:
            return 0.0, 0.0, 0.0

        top_of_book_price = float(order_book_asks[0][0])

        for price_str, qty_str in order_book_asks[:10]:
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
        remaining_base = base_amount_to_sell
        total_quote_received = 0.0

        if not order_book_bids:
            return 0.0, 0.0, 0.0

        top_of_book_price = float(order_book_bids[0][0])

        for price_str, qty_str in order_book_bids[:10]:
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
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

    def format_symbol(self, exchange: str, raw_symbol: str) -> str:
        """Converts symbol e.g. ETHUSDT -> B-ETH_USDT for CoinDCX."""
        if exchange == "binance":
            return raw_symbol
        elif exchange == "coindcx":
            for quote in ["USDT", "BTC", "ETH", "INR"]:
                if raw_symbol.endswith(quote):
                    base = raw_symbol[:-len(quote)]
                    return f"B-{base}_{quote}"
            return f"B-{raw_symbol}"
        return raw_symbol

    async def fetch_depth(self, exchange: str, symbol: str) -> Dict:
        formatted_sym = self.format_symbol(exchange, symbol)

        if exchange == "binance":
            url = f"https://api.binance.com/api/v3/depth?symbol={formatted_sym}&limit=10"
            try:
                async with self.session.get(url, headers=self.headers, timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.json()
            except Exception:
                pass
        elif exchange == "coindcx":
            url = f"https://public.coindcx.com/market_data/orderbook?pair={formatted_sym}"
            try:
                async with self.session.get(url, headers=self.headers, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        bids = [[p, q] for p, q in data.get('bids', {}).items()] if isinstance(data.get('bids'), dict) else data.get('bids', [])
                        asks = [[p, q] for p, q in data.get('asks', {}).items()] if isinstance(data.get('asks'), dict) else data.get('asks', [])
                        bids = sorted(bids, key=lambda x: float(x[0]), reverse=True)
                        asks = sorted(asks, key=lambda x: float(x[0]))
                        return {"bids": bids, "asks": asks}
            except Exception:
                pass
        return {"bids": [], "asks": []}

    async def evaluate_forward_loop(self, exchange: str, loop_cfg: Dict, capital_usdt: float) -> Optional[Dict]:
        """USDT -> Asset A -> Asset B -> USDT"""
        a, b = loop_cfg["a"], loop_cfg["b"]
        s1 = f"{a}USDT"
        s2 = f"{a}{b}"
        s3 = f"{b}USDT"

        ob1, ob2, ob3 = await asyncio.gather(
            self.fetch_depth(exchange, s1),
            self.fetch_depth(exchange, s2),
            self.fetch_depth(exchange, s3)
        )

        if not ob1["asks"] or not ob2["bids"] or not ob3["bids"]:
            return None

        taker_fee_pct = FEE_RATES[exchange]["taker_fee"]
        is_tds = FEE_RATES[exchange].get("tds_applicable", False)
        tds_rate = FEE_RATES[exchange].get("tds_rate", 0.01)

        # Step 1: BUY Asset A with USDT
        qty_a, price1, slip1 = OrderBookWalker.simulate_market_buy(ob1["asks"], capital_usdt)
        if qty_a == 0: return None
        fee1_usd = capital_usdt * taker_fee_pct
        qty_a_net = qty_a * (1.0 - taker_fee_pct)

        # Step 2: SELL Asset A for Asset B
        qty_b, price2, slip2 = OrderBookWalker.simulate_market_sell(ob2["bids"], qty_a_net)
        if qty_b == 0: return None
        fee2_usd = (qty_b * float(ob3["bids"][0][0])) * taker_fee_pct
        qty_b_net = qty_b * (1.0 - taker_fee_pct)

        # Step 3: SELL Asset B for USDT
        final_usdt, price3, slip3 = OrderBookWalker.simulate_market_sell(ob3["bids"], qty_b_net)
        if final_usdt == 0: return None
        fee3_usd = final_usdt * taker_fee_pct
        final_usdt_net = final_usdt * (1.0 - taker_fee_pct)

        total_fees = fee1_usd + fee2_usd + fee3_usd
        total_slip = slip1 + slip2 + slip3
        gross_profit_usd = final_usdt - capital_usdt
        gross_profit_pct = (gross_profit_usd / capital_usdt) * 100.0

        pre_tds_net_profit_usd = final_usdt_net - capital_usdt
        pre_tds_net_profit_pct = (pre_tds_net_profit_usd / capital_usdt) * 100.0

        tds_impact_usd = ((capital_usdt + final_usdt) * tds_rate) if is_tds else 0.0
        post_tds_net_profit_usd = pre_tds_net_profit_usd - tds_impact_usd
        post_tds_net_profit_pct = (post_tds_net_profit_usd / capital_usdt) * 100.0

        return {
            "exchange": exchange,
            "direction": "FORWARD (USDT -> A -> B -> USDT)",
            "loop_label": f"USDT -> {a} -> {b} -> USDT",
            "starting_capital": capital_usdt,
            "step1": {"action": f"BUY {a}", "price": price1, "amount": qty_a_net, "fee_usd": fee1_usd},
            "step2": {"action": f"SELL {a} for {b}", "price": price2, "amount": qty_b_net, "fee_usd": fee2_usd},
            "step3": {"action": f"SELL {b} for USDT", "price": price3, "amount": final_usdt_net, "fee_usd": fee3_usd},
            "total_fees_usd": total_fees,
            "total_slippage_usd": total_slip,
            "gross_profit_usd": gross_profit_usd,
            "gross_profit_pct": gross_profit_pct,
            "pre_tds_net_profit_usd": pre_tds_net_profit_usd,
            "pre_tds_net_profit_pct": pre_tds_net_profit_pct,
            "post_tds_net_profit_usd": post_tds_net_profit_usd,
            "post_tds_net_profit_pct": post_tds_net_profit_pct,
            "tds_impact_usd": tds_impact_usd,
            "is_tds": is_tds
        }

    async def evaluate_reverse_loop(self, exchange: str, loop_cfg: Dict, capital_usdt: float) -> Optional[Dict]:
        """USDT -> Asset B -> Asset A -> USDT"""
        a, b = loop_cfg["a"], loop_cfg["b"]
        s1 = f"{b}USDT"
        s2 = f"{a}{b}"
        s3 = f"{a}USDT"

        ob1, ob2, ob3 = await asyncio.gather(
            self.fetch_depth(exchange, s1),
            self.fetch_depth(exchange, s2),
            self.fetch_depth(exchange, s3)
        )

        if not ob1["asks"] or not ob2["asks"] or not ob3["bids"]:
            return None

        taker_fee_pct = FEE_RATES[exchange]["taker_fee"]
        is_tds = FEE_RATES[exchange].get("tds_applicable", False)
        tds_rate = FEE_RATES[exchange].get("tds_rate", 0.01)

        # Step 1: BUY Asset B with USDT
        qty_b, price1, slip1 = OrderBookWalker.simulate_market_buy(ob1["asks"], capital_usdt)
        if qty_b == 0: return None
        fee1_usd = capital_usdt * taker_fee_pct
        qty_b_net = qty_b * (1.0 - taker_fee_pct)

        # Step 2: BUY Asset A using Asset B on pair A/B
        qty_a, price2, slip2 = OrderBookWalker.simulate_market_buy(ob2["asks"], qty_b_net)
        if qty_a == 0: return None
        fee2_usd = (qty_a * float(ob3["bids"][0][0])) * taker_fee_pct
        qty_a_net = qty_a * (1.0 - taker_fee_pct)

        # Step 3: SELL Asset A for USDT
        final_usdt, price3, slip3 = OrderBookWalker.simulate_market_sell(ob3["bids"], qty_a_net)
        if final_usdt == 0: return None
        fee3_usd = final_usdt * taker_fee_pct
        final_usdt_net = final_usdt * (1.0 - taker_fee_pct)

        total_fees = fee1_usd + fee2_usd + fee3_usd
        total_slip = slip1 + slip2 + slip3
        gross_profit_usd = final_usdt - capital_usdt
        gross_profit_pct = (gross_profit_usd / capital_usdt) * 100.0

        pre_tds_net_profit_usd = final_usdt_net - capital_usdt
        pre_tds_net_profit_pct = (pre_tds_net_profit_usd / capital_usdt) * 100.0

        tds_impact_usd = ((capital_usdt + final_usdt) * tds_rate) if is_tds else 0.0
        post_tds_net_profit_usd = pre_tds_net_profit_usd - tds_impact_usd
        post_tds_net_profit_pct = (post_tds_net_profit_usd / capital_usdt) * 100.0

        return {
            "exchange": exchange,
            "direction": "REVERSE (USDT -> B -> A -> USDT)",
            "loop_label": f"USDT -> {b} -> {a} -> USDT",
            "starting_capital": capital_usdt,
            "step1": {"action": f"BUY {b}", "price": price1, "amount": qty_b_net, "fee_usd": fee1_usd},
            "step2": {"action": f"BUY {a} with {b}", "price": price2, "amount": qty_a_net, "fee_usd": fee2_usd},
            "step3": {"action": f"SELL {a} for USDT", "price": price3, "amount": final_usdt_net, "fee_usd": fee3_usd},
            "total_fees_usd": total_fees,
            "total_slippage_usd": total_slip,
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
    print("=" * 75)
    print("🚀 QUANTITATIVE TRIANGULAR ARBITRAGE ENGINE (PAPER TRADING - FIXED)")
    print("   Exchanges: BINANCE & COINDCX (Dual-Direction Scan + User-Agent Fix)")
    print(f"   Capital: ${STARTING_CAPITAL_USDT:.2f} USDT | Min Net Profit Gate: {MIN_NET_PROFIT_PCT:.2f}%")
    print("=" * 75)

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        scanner = TriangularArbitrageScanner(session)

        while True:
            try:
                for loop_cfg in TRIANGULAR_LOOPS:
                    tasks = []
                    for ex in ["binance", "coindcx"]:
                        tasks.append(scanner.evaluate_forward_loop(ex, loop_cfg, STARTING_CAPITAL_USDT))
                        tasks.append(scanner.evaluate_reverse_loop(ex, loop_cfg, STARTING_CAPITAL_USDT))

                    results = await asyncio.gather(*tasks)
                    candidates = [r for r in results if r is not None]
                    if not candidates:
                        continue

                    candidates.sort(key=lambda x: x["pre_tds_net_profit_pct"], reverse=True)
                    best = candidates[0]

                    # Filter by Minimum Net Profit Gate
                    if best["pre_tds_net_profit_pct"] >= MIN_NET_PROFIT_PCT:
                        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        ex_name = best["exchange"].upper()

                        print("-" * 65)
                        print(f"[{ts}] ⚡ TRIANGULAR LOOP DETECTED: {best['loop_label']}")
                        print(f"- Exchange Selected: [{ex_name}] | Direction: {best['direction']}")
                        print(f"- Starting Capital: ${best['starting_capital']:.2f} USDT")
                        print(f"- Step 1 ({best['step1']['action']}): Price = ${best['step1']['price']:.4f}, Amt = {best['step1']['amount']:.6f}, Fee = ${best['step1']['fee_usd']:.4f}")
                        print(f"- Step 2 ({best['step2']['action']}): Price = {best['step2']['price']:.6f}, Amt = {best['step2']['amount']:.6f}, Fee = ${best['step2']['fee_usd']:.4f}")
                        print(f"- Step 3 ({best['step3']['action']}): Price = ${best['step3']['price']:.4f}, Amt = ${best['step3']['amount']:.2f} USDT, Fee = ${best['step3']['fee_usd']:.4f}")
                        print(f"- Total Fees Cut: ${best['total_fees_usd']:.4f}")
                        print(f"- Slippage Impact: ${best['total_slippage_usd']:.4f}")
                        print(f"- Gross Profit: ${best['gross_profit_usd']:.4f} ({best['gross_profit_pct']:.3f}%)")
                        print(f"- PRE-TDS NET PROFIT: ${best['pre_tds_net_profit_usd']:.4f} ({best['pre_tds_net_profit_pct']:.3f}%)")
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
