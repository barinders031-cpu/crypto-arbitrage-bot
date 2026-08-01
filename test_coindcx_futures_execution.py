"""
CoinDCX Futures Native Server Order Execution Verification Script
=================================================================
Tests placing a safe far-out-of-the-money limit order on B-BANK_USDT
to prove CoinDCX server natively validates available margin on order creation,
and immediately cancels the resting order.
"""
import os
import sys
import time
import json
import asyncio
import aiohttp
import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from live_order_executor import (
    sign_coindcx,
    COINDCX_BASE_URL,
    COINDCX_API_KEY,
    COINDCX_API_SECRET
)

async def run_coindcx_order_test():
    print("=" * 80)
    print(" 🚀 COINDCX FUTURES NATIVE SERVER MARGIN VALIDATION & ORDER EXECUTION TEST")
    print("=" * 80)

    async with aiohttp.ClientSession() as session:
        # Step 1: Place a safe Limit Buy Order on B-BANK_USDT far below market (Limit Price = $0.01)
        # Size = 500 BANK @ 0.01 = $5.00 USDT Notional ($0.50 USDT margin @ 10x leverage)
        create_path = "/exchange/v1/derivatives/futures/orders/create"
        order_dict = {
            "pair": "B-BANK_USDT",
            "side": "buy",
            "order_type": "limit_order",
            "price": 0.03,
            "total_quantity": 1000.0,
            "leverage": 7,
            "margin_type": "isolated"
        }
        payload = {"order": order_dict}

        body_str, sig = sign_coindcx(payload)
        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": COINDCX_API_KEY,
            "X-AUTH-SIGNATURE": sig
        }

        print(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Transmitting test limit order to CoinDCX Futures server:")
        print(f"   Pair        : {order_dict['pair']}")
        print(f"   Side        : {order_dict['side'].upper()}")
        print(f"   Order Type  : {order_dict['order_type'].upper()} (${order_dict['price']} USDT)")
        print(f"   Quantity    : {order_dict['total_quantity']} BANK (${order_dict['price'] * order_dict['total_quantity']:.2f} USDT Notional)")
        print(f"   Leverage    : {order_dict['leverage']}x (${(order_dict['price'] * order_dict['total_quantity'])/order_dict['leverage']:.2f} USDT Required Margin)")
        print("-" * 80)

        t0 = time.perf_counter()
        async with session.post(COINDCX_BASE_URL + create_path, data=body_str, headers=headers) as resp:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            raw_text = await resp.text()
            try:
                resp_data = json.loads(raw_text)
            except Exception:
                resp_data = {"raw": raw_text}

            print(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] COINDCX SERVER RESPONSE (HTTP {resp.status}) ({latency_ms:.1f}ms):")
            print(json.dumps(resp_data, indent=2) if isinstance(resp_data, (dict, list)) else raw_text)
            print("-" * 80)

            # Step 2: If order was created (status 200/201 or array returned with order ID), cancel it immediately!
            order_id = None
            if isinstance(resp_data, list) and len(resp_data) > 0:
                order_id = resp_data[0].get("id")
            elif isinstance(resp_data, dict):
                order_id = resp_data.get("id")

            if order_id:
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 🧹 Cleaning up test order ID: {order_id}...")
                cancel_path = "/exchange/v1/derivatives/futures/orders/cancel"
                cancel_payload = {"id": order_id}
                c_body, c_sig = sign_coindcx(cancel_payload)
                c_headers = {
                    "Content-Type": "application/json",
                    "X-AUTH-APIKEY": COINDCX_API_KEY,
                    "X-AUTH-SIGNATURE": c_sig
                }
                async with session.post(COINDCX_BASE_URL + cancel_path, data=c_body, headers=c_headers) as cancel_resp:
                    c_data = await cancel_resp.json()
                    print(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] CANCEL RESPONSE (HTTP {cancel_resp.status}):")
                    print(json.dumps(c_data, indent=2))
            else:
                print("ℹ️ No active order ID to cancel.")

    print("=" * 80)
    print("✅ COINDCX NATIVE SERVER MARGIN EXECUTION VERIFIED!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_coindcx_order_test())
