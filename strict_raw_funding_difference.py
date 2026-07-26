"""
Clean Raw Funding Rate Difference Scanner (Delta Exchange India vs CoinDCX)
Strictly sorted by Raw Per-Payment Funding Difference % (Highest to Lowest)
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

print("[+] Fetching live raw data from Delta Exchange India...")
delta_products = fetch("https://api.india.delta.exchange/v2/products")
delta_tickers = fetch("https://api.india.delta.exchange/v2/tickers")

delta_interval = {}
for p in delta_products:
    sym = p.get('symbol', '')
    specs = p.get('product_specs') or {}
    rei = specs.get('rate_exchange_interval')
    delta_interval[sym] = int(rei) / 3600.0 if rei else 8.0

delta_map = {}
for t in delta_tickers:
    if 'perpetual' in t.get('contract_type', ''):
        sym = t.get('symbol', '')
        rate_pct = float(t.get('funding_rate') or 0)
        coin = sym.replace('USD', '')
        h = delta_interval.get(sym, 8.0)
        delta_map[coin] = {'rate': rate_pct, 'h': h, 'sym': sym}

print("[+] Fetching live raw data from CoinDCX (Binance Liquidity)...")
binance_funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")

coindcx_map = {}
for b in binance_funding:
    sym = b.get('symbol', '')
    if sym.endswith('USDT'):
        coin = sym.replace('USDT', '')
        rate_pct = float(b.get('lastFundingRate') or 0) * 100.0
        coindcx_map[coin] = {'rate': rate_pct, 'h': 8.0, 'sym': sym}

results = []

for coin, d in delta_map.items():
    if coin in coindcx_map:
        c = coindcx_map[coin]
        d_rate = d['rate']
        c_rate = c['rate']
        
        # Raw Spread Difference
        raw_diff = abs(d_rate - c_rate)
        
        if d_rate >= 0:
            action = "SHORT Delta + LONG CoinDCX"
        else:
            action = "LONG Delta + SHORT CoinDCX"

        results.append({
            'coin': coin,
            'delta_sym': d['sym'],
            'delta_rate': d_rate,
            'delta_h': d['h'],
            'cdcx_sym': c['sym'],
            'cdcx_rate': c_rate,
            'cdcx_h': c['h'],
            'raw_diff': raw_diff,
            'action': action
        })

# STRICTLY SORTED BY LARGEST RAW FUNDING DIFFERENCE %
results.sort(key=lambda x: x['raw_diff'], reverse=True)

print("\n" + "=" * 115)
print("   TOP LIVE FUNDING RATE DIFFERENCE LIST (DELTA EXCHANGE INDIA vs COINDCX)")
print("   Strictly Ranked by Largest Per-Payment Raw Funding Difference %")
print("=" * 115)
print(f"{'Rank':<5} {'Coin':<10} {'Delta Rate (Per Payment)':>24} {'CoinDCX Rate (Per Payment)':>26} {'RAW DIFFERENCE':>18} {'Strategy Action':>26}")
print("-" * 115)

for rank, r in enumerate(results[:20], 1):
    d_str = f"{r['delta_rate']:>+7.4f}% ({r['delta_h']:.0f}H)"
    c_str = f"{r['cdcx_rate']:>+7.4f}% ({r['cdcx_h']:.0f}H)"
    
    print(f"{rank:<5} {r['coin']:<10} {d_str:>24} {c_str:>26} {r['raw_diff']:>17.4f}% {r['action']:>26}")

print("=" * 115)
