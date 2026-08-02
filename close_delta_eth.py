import asyncio
from live_order_executor import LiveOrderExecutor

async def main():
    executor = LiveOrderExecutor()
    await executor._ensure_session()
    res = await executor._delta_order("ETHUSD", "buy", 1, order_type="market_order", reduce_only=True)
    print("DELTA CLOSE RESULT:", res)
    await executor.close()

if __name__ == "__main__":
    asyncio.run(main())
