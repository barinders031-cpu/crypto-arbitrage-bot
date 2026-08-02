import asyncio
import json
from live_order_executor import LiveOrderExecutor

async def main():
    executor = LiveOrderExecutor()
    await executor._ensure_session()
    
    # Correct Delta endpoint for all positions
    pos_res = await executor._delta_get("/v2/positions/margined")
    print("DELTA MARGINED POSITIONS:", json.dumps(pos_res, indent=2))
    
    await executor.close()

if __name__ == "__main__":
    asyncio.run(main())
