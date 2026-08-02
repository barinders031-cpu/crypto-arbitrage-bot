import sys
import asyncio
import json
import time
import hmac
import hashlib
import aiohttp

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from live_order_executor import (
    sign_delta,
    sign_coindcx,
    DELTA_BASE_URL,
    DELTA_API_KEY,
    DELTA_API_SECRET,
    COINDCX_BASE_URL,
    COINDCX_API_KEY,
    COINDCX_API_SECRET
)

async def test_delta_balance():
    print("=" * 80)
    print(" 1. FETCHING DELTA EXCHANGE INDIA LIVE BALANCES")
    print("=" * 80)
    async with aiohttp.ClientSession() as session:
        t_stamp, sig = sign_delta("GET", "/v2/wallet/balances", "")
        headers = {
            "api-key": DELTA_API_KEY,
            "timestamp": t_stamp,
            "signature": sig,
            "User-Agent": "Mozilla/5.0"
        }
        async with session.get(DELTA_BASE_URL + "/v2/wallet/balances", headers=headers) as resp:
            data = await resp.json()
            print("HTTP Status:", resp.status)
            print("Raw Response:", json.dumps(data, indent=2))
            
            usd_bal = None
            for item in data.get("result", []):
                if item.get("asset_symbol") in ("USD", "USDT"):
                    print(f"-> Asset: {item.get('asset_symbol')} | Balance: {item.get('balance')} | Available: {item.get('available_balance')}")
                    if item.get("asset_symbol") == "USD":
                        usd_bal = float(item.get("balance") or 0)
            return usd_bal

async def test_coindcx_balance():
    print("\n" + "=" * 80)
    print(" 2. FETCHING COINDCX LIVE BALANCES & POSITIONS")
    print("=" * 80)
    async with aiohttp.ClientSession() as session:
        # User Balances
        path1 = "/exchange/v1/users/balances"
        body1, sig1 = sign_coindcx({})
        headers1 = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig1}
        async with session.post(COINDCX_BASE_URL + path1, data=body1, headers=headers1) as resp1:
            data1 = await resp1.json()
            print("Spot Balances HTTP Status:", resp1.status)
            usdt_item = None
            if isinstance(data1, list):
                for item in data1:
                    bal = float(item.get("balance") or 0)
                    locked = float(item.get("locked_balance") or 0)
                    if bal > 0 or locked > 0:
                        print(f"-> Asset: {item.get('currency')} | Balance: {bal} | Locked: {locked}")
                    if item.get("currency") == "USDT":
                        usdt_item = item

        # Futures Positions
        path2 = "/exchange/v1/derivatives/futures/positions"
        body2, sig2 = sign_coindcx({})
        headers2 = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig2}
        async with session.post(COINDCX_BASE_URL + path2, data=body2, headers=headers2) as resp2:
            data2 = await resp2.json()
            print("\nFutures Positions HTTP Status:", resp2.status)
            locked_margin = 0.0
            if isinstance(data2, list):
                for p in data2:
                    lm = float(p.get("locked_user_margin") or 0)
                    if lm > 0:
                        locked_margin += lm
                        print(f"-> Pair: {p.get('pair')} | ActivePos: {p.get('active_pos')} | LockedMargin: {lm}")

            print(f"\nCoinDCX Total Capital Calculation:")
            spot_usdt = float(usdt_item.get("balance") or 0) if usdt_item else 0.0
            total_usdt = spot_usdt + locked_margin
            print(f"   Spot USDT Balance : ${spot_usdt:.4f}")
            print(f"   Futures Locked    : ${locked_margin:.4f}")
            print(f"   TOTAL FUTURES USDT: ${total_usdt:.4f}")
            return total_usdt

async def main():
    d_bal = await test_delta_balance()
    c_bal = await test_coindcx_balance()
    print("\n" + "=" * 80)
    print(" 📊 SUMMARY LIVE BALANCE FETCH:")
    print(f"    Delta Live Balance   : ${d_bal if d_bal is not None else 0.0:.4f} USD")
    print(f"    CoinDCX Live Balance : ${c_bal if c_bal is not None else 0.0:.4f} USDT")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
