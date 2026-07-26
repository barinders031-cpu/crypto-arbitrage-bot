"""
Real Delta Exchange India - ACCURATE Funding Rate Scanner
Uses: rate_exchange_interval (actual payment interval) from product_specs
"""
import urllib.request
import json

BASE = "https://api.india.delta.exchange"

def fetch(path):
    req = urllib.request.Request(BASE + path, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=15)
    return json.loads(res.read().decode()).get('result', [])

print("[+] Fetching data from Delta Exchange India (LIVE)...")
products = fetch('/v2/products')
tickers_raw = fetch('/v2/tickers')

ticker_map = {t['symbol']: t for t in tickers_raw}

# Build payment_interval_hours map from product_specs -> rate_exchange_interval
payment_interval_map = {}
for p in products:
    sym = p.get('symbol', '')
    specs = p.get('product_specs') or {}
    rate_exchange_interval = specs.get('rate_exchange_interval')  # seconds
    if rate_exchange_interval:
        payment_interval_map[sym] = int(rate_exchange_interval) / 3600.0  # to hours
    else:
        payment_interval_map[sym] = 8.0  # fallback

results = []
for sym, t in ticker_map.items():
    if 'perpetual' not in t.get('contract_type', ''):
        continue

    rate_pct = float(t.get('funding_rate') or 0)  # Already in % e.g. 0.1215 = 0.1215%
    mark = float(t.get('mark_price') or 0)
    vol = float(t.get('volume', 0) or 0)
    if mark <= 0:
        continue

    payment_hours = payment_interval_map.get(sym, 8.0)
    payments_per_day = 24.0 / payment_hours
    daily_rate_pct = rate_pct * payments_per_day
    rate_per_payment_pct = rate_pct

    # Show all coins with any rate > 0.05% per payment (ignore zero/tiny rates)
    if abs(rate_per_payment_pct) >= 0.05:
        action = 'SHORT' if rate_pct > 0 else 'LONG'
        results.append((abs(rate_per_payment_pct), rate_per_payment_pct, daily_rate_pct, payment_hours, sym, mark, vol, action))

results.sort(reverse=True)

print(f"\n{'Rank':<5} {'Symbol':<22} {'Pay Interval':>13} {'Rate/Payment%':>14} {'Daily%':>10} {'Price':>12} {'Volume USD':>15} {'Action':>8}")
print('=' * 108)
for rank, (abs_r, rate_pp, daily, fp, sym, mark, vol, action) in enumerate(results[:60], 1):
    print(f"{rank:<5} {sym:<22} {fp:>10.0f}H     {rate_pp:>13.4f}%  {daily:>9.4f}%  {mark:>12.6f}  {vol:>15,.0f}  {action:>8s}")

print(f"\nTotal coins shown: {min(60, len(results))} | Total with rate >= 0.05%: {len(results)}")
