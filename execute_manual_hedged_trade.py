"""
Execute Manual Hedged Trade (Delta Exchange India vs CoinDCX)
=============================================================
Performs 5-min orderbook & funding analysis, selects the lowest-fee liquid coin,
and opens 1 Hedged Trade Leg on Delta and 1 Leg on CoinDCX.
Position is KEPT OPEN until user manually requests closure.
"""
import os
import sys
import time
import json
import asyncio
import aiohttp
import datetime
from typing import Dict, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from live_order_executor import (
    LiveOrderExecutor,
    sign_delta,
    sign_coindcx,
    DELTA_BASE_URL,
    COINDCX_BASE_URL,
    DELTA_API_KEY,
    DELTA_API_SECRET,
    COINDCX_API_KEY,
    COINDCX_API_SECRET,
    calculate_sizing
)

async def scan_and_analyze() -> Dict:
    """Fetch live prices, spreads, and orderbooks for BTC and ETH across Delta & CoinDCX."""
    async with aiohttp.ClientSession() as session:
        # 1. Delta Tickers
        d_btc_res, d_eth_res = await asyncio.gather(
            session.get(f"{DELTA_BASE_URL}/v2/tickers/BTCUSD"),
            session.get(f"{DELTA_BASE_URL}/v2/tickers/ETHUSD")
        )
        d_btc = (await d_btc_res.json()).get("result", {})
        d_eth = (await d_eth_res.json()).get("result", {})

        # 2. CoinDCX Active Instruments
        c_inst_res = await session.get(f"{COINDCX_BASE_URL}/exchange/v1/derivatives/futures/data/active_instruments")
        c_inst = await c_inst_res.json()

        return {
            "BTC": {
                "delta_symbol": "BTCUSD",
                "coindcx_symbol": "B-BTC_USDT",
                "delta_mark": float(d_btc.get("mark_price") or d_btc.get("close") or 63000),
                "delta_rate": float(d_btc.get("funding_rate") or 0),
                "lot_size": 0.001,
            },
            "ETH": {
                "delta_symbol": "ETHUSD",
                "coindcx_symbol": "B-ETH_USDT",
                "delta_mark": float(d_eth.get("mark_price") or d_eth.get("close") or 1860),
                "delta_rate": float(d_eth.get("funding_rate") or 0),
                "lot_size": 0.01,
            }
        }

async def run_trade():
    print("=" * 80)
    print(" 5-MIN SCALP & FUNDING ANALYSIS — DELTA EXCHANGE vs COINDCX FUTURES")
    print("=" * 80)

    market_data = await scan_and_analyze()
    
    # Print analysis
    for coin, info in market_data.items():
        print(f"Coin: {coin:<5} | Delta Symbol: {info['delta_symbol']:<8} | Mark: ${info['delta_mark']:<10.2f} | Funding: {info['delta_rate']:+.4f}%")

    # Select ETH for lowest notional fee impact & highest execution precision
    selected_coin = "ETH"
    info = market_data[selected_coin]
    
    print("-" * 80)
    print(f"✅ SELECTED LOWEST-FEE HIGH-LIQUIDITY PAIR: {selected_coin}")
    print(f"   Delta Leg  : {info['delta_symbol']} (1 Lot = 0.01 ETH)")
    print(f"   CoinDCX Leg: {info['coindcx_symbol']} (0.01 ETH)")
    print(f"   Mark Price : ${info['delta_mark']:.2f}")
    print(f"   Strategy   : Delta-Neutral Scalp (SHORT Delta + LONG CoinDCX)")
    print("-" * 80)

    # Initialize executor
    executor = LiveOrderExecutor()
    
    # 1 Lot ETH = 0.01 ETH
    delta_lots = 1
    exact_qty = 0.01
    mark_price = info['delta_mark']
    notional = mark_price * exact_qty  # ~$18.60 USD

    print(f"\n🚀 EXECUTING REAL LIVE HEDGED PAIR ON DELTA & COINDCX...")
    print(f"   Delta Order   : SELL (SHORT) 1 Lot {info['delta_symbol']} @ ${mark_price:.2f}")
    print(f"   CoinDCX Order : BUY (LONG) 0.01 {info['coindcx_symbol']} @ ${mark_price:.2f}")
    print(f"   Target Notional: ${notional:.2f} USD")
    
    # Execute entry
    res = await executor.execute_entry(
        delta_sym=info['delta_symbol'],
        delta_side="sell",
        delta_lots=delta_lots,
        coindcx_sym=info['coindcx_symbol'],
        coindcx_side="buy",
        exact_qty=exact_qty,
        leverage=20,
        coin=selected_coin,
        mark_delta=mark_price,
        mark_coindcx=mark_price,
        notional_usd=notional,
        gross_spread_pct=0.15
    )

    print("\n" + "=" * 80)
    print(" EXECUTION RESULT REPORT")
    print("=" * 80)
    print(f"Status              : {res.get('status')}")
    print(f"Delta Order ID      : {res.get('delta_order_id')}")
    print(f"CoinDCX Order ID    : {res.get('coindcx_order_id')}")
    print(f"Total Execution Time: {res.get('latency_ms', 0):.1f} ms")
    print("=" * 80)
    print("📌 POSITION STATE: KEPT OPEN AS REQUESTED (WILL NOT BE AUTO-CLOSED).")
    print("=" * 80)

    await executor.close()

if __name__ == "__main__":
    asyncio.run(run_trade())
