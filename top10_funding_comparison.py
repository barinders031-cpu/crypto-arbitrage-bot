"""
Delta Exchange India vs CoinDCX Real Per-Payment Funding Rate Comparison
Shows exact raw per-payment funding rate as shown on UI (NO DAILY YIELD)
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

# Map Delta product -> rate_exchange_interval
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
        rate_pct = float(t.get('funding_rate') or 0)  # Raw % per payment as shown on UI
        coin = sym.replace('USD', '')
        h = delta_interval.get(sym, 8.0)
        delta_map[coin] = {
            'symbol': sym,
            'rate': rate_pct,
            'interval': h
        }

print("[+] Fetching live raw funding rates from CoinDCX (Binance Liquidity)...")
binance_funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")

coindcx_map = {}
for b in binance_funding:
    sym = b.get('symbol', '')
    if sym.endswith('USDT'):
        coin = sym.replace('USDT', '')
        rate_pct = float(b.get('lastFundingRate') or 0) * 100.0  # % per 8h payment as shown on UI
        coindcx_map[coin] = {
            'symbol': f"B-{sym}",
            'rate': rate_pct,
            'interval': 8.0
        }

# Compare Top 10 High Funding Coins on Delta vs CoinDCX
results = []
for coin, d in delta_map.items():
    d_rate = d['rate']
    d_int = d['interval']
    
    cdcx = coindcx_map.get(coin, {})
    c_rate = cdcx.get('rate', 0.0) if cdcx else 0.0
    c_int = cdcx.get('interval', 8.0) if cdcx else 8.0
    
    diff = d_rate - c_rate
    
    results.append({
        'coin': coin,
        'delta_sym': d['symbol'],
        'delta_rate': d_rate,
        'delta_int': d_int,
        'cdcx_sym': cdcx.get('symbol', 'N/A'),
        'cdcx_rate': c_rate if cdcx else None,
        'cdcx_int': c_int if cdcx else None,
        'diff': diff
    })

# Sort by absolute Delta Funding Rate
results.sort(key=lambda x: abs(x['delta_rate']), reverse=True)

print("\n" + "=" * 115)
print("   TOP 10 LIVE FUNDING RATE COMPARISON: DELTA EXCHANGE INDIA vs COINDCX")
print("   (Exact raw per-payment funding rate as shown on UI)")
print("=" * 115)
print(f"{'#':<3} {'Coin':<10} {'Delta Instrument':<18} {'Delta Rate/Payment':>20} {'CoinDCX Instrument':<20} {'CoinDCX Rate/Payment':>20} {'Difference':>15}")
print("-" * 115)

for i, r in enumerate(results[:10], 1):
    d_str = f"{r['delta_rate']:>+9.4f}% ({r['delta_int']:.0f}H)"
    
    if r['cdcx_rate'] is not None:
        c_str = f"{r['cdcx_rate']:>+9.4f}% ({r['cdcx_int']:.0f}H)"
    else:
        c_str = "N/A (Not Listed)"
        
    diff_str = f"{r['diff']:>+10.4f}%"
    
    print(f"{i:<3} {r['coin']:<10} {r['delta_sym']:<18} {d_str:>20} {r['cdcx_sym']:<20} {c_str:>20} {diff_str:>15}")

print("=" * 115)
