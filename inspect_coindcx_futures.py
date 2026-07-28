"""
Inspect CoinDCX Futures Positions data structure
"""
import urllib.request
import json
import hmac
import hashlib
import time

API_KEY    = "2b28b8cad04d91128eb92048acaf2041b1249bdb13f270fe"
API_SECRET = "2fc83416123aec1d0f60fb66e5f52207cfbfee03f3a11ebc5fab4821486e036a"
BASE       = "https://api.coindcx.com"

def signed_request(path, body=None):
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
    req = urllib.request.Request(url, data=body_str.encode(), headers=headers, method='POST')
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode())

positions = signed_request('/exchange/v1/derivatives/futures/positions')
print(f"Total Futures Positions returned by CoinDCX: {len(positions)}")
if positions:
    print("\nKeys in Futures position dict:")
    print(list(positions[0].keys()))
    print("\nSample Position item:")
    print(json.dumps(positions[0], indent=2))
