import asyncio
import json
from live_order_executor import LiveOrderExecutor

async def main():
    executor = LiveOrderExecutor()
    await executor._ensure_session()
    
    # 1. Delta Positions
    delta_pos = await executor._delta_get("/v2/positions")
    print("=== DELTA OPEN POSITIONS ===")
    delta_results = delta_pos.get("result", []) if isinstance(delta_pos, dict) else []
    active_delta = [p for p in delta_results if float(p.get("size", 0)) != 0]
    print(f"Active Delta Positions Count: {len(active_delta)}")
    for p in active_delta:
        print(f"  Symbol: {p.get('product_symbol')} | Size: {p.get('size')} Lots | Entry Price: {p.get('entry_price')}")

    # 2. CoinDCX Positions
    pos_path = "/exchange/v1/derivatives/futures/positions"
    pos_payload = {}
    from live_order_executor import sign_coindcx, COINDCX_BASE_URL, COINDCX_API_KEY
    body_str, sig = sign_coindcx(pos_payload)
    headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": COINDCX_API_KEY, "X-AUTH-SIGNATURE": sig}
    async with executor.session.post(COINDCX_BASE_URL + pos_path, data=body_str, headers=headers) as resp:
        cdcx_pos = await resp.json()
        print("\n=== COINDCX OPEN POSITIONS ===")
        active_cdcx = [p for p in cdcx_pos if float(p.get("active_pos", 0)) != 0] if isinstance(cdcx_pos, list) else []
        print(f"Active CoinDCX Positions Count: {len(active_cdcx)}")
        for p in active_cdcx:
            print(f"  Pair: {p.get('pair')} | Active Pos: {p.get('active_pos')}")

    await executor.close()

if __name__ == "__main__":
    asyncio.run(main())
