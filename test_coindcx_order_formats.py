import sys
import asyncio
import json
import aiohttp

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from live_order_executor import (
    sign_coindcx,
    COINDCX_BASE_URL,
    COINDCX_API_KEY,
    COINDCX_API_SECRET
)

async def test_order_format(session, payload):
    body_str, sig = sign_coindcx(payload)
    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": COINDCX_API_KEY,
        "X-AUTH-SIGNATURE": sig
    }
    url = COINDCX_BASE_URL + "/exchange/v1/derivatives/futures/orders/create"
    async with session.post(url, data=body_str, headers=headers) as resp:
        txt = await resp.text()
        print(f"Payload: {json.dumps(payload)}")
        print(f"Response: HTTP {resp.status} | Body: {txt}")

async def main():
    async with aiohttp.ClientSession() as session:
        payloads = [
            {"pair": "B-BANK_USDT", "side": "buy", "order_type": "limit_order", "price": 0.03, "total_quantity": 1000.0, "leverage": 10},
            {"pair": "B-BANK_USDT", "side": "buy", "order_type": "limit_order", "price": "0.03", "total_quantity": 1000, "leverage": 10},
            {"pair": "B-BANK_USDT", "side": "buy", "order_type": "limit_order", "price": 0.03, "total_quantity": 1000, "leverage": 10, "position_intent": "order_default"},
        ]
        for p in payloads:
            await test_order_format(session, p)

if __name__ == "__main__":
    asyncio.run(main())
