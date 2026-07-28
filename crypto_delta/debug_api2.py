"""Debug options structure."""
import requests

r = requests.get('https://api.india.delta.exchange/v2/products', timeout=10)
data = r.json()
products = data.get('result', [])
btc = [p for p in products if p.get('underlying_asset', {}).get('symbol') == 'BTC']

# Check fields
if btc:
    p = btc[0]
    print("Keys:", list(p.keys()))
    print("Sample:", p)
