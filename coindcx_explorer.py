"""
CoinDCX API Explorer - Balance + Futures Funding Rates Scanner
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
    """Signed request for private endpoints"""
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
        res = urllib.request.urlopen(req, timeout=10)
        return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        return {'error': e.read().decode(), 'code': e.code}
    except Exception as e:
        return {'error': str(e)}

def public_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        res = urllib.request.urlopen(req, timeout=10)
        return json.loads(res.read().decode())
    except Exception as e:
        return {'error': str(e)}

# =====================================================
# 1. Check Account Balance
# =====================================================
print("=" * 70)
print("  COINDCX ACCOUNT STATUS")
print("=" * 70)

bal = signed_request('POST', '/exchange/v1/users/balances')
if isinstance(bal, list):
    print("\n[+] Wallet Balances:")
    for b in bal:
        avail = float(b.get('balance', 0))
        locked = float(b.get('locked_balance', 0))
        if avail > 0 or locked > 0:
            print(f"    {b.get('currency'):10s}  Balance: {avail:.6f}  Locked: {locked:.6f}")
elif isinstance(bal, dict) and bal.get('error'):
    print(f"[ERROR] Balance: {bal}")
else:
    print(f"[?] Balance response: {bal}")

# =====================================================
# 2. Check if CoinDCX has Futures / Funding Rates
# =====================================================
print("\n[+] Checking CoinDCX Futures markets...")

# Try futures tickers
futures_tickers = public_get("https://api.coindcx.com/exchange/v1/derivatives/futures/tickers")
if isinstance(futures_tickers, list) and len(futures_tickers) > 0:
    print(f"    Found {len(futures_tickers)} futures tickers")
    sample = futures_tickers[:3]
    for s in sample:
        print(f"    Sample: {s}")
elif 'error' in str(futures_tickers):
    print(f"    Futures endpoint error: {futures_tickers}")
    
    # Try alternative endpoint
    alt = public_get("https://api.coindcx.com/exchange/v1/markets_details")
    if isinstance(alt, list):
        futures = [m for m in alt if 'futures' in m.get('coindcx_name','').lower() or 'PERP' in m.get('symbol','')]
        print(f"    Found {len(futures)} futures from markets_details")
        for f in futures[:5]:
            print(f"    {f}")

# =====================================================
# 3. Try CoinDCX Futures specific API
# =====================================================
print("\n[+] Trying CoinDCX Futures funding rates API...")
endpoints_to_try = [
    "https://api.coindcx.com/exchange/v1/derivatives/futures/funding_rates",
    "https://api.coindcx.com/exchange/v1/derivatives/ticker",
    "https://api.coindcx.com/exchange/v1/futures/tickers",
    "https://futures-api.coindcx.com/api/v1/tickers",
]
for ep in endpoints_to_try:
    res = public_get(ep)
    if 'error' not in str(res)[:100]:
        print(f"\n  [OK] {ep}")
        if isinstance(res, list):
            print(f"       {len(res)} items. Sample: {res[:2]}")
        else:
            print(f"       Response: {str(res)[:300]}")
    else:
        print(f"  [X]  {ep} -> {str(res)[:80]}")
