import sys
import asyncio
import json

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from live_order_executor import LiveOrderExecutor

async def main():
    executor = LiveOrderExecutor()
    await executor._ensure_session()

    print("=== DELTA DETAILED POSITIONS INSPECTION ===")
    d_pos_resp = await executor._delta_get("/v2/positions")
    result = d_pos_resp.get("result", []) if isinstance(d_pos_resp, dict) else []
    
    non_zero = []
    for p in result:
        size = float(p.get("size") or 0)
        entry_price = float(p.get("entry_price") or 0)
        realized_pnl = float(p.get("realized_pnl") or 0)
        unrealized_pnl = float(p.get("unrealized_pnl") or 0)
        sym = p.get("product_symbol", "")
        
        if size != 0 or unrealized_pnl != 0:
            non_zero.append(p)
            print(f"📌 ACTIVE POSITION: Symbol={sym} | Size={size} | EntryPrice={entry_price} | PnL={unrealized_pnl}")

    if not non_zero:
        print("✅ NO ACTIVE POSITIONS FOUND IN DELTA POSITIONS ARRAY!")

    print("\n=== DELTA OPEN ORDERS INSPECTION ===")
    d_orders_resp = await executor._delta_get("/v2/orders?state=open")
    orders_res = d_orders_resp.get("result", []) if isinstance(d_orders_resp, dict) else []
    print(f"Open Orders Count: {len(orders_res)}")
    for o in orders_res:
        print(f"  Order ID: {o.get('id')} | Symbol: {o.get('product_symbol')} | Side: {o.get('side')} | Size: {o.get('size')}")

    await executor.close()

if __name__ == "__main__":
    asyncio.run(main())
