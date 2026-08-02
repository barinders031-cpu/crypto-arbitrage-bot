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
        path1 = "/exchange/v1/users/balances"
        body1, sig1 = sign_coindcx({})
        headers1 = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig1}
        async with session.post(COINDCX_BASE_URL + path1, data=body1, headers=headers1) as resp:
            data = await resp.json()
            
            spot_usdt = 0.0
            spot_inr = 0.0
            if isinstance(data, list):
                for item in data:
                    c = item.get("currency")
                    b = float(item.get("balance") or 0)
                    l = float(item.get("locked_balance") or 0)
                    if c == "USDT":
                        spot_usdt = b
                    elif c == "INR":
                        spot_inr = b
                    if b > 0 or l > 0:
                        print(f"  {c:<8}: Balance = {b:.6f} | Locked = {l:.6f}")

            print("\n" + "=" * 60)
            print(" 📊 COINDCX LIVE USER BALANCES:")
            print(f"    Spot Wallet USDT Balance : ${spot_usdt:.4f} USDT")
            print(f"    Spot Wallet INR Balance  : ₹{spot_inr:.2f} INR")
            print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
