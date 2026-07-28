"""
Delta Exchange - REAL Funding Rate Scanner
Shows EXACT funding rate as shown on Delta UI per coin
Checks Binance SPOT availability for hedge
"""
import urllib.request
import json

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=12)
    data = json.loads(res.read().decode())
    if isinstance(data, dict) and 'result' in data:
        return data['result']
    return data

print("[+] Fetching live data from Delta Exchange India...")
products  = fetch_json("https://api.india.delta.exchange/v2/products")
tickers   = fetch_json("https://api.india.delta.exchange/v2/tickers")

# Map symbol -> rate_exchange_interval (actual payment interval in hours)
pay_interval = {}
for p in products:
    sym   = p.get('symbol', '')
    specs = p.get('product_specs') or {}
    rei   = specs.get('rate_exchange_interval')  # seconds
    pay_interval[sym] = int(rei) / 3600.0 if rei else 8.0

# Build funding list for ALL perpetuals
print("[+] Fetching Binance SPOT list for hedge check...")
spot_info  = fetch_json("https://api.binance.com/api/v3/exchangeInfo")
binance_spot = set(
    s['baseAsset']
    for s in spot_info.get('symbols', [])
    if s.get('quoteAsset') == 'USDT' and s.get('status') == 'TRADING'
)

results = []
for t in tickers:
    if 'perpetual' not in t.get('contract_type', ''):
        continue

    sym       = t.get('symbol', '')
    # funding_rate is ALREADY in % form (e.g. 0.3252 means 0.3252%)
    rate_pct  = float(t.get('funding_rate') or 0)
    mark      = float(t.get('mark_price') or 0)
    vol       = float(t.get('volume', 0) or 0)

    if mark <= 0 or abs(rate_pct) < 0.005:
        continue

    ph            = pay_interval.get(sym, 8.0)
    payments_day  = 24.0 / ph
    daily_pct     = rate_pct * payments_day
    coin          = sym.replace('USD', '')
    on_binance    = coin in binance_spot or (coin + 'T') in binance_spot

    results.append({
        'symbol':       sym,
        'coin':         coin,
        'rate_pct':     rate_pct,       # Per payment period (as shown on Delta UI)
        'pay_h':        ph,
        'daily_pct':    daily_pct,
        'mark':         mark,
        'vol':          vol,
        'binance_spot': on_binance,
    })

# Sort by ABSOLUTE funding rate per payment (highest first)
results.sort(key=lambda x: abs(x['rate_pct']), reverse=True)

print()
print("=" * 110)
print("   TOP FUNDING COINS - DELTA EXCHANGE INDIA (LIVE)")
print("   'Rate per Payment' = EXACT same value shown on Delta UI (e.g. Funding 4h: 0.3252%)")
print("=" * 110)
print(f"{'#':<4} {'Symbol':<14} {'Pay':<6} {'Funding Rate':<15} {'Daily%':<12} {'Price':>12} {'Vol USD':>14} {'Binance Spot':>13} {'Action':<8}")
print("-" * 110)

for i, r in enumerate(results[:20], 1):
    action = "SHORT" if r['rate_pct'] > 0 else "LONG "
    bspot  = "YES" if r['binance_spot'] else "NO"
    print(
        f"{i:<4} {r['symbol']:<14} {r['pay_h']:>3.0f}H  "
        f"{r['rate_pct']:>+10.4f}%    "
        f"{r['daily_pct']:>+9.4f}%  "
        f"{r['mark']:>12.6f}  "
        f"{r['vol']:>13,.0f}  "
        f"{bspot:>12}  "
        f"{action}"
    )

print()
print("=" * 110)
print("TOP 10 BEST FOR HEDGE (Binance Spot Available = YES):")
print("-" * 110)
hedge_coins = [r for r in results if r['binance_spot']][:10]
for i, r in enumerate(hedge_coins, 1):
    action = "SHORT futures + BUY spot" if r['rate_pct'] > 0 else "LONG futures + SELL spot"
    print(
        f"  {i}. {r['symbol']:<14} | Funding: {r['rate_pct']:>+8.4f}% per {r['pay_h']:.0f}H "
        f"({r['daily_pct']:>+7.4f}%/day) | {action}"
    )
print("=" * 110)
