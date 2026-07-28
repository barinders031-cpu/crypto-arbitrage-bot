"""
Delta Exchange DEMO - Check exact margin, funding rates, and place working Futures Short
"""
import urllib.request
import json
import time
import hmac
import hashlib
import os

DEMO_BASE_URL = "https://cdn-ind.testnet.deltaex.org"
API_KEY = "bZIwAB5Q1FM5nTflbg4CWNmYaDt7pI"
API_SECRET = "v8eGb9IFsW1gR8P4TL5sMnjX7hQvOLTNxKsaUGTnzAGaGMALcwxUYu6K3im0"

def send_signed_request(method, path, payload=None):
    timestamp = str(int(time.time()))
    body_str = json.dumps(payload) if payload else ""
    message = method + timestamp + path + body_str
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    headers = {'Content-Type': 'application/json', 'api-key': API_KEY, 'timestamp': timestamp, 'signature': signature, 'User-Agent': 'Mozilla/5.0'}
    url = DEMO_BASE_URL + path
    data_bytes = body_str.encode() if payload else None
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        res = urllib.request.urlopen(req, timeout=10)
        return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        return {'success': False, 'error': json.loads(e.read().decode())}

def get_public(path):
    url = DEMO_BASE_URL + path
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode())

# 1. Check Balance
print("=== DEMO ACCOUNT BALANCE ===")
bal = send_signed_request('GET', '/v2/wallet/balances')
if bal.get('success'):
    for a in bal.get('result', []):
        avail = float(a.get('available_balance', 0))
        if avail > 0:
            print(f"  {a.get('asset_symbol'):10s}: {avail:.4f}")
else:
    print("Balance error:", bal)

# 2. Check Live Funding Rates for BTC and ETH
print("\n=== LIVE FUNDING RATES ===")
tickers = get_public('/v2/tickers').get('result', [])
for t in tickers:
    if t.get('symbol') in ['BTCUSD', 'ETHUSD']:
        rate = float(t.get('funding_rate') or 0) * 100.0
        mark = float(t.get('mark_price') or 0)
        print(f"  {t['symbol']}: Mark=${mark:.2f} | 8H Funding Rate: {rate:.4f}%")

# 3. Get Margin Required for 1 Lot BTC Short
print("\n=== MARGIN REQUIRED FOR 1 LOT BTCUSD SHORT ===")
margin_res = send_signed_request('GET', '/v2/products/14/margin_requirements?size=1&side=sell')
print(margin_res)

# 4. Try placing 1 Lot BTCUSD Futures Short
print("\n=== PLACING 1 LOT BTCUSD SHORT (Futures) ===")
order_res = send_signed_request('POST', '/v2/orders', {
    "product_id": 14,  # BTCUSD product ID
    "size": 1,
    "side": "sell",
    "order_type": "market_order"
})
print(order_res)
