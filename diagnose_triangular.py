"""
Updated Diagnostic Script for Triangular Arbitrage Engine
Features:
1. User-Agent headers to prevent CoinDCX 403 Forbidden.
2. Pair symbol mapping for CoinDCX (e.g. B-ETH_USDT, B-ETH_BTC).
3. Evaluates both Forward (USDT -> A -> B -> USDT) and Reverse (USDT -> B -> A -> USDT) loops.
"""
import asyncio
import aiohttp
import json
import sys
from typing import Dict, List, Tuple, Optional

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

STARTING_CAPITAL_USDT = 100.0
MIN_NET_PROFIT_PCT    = 0.15

FEE_RATES = {
    "binance": {
        "taker_fee": 0.0010,     # 0.10%
        "taker_fee_bnb": 0.00075, # 0.075%
        "tds_applicable": False
    },
    "coindcx": {
        "taker_fee": 0.0020,     # 0.20%
        "tds_applicable": True,
        "tds_rate": 0.0100       # 1.0% TDS
    }
}

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
]

class OrderBookWalker:
    @staticmethod
    def simulate_market_buy(order_book_asks: List[List[float]], required_quote_amount: float) -> Tuple[float, float, float]:
        remaining_quote = required_quote_amount
        total_base_bought = 0.0
        weighted_cost = 0.0

        if not order_book_asks:
            return 0.0, 0.0, 0.0

        top_price = float(order_book_asks[0][0])

        for price_str, qty_str in order_book_asks[:10]:
            price = float(price_str)
            qty = float(qty_str)
            level_val = price * qty

            if remaining_quote <= level_val:
                qty_from_level = remaining_quote / price
                total_base_bought += qty_from_level
                weighted_cost += remaining_quote
                remaining_quote = 0.0
                break
            else:
                total_base_bought += qty
                weighted_cost += level_val
                remaining_quote -= level_val

        if total_base_bought == 0:
            return 0.0, 0.0, 0.0

        vwap_price = weighted_cost / total_base_bought
        ideal_cost = total_base_bought * top_price
        slippage_usd = max(0.0, weighted_cost - ideal_cost)

        return total_base_bought, vwap_price, slippage_usd

    @staticmethod
    def simulate_market_sell(order_book_bids: List[List[float]], base_amount_to_sell: float) -> Tuple[float, float, float]:
        remaining_base = base_amount_to_sell
        total_quote_received = 0.0

        if not order_book_bids:
            return 0.0, 0.0, 0.0

        top_price = float(order_book_bids[0][0])

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
        ideal_quote = base_amount_to_sell * top_price
        slippage_usd = max(0.0, ideal_quote - total_quote_received)

        return total_quote_received, vwap_price, slippage_usd


class TriangularArbitrageScanner:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    def format_symbol(self, exchange: str, raw_symbol: str) -> str:
        """Formats raw symbol e.g. ETHUSDT or ETHBTC for target exchange."""
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
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        if exchange == "binance":
            url = f"https://api.binance.com/api/v3/depth?symbol={formatted_sym}&limit=10"
            try:
                async with self.session.get(url, headers=headers, timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.json()
            except Exception:
                pass
        elif exchange == "coindcx":
            url = f"https://public.coindcx.com/market_data/orderbook?pair={formatted_sym}"
            try:
                async with self.session.get(url, headers=headers, timeout=5) as resp:
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

    async def evaluate_forward_loop(self, exchange: str, loop_cfg: Dict, capital: float) -> Optional[Dict]:
        """USDT -> A -> B -> USDT"""
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

        fee_pct = FEE_RATES[exchange]["taker_fee"]
        qty_a, p1, slip1 = OrderBookWalker.simulate_market_buy(ob1["asks"], capital)
        if qty_a == 0: return None
        qty_a_net = qty_a * (1.0 - fee_pct)

        qty_b, p2, slip2 = OrderBookWalker.simulate_market_sell(ob2["bids"], qty_a_net)
        if qty_b == 0: return None
        qty_b_net = qty_b * (1.0 - fee_pct)

        final_usdt, p3, slip3 = OrderBookWalker.simulate_market_sell(ob3["bids"], qty_b_net)
        if final_usdt == 0: return None
        final_usdt_net = final_usdt * (1.0 - fee_pct)

        gross_usd = final_usdt - capital
        net_usd = final_usdt_net - capital
        gross_pct = (gross_usd / capital) * 100.0
        net_pct = (net_usd / capital) * 100.0

        return {
            "exchange": exchange,
            "direction": "FORWARD (USDT->A->B->USDT)",
            "label": f"USDT -> {a} -> {b} -> USDT",
            "gross_pct": gross_pct,
            "net_pct": net_pct,
            "final_usdt": final_usdt_net
        }

    async def evaluate_reverse_loop(self, exchange: str, loop_cfg: Dict, capital: float) -> Optional[Dict]:
        """USDT -> B -> A -> USDT"""
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

        fee_pct = FEE_RATES[exchange]["taker_fee"]

        qty_b, p1, slip1 = OrderBookWalker.simulate_market_buy(ob1["asks"], capital)
        if qty_b == 0: return None
        qty_b_net = qty_b * (1.0 - fee_pct)

        qty_a, p2, slip2 = OrderBookWalker.simulate_market_buy(ob2["asks"], qty_b_net)
        if qty_a == 0: return None
        qty_a_net = qty_a * (1.0 - fee_pct)

        final_usdt, p3, slip3 = OrderBookWalker.simulate_market_sell(ob3["bids"], qty_a_net)
        if final_usdt == 0: return None
        final_usdt_net = final_usdt * (1.0 - fee_pct)

        gross_usd = final_usdt - capital
        net_usd = final_usdt_net - capital
        gross_pct = (gross_usd / capital) * 100.0
        net_pct = (net_usd / capital) * 100.0

        return {
            "exchange": exchange,
            "direction": "REVERSE (USDT->B->A->USDT)",
            "label": f"USDT -> {b} -> {a} -> USDT",
            "gross_pct": gross_pct,
            "net_pct": net_pct,
            "final_usdt": final_usdt_net
        }


async def main():
    print("=" * 85)
    print("FIXED TRIANGULAR ARBITRAGE DIAGNOSTIC SCANNER")
    print("Exchanges: BINANCE & COINDCX (User-Agent + Symbol Format B-xxx_yyy)")
    print("=" * 85)

    async with aiohttp.ClientSession() as session:
        scanner = TriangularArbitrageScanner(session)
        
        results = []
        for loop in TRIANGULAR_LOOPS:
            for ex in ["binance", "coindcx"]:
                fwd = await scanner.evaluate_forward_loop(ex, loop, STARTING_CAPITAL_USDT)
                rev = await scanner.evaluate_reverse_loop(ex, loop, STARTING_CAPITAL_USDT)
                if fwd: results.append(fwd)
                if rev: results.append(rev)

        print("\n" + "=" * 90)
        print(f"{'EXCHANGE':<10} | {'DIRECTION':<27} | {'LOOP LABEL':<28} | {'GROSS %':<9} | {'NET PROFIT %'}")
        print("=" * 90)

        for r in results:
            status = "ACCEPT" if r["net_pct"] >= MIN_NET_PROFIT_PCT else "REJECT"
            print(f"{r['exchange'].upper():<10} | {r['direction']:<27} | {r['label']:<28} | {r['gross_pct']:>8.3f}% | {r['net_pct']:>11.3f}%  [{status}]")

        print("=" * 90)

if __name__ == "__main__":
    asyncio.run(main())
