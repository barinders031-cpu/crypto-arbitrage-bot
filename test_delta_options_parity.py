"""
Test Script for Delta Exchange India Options Put-Call Parity Scanner
====================================================================
Scans live BTC, ETH, and XAUT Options and Futures on Delta Exchange India.
Prints all matched Call/Put/Futures Put-Call Parity spreads.
"""
import sys
import asyncio
import json
import datetime

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from live_order_executor import LiveOrderExecutor
from delta_options_parity_engine import DeltaOptionsParityEngine

async def main():
    print("=" * 90)
    print(" 🚀 DELTA EXCHANGE INDIA OPTIONS PUT-CALL PARITY LIVE SCANNER (BTC, ETH, XAUT)")
    print("=" * 90)

    executor = LiveOrderExecutor()
    engine = DeltaOptionsParityEngine(executor)

    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Fetching live products & tickers from Delta Exchange India...")
    products, ticker_map = await engine.fetch_delta_products_and_tickers()
    print(f"   Total Products : {len(products)}")
    print(f"   Total Tickers  : {len(ticker_map)}")
    print("-" * 90)

    opps = engine.scan_parity_opportunities(products, ticker_map)

    if opps:
        print(f"✅ FOUND {len(opps)} LIVE PUT-CALL PARITY OPPORTUNITIES:")
        for idx, o in enumerate(opps[:10], 1):
            print(f"\n#{idx} [{o['coin']}] {o['type']} ARBITRAGE ({o['action']})")
            print(f"   Strike Price     : ${o['strike']:.2f}")
            print(f"   Futures Price    : ${o['futures_mark']:.2f}")
            print(f"   Call Ask / Put Bid: Call Ask=${o['call_ask']:.4f} | Put Bid=${o['put_bid']:.4f}")
            print(f"   Gross Spread     : {o['gross_spread_pct']:+.4f}%")
            print(f"   Net PnL (Fee-Ded): +{o['net_pnl_pct']:.4f}%")
            print(f"   Hours to Expiry  : {o['hours_to_exp']:.2f} Hours")
    else:
        print("ℹ️ No Put-Call Parity opportunities exceeding Net Fee Gate (+0.15%) found in current scan cycle.")
        print("   Scanner will continue background polling every scan loop.")

    print("=" * 90)

if __name__ == "__main__":
    asyncio.run(main())
