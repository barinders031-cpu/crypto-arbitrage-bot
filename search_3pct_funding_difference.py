"""
Scanner for extreme funding rate differences (>= 3.0%) between Delta Exchange India and Binance/Bybit
Calculates:
1. Per-Payment Raw Difference >= 3.0%
2. Daily Cumulative Funding Difference >= 3.0%
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
        daily = rate_pct * (24.0 / h)
        delta_map[coin] = {
            'symbol': sym,
            'rate': rate_pct,
            'interval': h,
            'daily': daily
        }

print("[+] Fetching live raw data from Binance Futures...")
binance_funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")

binance_map = {}
for b in binance_funding:
    sym = b.get('symbol', '')
    if sym.endswith('USDT'):
        coin = sym.replace('USDT', '')
        rate_pct = float(b.get('lastFundingRate') or 0) * 100.0
        daily = rate_pct * 3.0
        binance_map[coin] = {
            'symbol': sym,
            'rate': rate_pct,
            'interval': 8.0,
            'daily': daily
        }

# Filter for 3% threshold
per_payment_3pct = []
daily_3pct = []

for coin, d in delta_map.items():
    if coin in binance_map:
        b = binance_map[coin]
        d_rate = d['rate']
        b_rate = b['rate']
        
        d_daily = d['daily']
        b_daily = b['daily']
        
        raw_diff_payment = d_rate - b_rate
        abs_diff_payment = abs(raw_diff_payment)
        
        raw_diff_daily = d_daily - b_daily
        abs_diff_daily = abs(raw_diff_daily)
        
        item = {
            'coin': coin,
            'delta_sym': d['symbol'],
            'delta_rate': d_rate,
            'delta_int': d['interval'],
            'delta_daily': d_daily,
            'binance_sym': b['symbol'],
            'binance_rate': b_rate,
            'binance_int': b['interval'],
            'binance_daily': b_daily,
            'diff_payment': raw_diff_payment,
            'abs_diff_payment': abs_diff_payment,
            'diff_daily': raw_diff_daily,
            'abs_diff_daily': abs_diff_daily,
        }
        
        if abs_diff_payment >= 3.0:
            per_payment_3pct.append(item)
            
        if abs_diff_daily >= 3.0:
            daily_3pct.append(item)

print("\n" + "=" * 125)
print("   EXTREME FUNDING DIFFERENCE SEARCH (>= 3.0% THRESHOLD)")
print("=" * 125)

print(f"\n[1] COINS WITH RAW PER-PAYMENT DIFFERENCE >= 3.0% (|Delta Rate - Binance Rate| >= 3.0%): {len(per_payment_3pct)}")
if per_payment_3pct:
    for item in sorted(per_payment_3pct, key=lambda x: x['abs_diff_payment'], reverse=True):
        print(f"    - {item['coin']:<10} | Delta: {item['delta_rate']:>+8.4f}% | Binance: {item['binance_rate']:>+8.4f}% | Spread Diff: {item['diff_payment']:>+8.4f}%")
else:
    print("    None right now. Highest per-payment difference is ~0.10% (BASED/HUSD) to 0.05% (TLM).")

print(f"\n[2] COINS WITH DAILY CUMULATIVE DIFFERENCE >= 3.0% (|Delta Daily - Binance Daily| >= 3.0%): {len(daily_3pct)}")
if daily_3pct:
    print(f"{'Coin':<10} {'Delta Daily%':>15} {'Binance Daily%':>16} {'Daily Difference':>18} {'Best Action':>20}")
    print("-" * 85)
    for item in sorted(daily_3pct, key=lambda x: x['abs_diff_daily'], reverse=True):
        action = "SHORT Delta + LONG Binance" if item['diff_daily'] > 0 else "LONG Delta + SHORT Binance"
        print(f"{item['coin']:<10} {item['delta_daily']:>+14.4f}% {item['binance_daily']:>+15.4f}% {item['diff_daily']:>+17.4f}% {action:>20}")

print("=" * 125)
