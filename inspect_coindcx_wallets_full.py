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

async def main():
    async with aiohttp.ClientSession() as session:
        # 1. Check /exchange/v1/users/balances (Spot balances)
        path1 = "/exchange/v1/users/balances"
        body1, sig1 = sign_coindcx({})
        headers1 = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig1}
        async with session.post(COINDCX_BASE_URL + path1, data=body1, headers=headers1) as r1:
            data1 = await r1.json()
            print("=== COINDCX SPOT USER BALANCES ===")
            if isinstance(data1, list):
                non_zero = [i for i in data1 if float(i.get('balance', 0)) > 0 or float(i.get('locked_balance', 0)) > 0]
                print(json.dumps(non_zero, indent=2))
            else:
                print(json.dumps(data1, indent=2))

        # 2. Check /exchange/v1/derivatives/futures/positions
        path2 = "/exchange/v1/derivatives/futures/positions"
        body2, sig2 = sign_coindcx({})
        headers2 = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig2}
        async with session.post(COINDCX_BASE_URL + path2, data=body2, headers=headers2) as r2:
            data2 = await r2.json()
            print("\n=== COINDCX FUTURES POSITIONS ===")
            if isinstance(data2, list):
                active = [p for p in data2 if float(p.get('active_pos', 0)) != 0 or float(p.get('locked_user_margin', 0)) > 0]
                print(f"Active positions count: {len(active)}")
                print(json.dumps(active, indent=2))
            else:
                print(json.dumps(data2, indent=2))

        # 3. Check optional wallet/futures balance endpoints
        futures_balance_paths = [
            "/exchange/v1/derivatives/futures/balances",
            "/exchange/v1/derivatives/futures/user/balances",
            "/exchange/v1/users/info",
        ]
        for path3 in futures_balance_paths:
            body3, sig3 = sign_coindcx({})
            headers3 = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig3}
            try:
                async with session.post(COINDCX_BASE_URL + path3, data=body3, headers=headers3) as r3:
                    res3 = await r3.json()
                    print(f"\n=== COINDCX {path3} ===")
                    print(json.dumps(res3, indent=2)[:500])
            except Exception as e:
                print(f"\nPath {path3} error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
