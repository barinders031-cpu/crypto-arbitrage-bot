"""
download_weekly_options.py
==========================
Angel One SmartAPI se Nifty Weekly Options ka 5-minute historical data download karta hai.

What it downloads:
  - Current week + next 2 weekly expiries (Thu/Wed expiry series)
  - ATM +/- 15 strikes (50-point gap) = 31 CE + 31 PE strikes per expiry
  - Timeframe: 5-minute OHLCV
  - History: Last 60 days (enough for multiple weekly cycles)

Output file: weekly_nifty_options_<date>.csv
"""

import time
import json
import os
import sys
import csv
import re
from datetime import datetime, timedelta, date
from angel_client import AngelOneClient

# ============================================================
# CONFIG
# ============================================================
STRIKES_EACH_SIDE  = 15      # ATM +/- 15 strikes (31 total)
NIFTY_STRIKE_GAP   = 50      # Nifty option strike interval
HISTORY_DAYS       = 60      # Download last 60 days of history
TIMEFRAME          = "FIVE_MINUTE"
OUTPUT_FILE        = f"weekly_nifty_options_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# ============================================================
# STEP 1: GET CURRENT NIFTY SPOT PRICE
# ============================================================
def get_nifty_spot(client):
    res = client.get_ltp_data_throttled("NSE", "NIFTY", "99926000")
    if res and res.get("status") and "data" in res:
        return float(res["data"]["ltp"])
    print("[WARN] Could not fetch live spot — using fallback 24500")
    return 24500.0

# ============================================================
# STEP 2: FIND WEEKLY EXPIRY DATES
# Nifty weekly options expire every Thursday (or Wednesday if Thu is holiday)
# ============================================================
def get_upcoming_weekly_expiries(scrips, n=3):
    """
    Read actual available Nifty weekly expiry dates directly from the scrip master.
    Returns next n expiries from today (any weekday — Angel One determines the actual day).
    """
    from datetime import date
    today = date.today()

    # Collect all Nifty OPTIDX expiry strings
    expiry_strs = set()
    for s in scrips:
        if (s.get('exch_seg') == 'NFO' and
            s.get('name') == 'NIFTY' and
            s.get('instrumenttype') == 'OPTIDX'):
            exp = s.get('expiry', '')
            if exp:
                expiry_strs.add(exp)

    # Parse to date objects and filter to upcoming dates
    upcoming = []
    for exp_str in expiry_strs:
        try:
            exp_date = datetime.strptime(exp_str, "%d%b%Y").date()
            if exp_date >= today:
                upcoming.append((exp_date, exp_str))
        except:
            pass

    # Sort by date, take next n
    upcoming.sort(key=lambda x: x[0])
    result = upcoming[:n]
    print(f"[INFO] Available weekly expiries from scrip master: {[r[1] for r in result]}")
    return result  # List of (date, expiry_str) tuples

# ============================================================
# STEP 3: LOAD SCRIP MASTER & FIND WEEKLY OPTION TOKENS
# ============================================================
def load_scrip_master():
    scrip_path = "scrip_master.json"
    if not os.path.exists(scrip_path):
        import urllib.request
        print("[INFO] Downloading scrip master from Angel One...")
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        urllib.request.urlretrieve(url, scrip_path)
        print(f"[OK] Scrip master saved: {scrip_path}")
    else:
        age_hours = (time.time() - os.path.getmtime(scrip_path)) / 3600
        if age_hours > 12:
            print(f"[INFO] Scrip master is {age_hours:.1f}h old. Refreshing...")
            import urllib.request
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            urllib.request.urlretrieve(url, scrip_path)
    with open(scrip_path, 'r') as f:
        return json.load(f)

def find_weekly_option_tokens(scrips, atm_strike, expiry_tuples):
    """
    Filter scrip master for Nifty OPTIDX options matching:
      - Target expiries (from scrip master itself)
      - Strike within ATM +/- STRIKES_EACH_SIDE
    Strike stored as actual_strike * 100 (e.g. 24050 -> 2405000.0)
    """
    matched = []
    expiry_set = set(exp_str for _, exp_str in expiry_tuples)
    print(f"[DEBUG] Matching against expiries: {expiry_set}")

    for scrip in scrips:
        if (scrip.get("exch_seg") != "NFO" or
            scrip.get("name") != "NIFTY" or
            scrip.get("instrumenttype") != "OPTIDX"):
            continue

        scrip_expiry = scrip.get("expiry", "").upper()
        if scrip_expiry not in expiry_set:
            continue

        try:
            strike = float(scrip.get("strike", 0)) / 100.0
        except:
            continue

        if abs(strike - atm_strike) > (STRIKES_EACH_SIDE * NIFTY_STRIKE_GAP):
            continue

        symbol   = scrip.get("symbol", "")
        opt_type = "CE" if symbol.endswith("CE") else "PE" if symbol.endswith("PE") else None
        if opt_type is None:
            continue

        matched.append({
            "token":    scrip["token"],
            "symbol":   symbol,
            "strike":   strike,
            "opt_type": opt_type,
            "expiry":   scrip_expiry,
            "exch_seg": "NFO"
        })

    return matched

