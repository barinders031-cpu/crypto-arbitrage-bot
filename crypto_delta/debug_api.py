"""Debug Delta API."""
import requests

r = requests.get('https://api.india.delta.exchange/v2/products', timeout=10)
print('Status:', r.status_code)
if r.status_code == 200:
    data = r.json()
    products = data.get('result', [])
    print('Total products:', len(products))
    btc = [p for p in products if p.get('underlying_asset', {}).get('symbol') == 'BTC']
    print('BTC products:', len(btc))
    for p in btc[:5]:
        sym = p.get('symbol', 'N/A')
        ctype = p.get('contract_type', 'N/A')
        expiry = p.get('expiry_date', 'N/A')
        print(f"  {sym} | {ctype} | expiry: {expiry}")
else:
    print('Error:', r.text[:200])
