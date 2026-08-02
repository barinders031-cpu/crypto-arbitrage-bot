import sys
import asyncio

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from live_order_executor import LiveOrderExecutor

async def main():
    executor = LiveOrderExecutor()
    await executor._ensure_session()
    d_bal, c_bal, min_margin = await executor.fetch_live_balances()
    print("=" * 60)
    print(" ✅ RESTORED BALANCES AUDIT:")
    print(f"    Delta Balance   : ${d_bal:.2f} USD")
    print(f"    CoinDCX Balance : ${c_bal:.2f} USDT")
    print(f"    Safe Margin(75%): ${min_margin:.2f} USD")
    print("=" * 60)
    await executor.close()

if __name__ == "__main__":
    asyncio.run(main())
