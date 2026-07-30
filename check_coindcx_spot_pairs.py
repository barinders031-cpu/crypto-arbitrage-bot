import urllib.request
import json

url = "https://api.coindcx.com/exchange/v1/markets_details"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
try:
    res = urllib.request.urlopen(req, timeout=10)
    data = json.loads(res.read().decode())
    print(f"Total CoinDCX markets: {len(data)}")
    
    usdt_pairs = [m for m in data if m.get('target_currency_short') in ['USDT', 'BTC', 'ETH'] or m.get('pair','').endswith('USDT')]
    print("\nSample CoinDCX spot pairs:")
    for p in usdt_pairs[:20]:
        print(f"  symbol: {p.get('symbol'):15s} | pair: {p.get('pair'):15s} | coindcx_name: {p.get('coindcx_name')}")
except Exception as e:
    print(f"Error: {e}")
