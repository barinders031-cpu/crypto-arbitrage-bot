"""
Deep Probe: CoinDCX Private Signed API for Futures Funding Data
"""
import urllib.request
import urllib.error
import json
import hmac
import hashlib
import time

API_KEY    = "2b28b8cad04d91128eb92048acaf2041b1249bdb13f270fe"
API_SECRET = "2fc83416123aec1d0f60fb66e5f52207cfbfee03f3a11ebc5fab4821486e036a"
BASE       = "https://api.coindcx.com"

def signed_request(method, path, body=None):
    body = body or {}
    body['timestamp'] = int(time.time() * 1000)
    body_str = json.dumps(body, separators=(',', ':'))
    sig = hmac.new(API_SECRET.encode(), body_str.encode(), hashlib.sha256).hexdigest()
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': API_KEY,
        'X-AUTH-SIGNATURE': sig,
        'User-Agent': 'Mozilla/5.0'
    }
    url = BASE + path
    req = urllib.request.Request(url, data=body_str.encode(), headers=headers, method=method)
    try:
        res = urllib.request.urlopen(req, timeout=8)
        return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        return {'http_code': e.code, 'error': e.read().decode()}
    except Exception as e:
        return {'error': str(e)}

print("=" * 90)
print("   PROBING COINDCX SIGNED API ENDPOINTS FOR FUTURES & FUNDING DATA")
print("=" * 90)

private_endpoints = [
    '/exchange/v1/derivatives/futures/positions',
    '/exchange/v1/derivatives/futures/orders/active',
    '/exchange/v1/derivatives/futures/orders/trade_history',
    '/exchange/v1/margin/funding_history',
    '/exchange/v1/margin/get_active_orders',
    '/exchange/v1/margin/trades',
    '/exchange/v1/users/balances',
    '/exchange/v1/orders/active_orders',
    '/exchange/v1/orders/trade_history',
]

for path in private_endpoints:
    res = signed_request('POST', path)
    status = "OK" if 'error' not in res or res.get('http_code') == 200 else f"ERR ({res.get('http_code')})"
    res_str = str(res)[:180]
    print(f"{path:<50} -> {status:<10} | {res_str}")

print("=" * 90)
