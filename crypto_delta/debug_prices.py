"""Debug option prices."""
import requests

# Check if there's a ticker for options
symbol = 'C-BTC-67500-070826'
r = requests.get(f'https://api.india.delta.exchange/v2/tickers/{symbol}', timeout=5)
print('Ticker status:', r.status_code)
if r.status_code == 200:
    data = r.json()
    print('Ticker data:', data)
else:
    print('Error:', r.text[:200])

# Check orderbook
r2 = requests.get(f'https://api.india.delta.exchange/v2/l2orderbook/{symbol}', timeout=5)
print('\nOrderbook status:', r2.status_code)
if r2.status_code == 200:
    data2 = r2.json()
    result = data2.get('result', {})
    print('Bid:', result.get('buy', [])[:2])
    print('Ask:', result.get('sell', [])[:2])
else:
    print('Error:', r2.text[:200])
