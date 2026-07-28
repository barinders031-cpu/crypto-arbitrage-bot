import requests, time, json
from collections import defaultdict

base = 'https://api.india.delta.exchange'

print("=== DELTA EXCHANGE BOT DIAGNOSTIC ===\n")

# 1. Fetch BTC Options
prods = requests.get(base + '/v2/products', timeout=10).json()
btc_opts = [p for p in prods.get('result', []) 
            if p.get('underlying_asset', {}).get('symbol') == 'BTC' 
            and p.get('contract_type') in ['call_options', 'put_options']]

print(f"[OK] BTC Options Found: {len(btc_opts)}")

# 2. Spot price
spot_resp = requests.get(base + '/v2/tickers/BTCUSD').json()
res = spot_resp.get('result', {})
spot = float(res.get('close', 0) or res.get('spot_price', 0) or res.get('mark_price', 0) or 64000)
print(f"[OK] BTC Spot Price: ${spot}")

# 3. Group by expiry
grouped = defaultdict(list)
for p in btc_opts:
    expiry = p.get('expiry_date', '')
    grouped[expiry].append(p)

expiries = sorted(grouped.keys())
print(f"[OK] Expiry dates: {expiries[:5]}")

# 4. Scan nearest expiry for arbitrage
nearest = expiries[0]
opts = grouped[nearest]
calls = sorted([o for o in opts if o.get('contract_type') == 'call_options'], key=lambda x: float(x.get('strike_price', 0)))
puts = sorted([o for o in opts if o.get('contract_type') == 'put_options'], key=lambda x: float(x.get('strike_price', 0)))

print(f"\n[SCAN] Nearest expiry: {nearest}")
print(f"[SCAN] Calls: {len(calls)}, Puts: {len(puts)}")

# ATM window: 5% around spot
atm_calls = [c for c in calls if abs(float(c['strike_price']) - spot) / spot < 0.05]
atm_puts = [c for c in puts if abs(float(c['strike_price']) - spot) / spot < 0.05]
print(f"[SCAN] ATM Calls (5% range): {len(atm_calls)}")
print(f"[SCAN] ATM Puts (5% range): {len(atm_puts)}")

# 5. Check orderbooks for call arbitrage
print("\n[CALL SCAN] Checking vertical spread arbitrage (lower ask < higher bid)...")
arb_found = 0

for i in range(len(atm_calls) - 1):
    c1 = atm_calls[i]
    c2 = atm_calls[i+1]
    ob1 = requests.get(base + '/v2/l2orderbook/' + c1['symbol'], timeout=3).json().get('result', {})
    ob2 = requests.get(base + '/v2/l2orderbook/' + c2['symbol'], timeout=3).json().get('result', {})
    asks1 = ob1.get('sell', [])
    bids2 = ob2.get('buy', [])
    if asks1 and bids2:
        c1_ask = float(asks1[0]['price'])
        c2_bid = float(bids2[0]['price'])
        credit = c2_bid - c1_ask
        profit_usd = credit * 0.001
        tag = ">>> ARB!" if credit > 0 else "     "
        print(f"  {tag} K1={c1['strike_price']} ask={c1_ask} | K2={c2['strike_price']} bid={c2_bid} | net={credit:.2f} profit=${profit_usd:.4f}")
        if credit > 0:
            arb_found += 1
    time.sleep(0.1)

# 6. Check orderbooks for put arbitrage
print("\n[PUT SCAN] Checking vertical spread arbitrage (higher ask < lower bid)...")
for i in range(len(atm_puts) - 1):
    p1 = atm_puts[i]     # lower strike
    p2 = atm_puts[i+1]   # higher strike
    ob1 = requests.get(base + '/v2/l2orderbook/' + p1['symbol'], timeout=3).json().get('result', {})
    ob2 = requests.get(base + '/v2/l2orderbook/' + p2['symbol'], timeout=3).json().get('result', {})
    bids1 = ob1.get('buy', [])
    asks2 = ob2.get('sell', [])
    if bids1 and asks2:
        p1_bid = float(bids1[0]['price'])
        p2_ask = float(asks2[0]['price'])
        credit = p1_bid - p2_ask
        profit_usd = credit * 0.001
        tag = ">>> ARB!" if credit > 0 else "     "
        print(f"  {tag} K1={p1['strike_price']} bid={p1_bid} | K2={p2['strike_price']} ask={p2_ask} | net={credit:.2f} profit=${profit_usd:.4f}")
        if credit > 0:
            arb_found += 1
    time.sleep(0.1)

print(f"\n=== RESULT: {arb_found} arbitrage opportunities found ===")
if arb_found == 0:
    print("[INFO] Market is efficient - no mispricings in ATM chain right now.")
    print("[INFO] Bot will continue scanning every 10 seconds for new opportunities.")
