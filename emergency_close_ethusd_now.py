import asyncio
import json
import time
import hmac
import hashlib
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from live_order_executor import (
    LiveOrderExecutor,
    sign_delta,
    DELTA_BASE_URL,
    DELTA_API_KEY,
    DELTA_API_SECRET
)

async def close_eth_now():
    print("=" * 80)
    print(" EMERGENCY CLOSING ETHUSD POSITION ON DELTA EXCHANGE INDIA NOW")
    print("=" * 80)

    executor = LiveOrderExecutor()
    await executor._ensure_session()

    # 1. Fire Buy Market Order to close SHORT -0.01 ETH (1 Lot)
    res = await executor._delta_order("ETHUSD", "buy", 1, order_type="market_order", reduce_only=True)
    print("CLOSE ORDER RESULT:", json.dumps(res, indent=2))

    # 2. Re-check Delta Positions API
    await asyncio.sleep(1.0)
    pos_res = await executor._delta_get("/v2/positions")
    print("POST-CLOSE DELTA POSITIONS:", json.dumps(pos_res, indent=2))

    await executor.close()

if __name__ == "__main__":
    asyncio.run(close_eth_now())
