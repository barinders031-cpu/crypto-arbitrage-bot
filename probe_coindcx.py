import urllib.request, json

endpoints = [
    "https://api.coindcx.com/exchange/v1/derivatives/futures/data/summary",
    "https://api.coindcx.com/exchange/v1/derivatives/futures/data/stats?pair=B-BTC_USDT",
    "https://api.coindcx.com/exchange/v1/derivatives/futures/data/mark_price?pair=B-BTC_USDT",
    "https://api.coindcx.com/exchange/v1/derivatives/futures/data/trade_history?pair=B-BTC_USDT",
    "https://api.coindcx.com/exchange/v1/derivatives/futures/data/orderbook?pair=B-BTC_USDT",
    "https://api.coindcx.com/exchange/v1/derivatives/ticker?pair=B-BTC_USDT",
    "https://api.coindcx.com/exchange/v1/derivatives/futures/ticker",
    "https://api.coindcx.com/exchange/v1/derivatives/funding_rates",
]
for ep in endpoints:
    try:
        res = urllib.request.urlopen(urllib.request.Request(ep, headers={"User-Agent":"x"}), timeout=5)
        data = json.loads(res.read().decode())
        print(f"OK: {ep.split('/')[-1]}")
        print(f"   {str(data)[:400]}")
    except Exception as e:
        print(f"FAIL {ep.split('/')[-1]}: {str(e)[:70]}")
