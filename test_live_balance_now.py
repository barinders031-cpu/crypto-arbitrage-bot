import sys
import asyncio
import datetime

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from live_order_executor import LiveOrderExecutor

async def main():
    executor = LiveOrderExecutor()
    await executor._ensure_session()

    print("=" * 80)
    print(" 🚀 LIVE REAL-TIME UN-CACHED BALANCE STREAM AUDIT")
    print("=" * 80)

    for i in range(1, 4):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        d_bal, c_bal, min_margin = await executor.fetch_live_balances()
        print(f"[{ts}] Loop #{i}: Delta=${d_bal:.4f} | CoinDCX=${c_bal:.4f} | Weaker Margin(75%)=${min_margin:.4f}")
        await asyncio.sleep(1.0)

    print("=" * 80)
    await executor.close()

if __name__ == "__main__":
    asyncio.run(main())
