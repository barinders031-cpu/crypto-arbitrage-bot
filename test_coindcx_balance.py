"""
CoinDCX Deep Futures Balance Finder: Find the endpoint that returns 9.31 USDT
"""
import urllib.request, urllib.error, json, hmac, hashlib, time, gzip, os
try:
    from dotenv import load_dotenv; load_dotenv()
except: pass

API_KEY    = os.getenv("COINDCX_API_KEY",    "2b28b8cad04d91128eb92048acaf2041b1249bdb13f270fe")
API_SECRET = os.getenv("COINDCX_API_SECRET", "2fc83416123aec1d0f60fb66e5f52207cfbfee03f3a11ebc5fab4821486e036a")
BASE       = "https://api.coindcx.com"

print(f"Testing CoinDCX API Key: {API_KEY[:12]}...")

def signed_post(path, extra_payload=None):
    payload = extra_payload or {}
    payload["timestamp"] = int(time.time() * 1000)
    body_str = json.dumps(payload, separators=(",", ":"))
    sig = hmac.new(API_SECRET.encode(), body_str.encode(), hashlib.sha256).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": API_KEY,
        "X-AUTH-SIGNATURE": sig,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
    }
    
    req = urllib.request.Request(BASE + path, data=body_str.encode(), headers=headers, method="POST")
    try:
        res = urllib.request.urlopen(req, timeout=12)
        raw = res.read()
        try: text = raw.decode("utf-8")
        except: text = gzip.decompress(raw).decode("utf-8")
        return res.status, json.loads(text)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: text = raw.decode("utf-8")
        except:
            try: text = gzip.decompress(raw).decode("utf-8")
            except: text = str(raw[:150])
        return e.code, text
    except Exception as e:
        return 0, str(e)

# List of all possible endpoints from CoinDCX documentation, web app, and derivatives API
futures_endpoints = [
    "/exchange/v1/derivatives/futures/wallets",
    "/exchange/v1/derivatives/futures/wallet",
    "/exchange/v1/derivatives/futures/balances",
    "/exchange/v1/derivatives/futures/account",
    "/exchange/v1/derivatives/futures/positions",
    "/exchange/v1/derivatives/futures/users/info",
    "/exchange/v1/derivatives/futures/orders/active",
    "/exchange/v1/derivatives/futures/trade_history",
    "/exchange/v1/derivatives/futures/user/margin",
    "/exchange/v1/margin/user_info",
    "/exchange/v1/margin/balances",
    "/exchange/v1/users/balances",
]

print("\n" + "="*80)
print(f"{'ENDPOINT':<50} {'STATUS':<8} {'RESPONSE'}")
print("="*80)

for path in futures_endpoints:
    time.sleep(0.5)
    code, resp = signed_post(path)
    resp_str = str(resp).replace("\n", " ")[:120]
    status_str = f"OK {code}" if code in (200, 201) else f"ERR {code}"
    print(f"{path:<50} {status_str:<8} {resp_str}")
    if code in (200, 201) and ("9.31" in str(resp) or "USDT" in str(resp) or "margin" in str(resp)):
        print(f"   >>> TARGET MATCH FOUND IN {path}: {resp}")

print("="*80)