# ============================================================
# STEP 4: FETCH HISTORICAL DATA FROM ANGEL ONE
# ============================================================
def fetch_historical(client, token, exchange, from_date, to_date, timeframe):
    params = {
        "exchange":    exchange,
        "symboltoken": token,
        "interval":    timeframe,
        "fromdate":    from_date,
        "todate":      to_date
    }
    retries = 3
    while retries > 0:
        try:
            res = client.get_candle_data_throttled(params)
            # Retry on rate-limit
            if res and not res.get("status") and "limit" in str(res.get("message", "")).lower():
                time.sleep(1)
                retries -= 1
                continue
            if res and res.get("status") and res.get("data"):
                return res["data"]
            break
        except Exception as e:
            retries -= 1
            time.sleep(0.5)
    return []

# ============================================================
# MAIN DOWNLOAD ROUTINE
# ============================================================
def download_weekly_options():
    print("=" * 60)
    print("  WEEKLY OPTIONS DOWNLOADER — Angel One SmartAPI")
    print("=" * 60)

    # Login
    client = AngelOneClient()
    if not client.login():
        print("[ERROR] Login failed. Check config.py credentials.")
        sys.exit(1)
    print("[OK] Angel One login successful.")

    # Get spot & ATM
    nifty_spot = get_nifty_spot(client)
    atm_strike = round(nifty_spot / NIFTY_STRIKE_GAP) * NIFTY_STRIKE_GAP
    print(f"[INFO] Nifty Spot: {nifty_spot:.2f} | ATM Strike: {atm_strike}")

    # Load scrip master
    scrips = load_scrip_master()

    # Get actual weekly expiry dates from scrip master (not guessed from weekday)
    expiry_tuples = get_upcoming_weekly_expiries(scrips, n=3)
    print(f"[INFO] Using expiries: {[e[1] for e in expiry_tuples]}")

    # Find matching tokens
    tokens = find_weekly_option_tokens(scrips, atm_strike, expiry_tuples)
    print(f"[INFO] Weekly option contracts found: {len(tokens)}")

    if not tokens:
        print("[WARN] No weekly tokens found in scrip master.")
        print("       Possible reasons: Market is closed / Expiry not yet listed")
        print("       Try refreshing scrip_master.json by deleting it and re-running.")
        return

    # Date range for history
    now = datetime.now()
    from_date = (now - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d 09:15")
    to_date   = now.strftime("%Y-%m-%d 15:30")
    print(f"[INFO] Fetching data: {from_date} to {to_date} | Timeframe: {TIMEFRAME}")
    print(f"[INFO] Output file: {OUTPUT_FILE}")
    print("-" * 60)

    # Download & write
    total_rows = 0
    success_count = 0
    fail_count = 0

    with open(OUTPUT_FILE, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["token", "symbol", "strike", "opt_type", "expiry",
                         "timestamp", "open", "high", "low", "close", "volume"])

        for i, scrip in enumerate(tokens):
            token   = scrip["token"]
            symbol  = scrip["symbol"]
            strike  = scrip["strike"]
            otype   = scrip["opt_type"]

            # Parse expiry from symbol
            exp_match = re.search(r'NIFTY(\d{2}[A-Z]{3}\d{2,4})', symbol)
            expiry_label = exp_match.group(1) if exp_match else "UNKNOWN"

            candles = fetch_historical(
                client, token, "NFO", from_date, to_date, TIMEFRAME
            )

            if candles:
                for candle in candles:
                    writer.writerow([
                        token, symbol, strike, otype, expiry_label,
                        candle[0], candle[1], candle[2], candle[3], candle[4], candle[5]
                    ])
                total_rows += len(candles)
                success_count += 1
                status = f"OK ({len(candles)} bars)"
            else:
                fail_count += 1
                status = "NO DATA"

            pct = ((i + 1) / len(tokens)) * 100
            print(f"  [{i+1:>3}/{len(tokens)}] {symbol:<30} {status}")

            time.sleep(0.15)  # Rate limit: ~6-7 req/sec (Angel One allows 10/sec)

    print("\n" + "=" * 60)
    print(f"  DOWNLOAD COMPLETE")
    print(f"  Contracts Attempted : {len(tokens)}")
    print(f"  Success             : {success_count}")
    print(f"  Failed / No Data    : {fail_count}")
    print(f"  Total Rows Saved    : {total_rows:,}")
    print(f"  Output File         : {OUTPUT_FILE}")
    print("=" * 60)

if __name__ == "__main__":
    download_weekly_options()
