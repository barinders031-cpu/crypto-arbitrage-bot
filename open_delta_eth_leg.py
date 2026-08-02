import asyncio
from live_order_executor import LiveOrderExecutor

async def main():
    executor = LiveOrderExecutor()
    await executor._ensure_session()
    res = await executor._delta_order("ETHUSD", "sell", 2, order_type="market_order")
    print("DELTA SHORT LEG RESULT:", res)
    await executor.close()

if __name__ == "__main__":
    asyncio.run(main())
