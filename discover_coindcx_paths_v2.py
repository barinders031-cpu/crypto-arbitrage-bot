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

async def test_endpoint(session, path, payload=None):
    if payload is None:
        payload = {}
    body_str, sig = sign_coindcx(payload)
    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": COINDCX_API_KEY,
        "X-AUTH-SIGNATURE": sig
    }
    url = COINDCX_BASE_URL + path
    try:
        async with session.post(url, data=body_str, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            data = await resp.json()
            if resp.status != 404:
                print(f"✅ FOUND PATH: {path} (HTTP {resp.status})")
                print(json.dumps(data, indent=2)[:1000])
            else:
                print(f"❌ 404: {path}")
            return resp.status, data
    except Exception as e:
        print(f"⚠️ ERROR: {path} -> {e}")
        return 500, None

async def main():
    async with aiohttp.ClientSession() as session:
        paths = [
            "/exchange/v1/derivatives/futures/user/trade_info",
            "/exchange/v1/derivatives/futures/balances",
            "/exchange/v1/margin/user_info",
            "/exchange/v1/margin/balances",
            "/exchange/v1/wallets",
            "/exchange/v1/user/wallets",
            "/exchange/v1/derivatives/futures/user_details",
            "/exchange/v1/derivatives/futures/user/positions",
            "/exchange/v1/derivatives/futures/positions",
            "/exchange/v1/derivatives/futures/orders/active_orders",
            "/exchange/v1/derivatives/futures/orders/trade_history",
        ]
        for p in paths:
            await test_endpoint(session, p)

if __name__ == "__main__":
    asyncio.run(main())
