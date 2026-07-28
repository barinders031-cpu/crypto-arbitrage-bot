"""
Probe all possible subpaths under /exchange/v1/derivatives/futures/
"""
import urllib.request
import json
import hmac
import hashlib
import time

API_KEY    = "2b28b8cad04d91128eb92048acaf2041b1249bdb13f270fe"
API_SECRET = "2fc83416123aec1d0f60fb66e5f52207cfbfee03f3a11ebc5fab4821486e036a"
BASE       = "https://api.coindcx.com"

def test_endpoint(path, method='POST'):
    timestamp = str(int(time.time() * 1000))
    body = {'timestamp': int(timestamp)}
    body_str = json.dumps(body, separators=(',', ':'))
    sig = hmac.new(API_SECRET.encode(), body_str.encode(), hashlib.sha256).hexdigest()
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': API_KEY,
        'X-AUTH-SIGNATURE': sig,
        'User-Agent': 'Mozilla/5.0'
    }
    url = BASE + path
    req = urllib.request.Request(url, data=body_str.encode() if method=='POST' else None, headers=headers, method=method)
    try:
        res = urllib.request.urlopen(req, timeout=5)
        return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.read().decode()[:100]}"
    except Exception as e:
        return str(e)

subpaths = [
    '/exchange/v1/derivatives/futures/wallets',
    '/exchange/v1/derivatives/futures/account',
    '/exchange/v1/derivatives/futures/info',
    '/exchange/v1/derivatives/futures/funding',
    '/exchange/v1/derivatives/futures/funding_history',
    '/exchange/v1/derivatives/futures/user_trades',
    '/exchange/v1/derivatives/futures/data/funding',
    '/exchange/v1/derivatives/futures/data/funding_history',
    '/exchange/v1/derivatives/futures/data/tickers',
    '/exchange/v1/derivatives/futures/data/instrument_info',
]

for p in subpaths:
    res_post = test_endpoint(p, 'POST')
    res_get = test_endpoint(p, 'GET')
    print(f"{p:<55} | POST: {str(res_post)[:60]} | GET: {str(res_get)[:60]}")
