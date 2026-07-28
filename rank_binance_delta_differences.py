"""
Ranked Funding Rate Comparison: DELTA EXCHANGE INDIA vs BINANCE vs COINDCX
Calculates raw per-payment rates and sorts by largest difference.
"""
import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    data = json.loads(res.read().decode())
    if isinstance(data, dict) and 'result' in data:
        return data['result']
    return data

print("[+] Fetching live raw funding rates from Delta Exchange India...")
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
        delta_map[coin] = {
            'symbol': sym,
            'rate': rate_pct,
            'interval': h
        }

print("[+] Fetching live raw funding rates from Binance & CoinDCX...")
binance_funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")

binance_map = {}
for b in binance_funding:
    sym = b.get('symbol', '')
    if sym.endswith('USDT'):
        coin = sym.replace('USDT', '')
        rate_pct = float(b.get('lastFundingRate') or 0) * 100.0
        binance_map[coin] = {
            'symbol': sym,
            'rate': rate_pct,
            'interval': 8.0
        }

# Match all common coins and calculate ABSOLUTE DIFFERENCE
results = []
for coin, d in delta_map.items():
    if coin in binance_map:
        b = binance_map[coin]
        d_rate = d['rate']
        b_rate = b['rate']
        
        raw_diff = d_rate - b_rate
        abs_diff = abs(raw_diff)
        
        results.append({
            'coin': coin,
            'delta_sym': d['symbol'],
            'delta_rate': d_rate,
            'delta_int': d['interval'],
            'binance_sym': b['symbol'],
            'binance_rate': b_rate,
            'binance_int': b['interval'],
            'raw_diff': raw_diff,
            'abs_diff': abs_diff
        })

# Sort RANK WISE by LARGEST ABSOLUTE DIFFERENCE
results.sort(key=lambda x: x['abs_diff'], reverse=True)

print("\n" + "=" * 125)
print("   DELTA EXCHANGE INDIA vs BINANCE vs COINDCX - RANKED BY LARGEST FUNDING DIFFERENCE")
print("   (Sorted Serial-Wise from Highest Spread Difference to Lowest)")
print("=" * 125)
print(f"{'Rank':<5} {'Coin':<10} {'Delta Instrument':<18} {'Delta Rate/Pay':>18} {'Binance Instrument':<20} {'Binance/CoinDCX Rate':>22} {'Spread Difference':>18}")
print("-" * 125)

for rank, r in enumerate(results[:25], 1):
    d_str = f"{r['delta_rate']:>+8.4f}% ({r['delta_int']:.0f}H)"
    b_str = f"{r['binance_rate']:>+8.4f}% ({r['binance_int']:.0f}H)"
    diff_str = f"{r['raw_diff']:>+9.4f}%"
    
    print(f"{rank:<5} {r['coin']:<10} {r['delta_sym']:<18} {d_str:>18} {r['binance_sym']:<20} {b_str:>22} {diff_str:>18}")

print("=" * 125)
