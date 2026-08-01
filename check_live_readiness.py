"""
Pre-Flight Diagnostic & Live Execution Readiness Checker
========================================================
Tests API authentication, environment parsing, and outputs required Render Dashboard variables.
"""
import os
import sys
import json
import time
import hmac
import hashlib
import urllib.request
import urllib.error

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

print("=" * 80)
print("     PRE-FLIGHT LIVE EXECUTION READINESS CHECKER")
print("=" * 80)

# 1. LIVE_EXECUTION Boolean Parsing Test
raw_live_env = os.getenv("LIVE_EXECUTION", "false")
is_live_parsed = raw_live_env.strip().lower() in ("true", "1", "yes")

print(f"\n[1] ENVIRONMENT LIVE FLAG PARSING:")
print(f"    Raw LIVE_EXECUTION Env Var : '{raw_live_env}'")
print(f"    Parsed Live Mode Enabled  : {is_live_parsed}")

try:
    my_public_ip = urllib.request.urlopen('https://api.ipify.org', timeout=5).read().decode().strip()
except Exception:
    my_public_ip = "Unable to fetch"

print(f"\n[1.1] SYSTEM OUTBOUND PUBLIC IP:")
print(f"    Current Public IP Address : {my_public_ip}")

# 2. API Credentials Check
delta_key = os.getenv("DELTA_API_KEY", "")
delta_sec = os.getenv("DELTA_API_SECRET", "")
coindcx_key = os.getenv("COINDCX_API_KEY", "")
coindcx_sec = os.getenv("COINDCX_API_SECRET", "")

print(f"\n[2] API CREDENTIALS PRESENT IN ENV:")
print(f"    DELTA_API_KEY      : {'Configured (' + delta_key[:8] + '...)' if delta_key else 'MISSING ❌'}")
print(f"    DELTA_API_SECRET   : {'Configured (' + delta_sec[:8] + '...)' if delta_sec else 'MISSING ❌'}")
print(f"    COINDCX_API_KEY    : {'Configured (' + coindcx_key[:8] + '...)' if coindcx_key else 'MISSING ❌'}")
print(f"    COINDCX_API_SECRET : {'Configured (' + coindcx_sec[:8] + '...)' if coindcx_sec else 'MISSING ❌'}")

# 3. Delta Exchange India Auth Test
print(f"\n[3] DELTA EXCHANGE INDIA AUTHENTICATION TEST:")
delta_auth_status = "FAIL"
delta_auth_msg = ""

if delta_key and delta_sec:
    try:
        base = "https://api.india.delta.exchange"
        path = "/v2/wallet/balances"
        method = "GET"
        ts = str(int(time.time()))
        msg = method + ts + path
        sig = hmac.new(delta_sec.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest()
        
        headers = {
            "api-key": delta_key,
            "signature": sig,
            "timestamp": ts,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        
        req = urllib.request.Request(base + path, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode())
            if data.get("success"):
                delta_auth_status = "PASS"
                delta_auth_msg = f"Authenticated successfully! Result: {data.get('result', [])[:2]}"
            else:
                delta_auth_status = "FAIL"
                delta_auth_msg = str(data)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        delta_auth_status = "FAIL"
        delta_auth_msg = f"HTTP {e.code}: {raw}"
    except Exception as e:
        delta_auth_status = "FAIL"
        delta_auth_msg = str(e)
else:
    delta_auth_msg = "API Key or Secret missing"

print(f"    DELTA AUTH STATUS : {delta_auth_status}")
print(f"    Details          : {delta_auth_msg}")

# 4. CoinDCX Futures Auth Test
print(f"\n[4] COINDCX FUTURES AUTHENTICATION TEST:")
coindcx_auth_status = "FAIL"
coindcx_auth_msg = ""

if coindcx_key and coindcx_sec:
    try:
        base = "https://api.coindcx.com"
        path = "/exchange/v1/derivatives/futures/positions"
        ts = int(time.time() * 1000)
        body = json.dumps({"timestamp": ts}, separators=(",", ":"))
        sig = hmac.new(coindcx_sec.encode('utf-8'), body.encode('utf-8'), hashlib.sha256).hexdigest()
        
        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": coindcx_key,
            "X-AUTH-SIGNATURE": sig,
            "User-Agent": "Mozilla/5.0"
        }
        
        req = urllib.request.Request(base + path, data=body.encode('utf-8'), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode())
            if isinstance(data, list):
                coindcx_auth_status = "PASS"
                coindcx_auth_msg = f"Authenticated successfully! Active position items: {len(data)}"
            else:
                coindcx_auth_status = "PASS"
                coindcx_auth_msg = str(data)[:100]
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        coindcx_auth_status = "FAIL"
        coindcx_auth_msg = f"HTTP {e.code}: {raw}"
    except Exception as e:
        coindcx_auth_status = "FAIL"
        coindcx_auth_msg = str(e)
else:
    coindcx_auth_msg = "API Key or Secret missing"

print(f"    COINDCX AUTH STATUS : {coindcx_auth_status}")
print(f"    Details            : {coindcx_auth_msg}")

# 5. Render.com Required Environment Variables List
print("\n" + "=" * 80)
print("     REQUIRED ENVIRONMENT VARIABLES FOR RENDER.COM DASHBOARD")
print("=" * 80)
render_vars = [
    ("LIVE_EXECUTION",          "true",                                                            "Master toggle to enable real order execution"),
    ("DELTA_API_KEY",           delta_key if delta_key else "your_delta_key",                      "Delta Exchange India API Key"),
    ("DELTA_API_SECRET",        delta_sec if delta_sec else "your_delta_secret",                  "Delta Exchange India API Secret"),
    ("COINDCX_API_KEY",         coindcx_key if coindcx_key else "your_coindcx_key",                "CoinDCX Futures API Key"),
    ("COINDCX_API_SECRET",      coindcx_sec if coindcx_sec else "your_coindcx_secret",            "CoinDCX Futures API Secret"),
    ("MARGIN_PER_EXCHANGE_USD", "10",                                                              "USD margin allocated per exchange leg"),
    ("MIN_GROSS_SPREAD_PCT",    "0.15",                                                            "Minimum Gross Funding Spread % requirement"),
    ("PORT",                    "5050",                                                            "HTTP Web Port for dashboard & ping endpoints")
]

print(f"{'VAR NAME':<26} {'VALUE / TEMPLATE':<32} {'DESCRIPTION'}")
print("-" * 80)
for name, val, desc in render_vars:
    disp_val = (val[:25] + "...") if len(val) > 28 else val
    print(f"{name:<26} {disp_val:<32} {desc}")
print("=" * 80)
