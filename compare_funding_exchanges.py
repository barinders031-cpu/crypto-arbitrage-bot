"""
Compare: Delta Exchange vs Binance Funding Rates
Also check if high-funding coins have SPOT on Binance
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


print("[+] Fetching data from all exchanges...")

# =====================================================
# 1. DELTA EXCHANGE - Top funding coins (from our scanner)
# =====================================================
delta_base = "https://api.india.delta.exchange"
products = fetch(delta_base + '/v2/products')
tickers_raw = fetch(delta_base + '/v2/tickers')
ticker_map = {t['symbol']: t for t in tickers_raw}

payment_interval_map = {}
for p in products:
    sym = p.get('symbol', '')
    specs = p.get('product_specs') or {}
    rate_exchange_interval = specs.get('rate_exchange_interval')
    if rate_exchange_interval:
        payment_interval_map[sym] = int(rate_exchange_interval) / 3600.0
    else:
        payment_interval_map[sym] = 8.0

delta_results = {}
for sym, t in ticker_map.items():
    if 'perpetual' not in t.get('contract_type', ''):
        continue
    rate_pct = float(t.get('funding_rate') or 0)
    mark = float(t.get('mark_price') or 0)
    if mark <= 0 or abs(rate_pct) < 0.01:
        continue
    payment_hours = payment_interval_map.get(sym, 8.0)
    payments_per_day = 24.0 / payment_hours
    daily = rate_pct * payments_per_day
    coin = sym.replace('USD', '')
    delta_results[coin] = {
        'delta_sym': sym,
        'rate_per_payment': rate_pct,
        'payment_hours': payment_hours,
        'daily_pct': daily,
        'mark_price': mark,
    }

# =====================================================
# 2. BINANCE FUTURES - Get all funding rates
# =====================================================
print("[+] Fetching Binance USDT-M funding rates...")
binance_funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")

binance_results = {}
for b in binance_funding:
    sym = b.get('symbol', '')
    if not sym.endswith('USDT'):
        continue
    rate = float(b.get('lastFundingRate') or 0) * 100.0  # convert to %
    mark = float(b.get('markPrice') or 0)
    coin = sym.replace('USDT', '')
    binance_results[coin] = {
        'binance_sym': sym,
        'rate_8h': rate,         # Binance is always 8H
        'daily_pct': rate * 3,   # 3x per day
        'mark_price': mark,
    }

# =====================================================
# 3. BINANCE SPOT - Check which coins have spot
# =====================================================
print("[+] Fetching Binance SPOT market list...")
spot_info = fetch("https://api.binance.com/api/v3/exchangeInfo")
spot_coins = set()
for s in spot_info.get('symbols', []):
    if s.get('quoteAsset') == 'USDT' and s.get('status') == 'TRADING':
        spot_coins.add(s.get('baseAsset', ''))

# =====================================================
# 4. COMPARE - Delta top coins vs Binance
# =====================================================
print("\n")
print("=" * 120)
print("  DELTA EXCHANGE TOP FUNDING COINS vs BINANCE COMPARISON")
print("=" * 120)
print(f"{'Coin':<12} {'Delta Rate/Pay':>14} {'Delta Daily%':>13} {'Binance Rate/8H':>16} {'Binance Daily%':>15} {'Binance Spot?':>14} {'Winner':>10}")
print("-" * 120)

# Sort by Delta daily rate
top_delta = sorted(delta_results.items(), key=lambda x: abs(x[1]['daily_pct']), reverse=True)

for coin, d in top_delta[:30]:
    b = binance_results.get(coin, {})
    delta_daily = d['daily_pct']
    delta_rate = d['rate_per_payment']
    delta_ph = d['payment_hours']
    
    binance_daily = b.get('daily_pct', 0)
    binance_rate = b.get('rate_8h', 0)
    
    has_spot = "YES" if coin in spot_coins else "NO"
    
    # Winner
    if abs(delta_daily) > abs(binance_daily) and abs(binance_daily) > 0:
        winner = "DELTA"
    elif abs(binance_daily) > abs(delta_daily):
        winner = "BINANCE"
    elif abs(binance_daily) == 0:
        winner = "DELTA only"
    else:
        winner = "SAME"

    action = "SHORT" if delta_daily > 0 else "LONG"
    
    b_rate_str = f"{binance_rate:+.4f}%" if b else "N/A"
    b_daily_str = f"{binance_daily:+.4f}%" if b else "N/A"
    
    print(f"{coin:<12} {delta_rate:>+13.4f}% {delta_daily:>+12.4f}%  {b_rate_str:>15}  {b_daily_str:>14}  {has_spot:>14}  {winner:>10}  [{action}]")

print()
print("=" * 120)
print("[NOTE] Delta rate is per payment interval (4H/8H). Binance rate is always per 8H.")
print("       Daily = Delta rate × (24/payment_hours) | Binance Daily = rate × 3")
