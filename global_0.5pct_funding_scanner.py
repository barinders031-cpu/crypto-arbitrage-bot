"""
Global Multi-Exchange Funding Rate Difference Scanner (Threshold >= 0.5%)
Exchanges Scanned:
1. Delta Exchange India
2. Binance Futures
3. Bybit Futures
4. OKX Futures
5. Gate.io Futures
"""
import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        res = urllib.request.urlopen(req, timeout=10)
        data = json.loads(res.read().decode())
        if isinstance(data, dict) and 'result' in data:
            return data['result']
        return data
    except Exception as e:
        return []

print("=" * 110)
print("   GLOBAL MULTI-EXCHANGE FUNDING DIFFERENCE SCANNER (>= 0.5% THRESHOLD)")
print("=" * 110)

# 1. Delta Exchange India
print("\n[+] Fetching Delta Exchange India...")
delta_products = fetch("https://api.india.delta.exchange/v2/products")
delta_tickers = fetch("https://api.india.delta.exchange/v2/tickers")

delta_map = {}
if isinstance(delta_tickers, list):
    for t in delta_tickers:
        if 'perpetual' in t.get('contract_type', ''):
            sym = t.get('symbol', '')
            rate_pct = float(t.get('funding_rate') or 0)
            coin = sym.replace('USD', '')
            delta_map[coin] = rate_pct

# 2. Binance Futures
print("[+] Fetching Binance Futures...")
binance_funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")
binance_map = {}
if isinstance(binance_funding, list):
    for b in binance_funding:
        sym = b.get('symbol', '')
        if sym.endswith('USDT'):
            coin = sym.replace('USDT', '')
            rate_pct = float(b.get('lastFundingRate') or 0) * 100.0
            binance_map[coin] = rate_pct

# 3. Bybit Futures
print("[+] Fetching Bybit Futures...")
bybit_map = {}
try:
    bybit_res = fetch("https://api.bybit.com/v5/market/tickers?category=linear")
    if isinstance(bybit_res, dict) and 'list' in bybit_res.get('result', {}):
        for b in bybit_res['result']['list']:
            sym = b.get('symbol', '')
            if sym.endswith('USDT'):
                coin = sym.replace('USDT', '')
                rate_pct = float(b.get('fundingRate') or 0) * 100.0
                bybit_map[coin] = rate_pct
except Exception as e:
    print(f"    Bybit error: {e}")

# 4. Gate.io Futures
print("[+] Fetching Gate.io Futures...")
gate_map = {}
try:
    gate_res = fetch("https://api.gateio.ws/api/v4/futures/usdt/tickers")
    if isinstance(gate_res, list):
        for g in gate_res:
            sym = g.get('contract', '')  # e.g., BTC_USDT
            if sym.endswith('_USDT'):
                coin = sym.replace('_USDT', '')
                rate_pct = float(g.get('funding_rate') or 0) * 100.0
                gate_map[coin] = rate_pct
except Exception as e:
    print(f"    Gate error: {e}")

print(f"\n[SUMMARY OF COINS SCANNED]")
print(f"    Delta: {len(delta_map)} | Binance: {len(binance_map)} | Bybit: {len(bybit_map)} | Gate.io: {len(gate_map)}")

# Scan all pairs of exchanges for per-payment difference >= 0.5%
results_payment = []
results_daily = []

exchanges = {
    'Delta': delta_map,
    'Binance': binance_map,
    'Bybit': bybit_map,
    'Gate': gate_map
}

ex_names = list(exchanges.keys())
all_coins = set(delta_map.keys()) | set(binance_map.keys()) | set(bybit_map.keys()) | set(gate_map.keys())

for coin in all_coins:
    for i in range(len(ex_names)):
        for j in range(i + 1, len(ex_names)):
            e1, e2 = ex_names[i], ex_names[j]
            m1, m2 = exchanges[e1], exchanges[e2]
            
            if coin in m1 and coin in m2:
                r1 = m1[coin]
                r2 = m2[coin]
                diff = r1 - r2
                abs_diff = abs(diff)
                
                # Daily rates (assuming ~3x payments per day average)
                d1 = r1 * 3.0
                d2 = r2 * 3.0
                daily_diff = d1 - d2
                abs_daily_diff = abs(daily_diff)
                
                if abs_diff >= 0.5:
                    results_payment.append({
                        'coin': coin,
                        'ex1': e1, 'r1': r1,
                        'ex2': e2, 'r2': r2,
                        'diff': diff, 'abs_diff': abs_diff
                    })
                    
                if abs_daily_diff >= 0.5:
                    results_daily.append({
                        'coin': coin,
                        'ex1': e1, 'r1': r1, 'd1': d1,
                        'ex2': e2, 'r2': r2, 'd2': d2,
                        'diff': daily_diff, 'abs_diff': abs_daily_diff
                    })

# Print Results
print("\n" + "=" * 110)
print(f"   [1] PER-PAYMENT FUNDING DIFFERENCE >= 0.5%: ({len(results_payment)} Pairs Found)")
print("=" * 110)

if results_payment:
    results_payment.sort(key=lambda x: x['abs_diff'], reverse=True)
    print(f"{'Coin':<10} {'Ex 1':<10} {'Rate 1':>12} {'Ex 2':<10} {'Rate 2':>12} {'Per-Payment Diff':>20} {'Action':>25}")
    print("-" * 110)
    for r in results_payment[:20]:
        action = f"SHORT {r['ex1']} + LONG {r['ex2']}" if r['diff'] > 0 else f"LONG {r['ex1']} + SHORT {r['ex2']}"
        print(f"{r['coin']:<10} {r['ex1']:<10} {r['r1']:>+11.4f}% {r['ex2']:<10} {r['r2']:>+11.4f}% {r['diff']:>+19.4f}% {action:>25}")
else:
    print("    No exchange pair currently has a per-payment raw funding difference >= 0.5%.")

print("\n" + "=" * 110)
print(f"   [2] DAILY CUMULATIVE FUNDING DIFFERENCE >= 0.5%: ({len(results_daily)} Pairs Found)")
print("=" * 110)

if results_daily:
    results_daily.sort(key=lambda x: x['abs_diff'], reverse=True)
    print(f"{'Coin':<10} {'Ex 1':<10} {'Daily 1%':>12} {'Ex 2':<10} {'Daily 2%':>12} {'Daily Diff%':>18} {'Action':>25}")
    print("-" * 110)
    for r in results_daily[:25]:
        action = f"SHORT {r['ex1']} + LONG {r['ex2']}" if r['diff'] > 0 else f"LONG {r['ex1']} + SHORT {r['ex2']}"
        print(f"{r['coin']:<10} {r['ex1']:<10} {r['d1']:>+11.4f}% {r['ex2']:<10} {r['d2']:>+11.4f}% {r['diff']:>+17.4f}% {action:>25}")
else:
    print("    No exchange pair currently has a daily cumulative funding difference >= 0.5%.")

print("=" * 110)
