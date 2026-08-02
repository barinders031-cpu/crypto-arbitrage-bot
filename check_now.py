import asyncio
from live_order_executor import get_executor

async def main():
    ex = get_executor()
    d_bal, c_bal, min_m = await ex.fetch_live_balances()
    print("\n" + "="*60)
    print(f"LIVE BALANCES FROM EXECUTOR:")
    print(f"  Delta Exchange Balance:  ${d_bal:.4f} USD")
    print(f"  CoinDCX Exchange Balance: ${c_bal:.4f} USDT")
    print(f"  Minimum Effective Margin: ${min_m:.4f} USD (75%)")
    print("="*60)

asyncio.run(main())
