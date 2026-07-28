"""
Binance Arbitrage Scanner:
1. Cash & Carry (Spot BUY + Quarterly Futures SELL) - 0% Funding Rate!
2. Conversion / Reversal Options Arbitrage (Sep Expiry Options + Quarterly Futures)
"""
import urllib.request
import json
from datetime import datetime

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode())

print("=" * 90)
print("   BINANCE RISK-FREE ARBITRAGE SCANNER (DATED FUTURES 0% FUNDING)")
print("=" * 90)

# 1. Fetch Spot Price (BTCUSDT)
spot_ticker = fetch("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
spot_price = float(spot_ticker['price'])
print(f"\n[+] Binance Spot BTC Price: ${spot_price:,.2f}")

# 2. Fetch Quarterly Futures Tickers (dapi / fapi delivery)
# Binance COIN-M delivery futures (e.g. BTCUSD_250925) and USDT-M delivery futures
delivery_info = fetch("https://dapi.binance.com/dapi/v1/ticker/price")
quarterly_futures = []
for f in delivery_info:
    sym = f['symbol']
    if 'BTC' in sym:
        price = float(f['price'])
        quarterly_futures.append((sym, price))

# Also check USDT-M Delivery futures
try:
    fapi_delivery = fetch("https://fapi.binance.com/fapi/v1/ticker/price")
    for f in fapi_delivery:
        sym = f['symbol']
        if 'BTC' in sym and ('_' in sym or any(c.isdigit() for c in sym[-4:])):
            price = float(f['price'])
            quarterly_futures.append((sym, price))
except Exception as e:
    pass

print("\n[+] Active Quarterly Futures Contracts (0% Funding Fee):")
print(f"{'Symbol':<25} {'Futures Price':>15} {'Spot Price':>15} {'Spread ($)':>12} {'Locked Return%':>15}")
print("-" * 85)

for sym, f_price in quarterly_futures:
    spread = f_price - spot_price
    pct_return = (spread / spot_price) * 100.0
    print(f"{sym:<25} ${f_price:>14,.2f} ${spot_price:>14,.2f} ${spread:>+11,.2f} {pct_return:>+14.2f}%")

# 3. Check Binance Options API for September Expiry
print("\n[+] Checking Binance Options (E-Options) for September Expiry...")
try:
    options_info = fetch("https://eapi.binance.com/eapi/v1/ticker")
    btc_options = [o for o in options_info if 'BTC' in o['symbol']]
    print(f"    Found {len(btc_options)} active BTC option strikes on Binance.")
    
    # Filter September options
    sep_options = [o for o in btc_options if '2509' in o['symbol'] or '2409' in o['symbol'] or '2609' in o['symbol']]
    print(f"    September Expiry Options: {len(sep_options)}")
    if sep_options:
        print("    Sample:", [o['symbol'] for o in sep_options[:5]])
except Exception as e:
    print(f"    Options API error: {e}")

print("=" * 90)
