"""
Binance Options Detailed Orderbook Scanner for Sep 25 Expiry
"""
import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode())

options_tickers = fetch("https://eapi.binance.com/eapi/v1/ticker")
fapi_prices = fetch("https://fapi.binance.com/fapi/v1/ticker/price")

fut_sep_price = 0.0
for f in fapi_prices:
    if f['symbol'] == 'BTCUSDT_260925':
        fut_sep_price = float(f['price'])
        break

print(f"BTCUSDT_260925 Futures Price: ${fut_sep_price:,.2f}\n")

# Filter Sep 25 Options with non-zero bids/asks
valid_opts = []
for o in options_tickers:
    sym = o['symbol']
    if 'BTC-260925-' in sym:
        bid = float(o.get('bidPrice') or 0)
        ask = float(o.get('askPrice') or 0)
        mark = float(o.get('markPrice') or 0)
        if bid > 0 or ask > 0 or mark > 0:
            valid_opts.append((sym, mark, bid, ask))

print(f"{'Option Symbol':<25} {'Mark Price':>12} {'Best Bid':>12} {'Best Ask':>12}")
print("-" * 65)
for sym, mark, bid, ask in sorted(valid_opts, key=lambda x: x[0]):
    print(f"{sym:<25} ${mark:>11.2f} ${bid:>11.2f} ${ask:>11.2f}")
