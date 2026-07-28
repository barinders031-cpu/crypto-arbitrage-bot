"""
download_1min_indices.py
========================
Robust Historical Data Downloader for NIFTY & SENSEX (1-Minute).
Downloads Spot and Options (CE & PE) data.

Features:
- Rate Limit Protection
- 1-Minute timeframe for the last 30 days
- Major Indices: NIFTY, SENSEX
- Options: ATM +/- 15 strikes, current and next expiry
"""

import time
import json
import os
import sys
import csv
from datetime import datetime, timedelta, date
from angel_client import AngelOneClient

# ============================================================
# CONFIGURATION
# ============================================================
HISTORY_DAYS      = 30      # Max 30 days for 1-minute data usually allowed by Angel One
TIMEFRAME         = "ONE_MINUTE"
STRIKES_EACH_SIDE = 15      # ATM +/- 15
OUTPUT_DIR        = "live_data" 

# Target Indices
INDICES = {
    "NIFTY":  {"exch": "NSE", "token": "99926000", "gap": 50},
    "SENSEX": {"exch": "BSE", "token": "99919000", "gap": 100}
}

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# ============================================================
# UTILITY FUNCTIONS
# ============================================================
def load_scrip_master():
    scrip_path = "scrip_master.json"
    if not os.path.exists(scrip_path) or (time.time() - os.path.getmtime(scrip_path)) / 3600 > 12:
        print("[INFO] Downloading / Refreshing scrip master...")
        import urllib.request
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        urllib.request.urlretrieve(url, scrip_path)
    with open(scrip_path, 'r') as f:
        return json.load(f)

def fetch_spot_historical(client, exchange, token, symbol, from_date, to_date):
    """Fetches spot data in chunks to avoid API limits on long ranges"""
    all_data = []
    current_start = datetime.strptime(from_date, "%Y-%m-%d %H:%M")
    end_dt = datetime.strptime(to_date, "%Y-%m-%d %H:%M")
    
    print(f"\n[INFO] Fetching Spot data for {symbol} ({from_date} to {to_date}) at {TIMEFRAME}")
    
    while current_start < end_dt:
        current_end = current_start + timedelta(days=15) # Shorter chunks for 1-min data
        if current_end > end_dt:
            current_end = end_dt
            
        params = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": TIMEFRAME,
            "fromdate": current_start.strftime("%Y-%m-%d %H:%M"),
            "todate": current_end.strftime("%Y-%m-%d %H:%M")
        }
        
        retries = 5
        while retries > 0:
            res = client.get_candle_data_throttled(params)
            if res and res.get("status") and res.get("data"):
                all_data.extend(res["data"])
                break
            elif res and not res.get("status"):
                msg = str(res.get("message", "")).lower()
                if "limit" in msg or "too many" in msg or "access" in msg:
                    print(f"  [WARN] Rate limit hit on Spot fetch. Waiting 10s...")
                    time.sleep(10)
                    retries -= 1
                    continue
            break
            
        current_start = current_end + timedelta(minutes=1)
        time.sleep(1)
        
    return all_data

def get_upcoming_expiries(scrips, underlying_name, n=2):
    today = date.today()
    expiry_strs = set()
    for s in scrips:
        if s.get('instrumenttype') == 'OPTIDX' and s.get('name') == underlying_name:
            exp = s.get('expiry', '')
            if exp:
                expiry_strs.add(exp)
                
    upcoming = []
    for exp_str in expiry_strs:
        try:
            exp_date = datetime.strptime(exp_str, "%d%b%Y").date()
            if exp_date >= today:
                upcoming.append((exp_date, exp_str))
        except:
            pass
            
    upcoming.sort(key=lambda x: x[0])
    result = [x[1] for x in upcoming[:n]]
    print(f"[INFO] Targeting expiries for {underlying_name}: {result}")
    return result

def get_atm_strike(spot_data, gap):
    if not spot_data:
        return 0
    last_close = spot_data[-1][4]
    return round(last_close / gap) * gap

def find_option_tokens(scrips, underlying, atm_strike, gap, expiries):
    matched = []
    for scrip in scrips:
        if scrip.get('instrumenttype') != 'OPTIDX' or scrip.get('name') != underlying:
            continue
        if scrip.get('expiry', '').upper() not in expiries:
            continue
            
        try:
            strike = float(scrip.get("strike", 0)) / 100.0
        except:
            continue
            
        if abs(strike - atm_strike) > (STRIKES_EACH_SIDE * gap):
            continue
            
        symbol = scrip.get("symbol", "")
        opt_type = "CE" if symbol.endswith("CE") else "PE" if symbol.endswith("PE") else None
        if not opt_type:
            continue
            
        matched.append({
            "token": scrip["token"],
            "symbol": symbol,
            "strike": strike,
            "opt_type": opt_type,
            "expiry": scrip.get("expiry"),
            "exch_seg": scrip.get("exch_seg")
        })
    return matched

def fetch_option_historical(client, exch, token, from_date, to_date):
    params = {
        "exchange": exch,
        "symboltoken": token,
        "interval": TIMEFRAME,
        "fromdate": from_date,
        "todate": to_date
    }
    retries = 5
    backoff = 2
    while retries > 0:
        res = client.get_candle_data_throttled(params)
        if res and res.get("status") and res.get("data"):
            return res["data"]
        elif res and not res.get("status"):
            msg = str(res.get("message", "")).lower()
            if "limit" in msg or "too many requests" in msg:
                print(f"    [RATE LIMIT] Waiting {backoff}s before retry...")
                time.sleep(backoff)
                backoff *= 2
                retries -= 1
                continue
        break 
    return []

# ============================================================
# MAIN EXECUTION
# ============================================================
def run():
    print("=" * 60)
    print("  1-MINUTE INDICES DATA DOWNLOADER (NIFTY & SENSEX) ")
    print("=" * 60)
    
    client = AngelOneClient()
    if not client.login():
        print("[ERROR] Login failed.")
        sys.exit(1)
        
    scrips = load_scrip_master()
    
    now = datetime.now()
    from_date = (now - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d 09:15")
    to_date   = now.strftime("%Y-%m-%d 15:30")
    
    for idx_name, info in INDICES.items():
        print(f"\n{'='*40}")
        print(f" PROCESSING: {idx_name} (1-MINUTE DATA)")
        print(f"{'='*40}")
        
        # 1. Fetch Spot
        spot_file = os.path.join(OUTPUT_DIR, f"{idx_name}_spot_{HISTORY_DAYS}d_1min.csv")
        spot_data = fetch_spot_historical(client, info["exch"], info["token"], idx_name, from_date, to_date)
        
        if spot_data:
            with open(spot_file, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
                w.writerows(spot_data)
            print(f"[OK] Saved {len(spot_data)} rows for {idx_name} Spot.")
        else:
            print(f"[WARN] Failed to fetch spot data for {idx_name}. Skipping options.")
            continue
            
        # 2. Get ATM & Find Tokens
        atm_strike = get_atm_strike(spot_data, info["gap"])
        print(f"[INFO] Calculated ATM Strike: {atm_strike}")
        
        expiries = get_upcoming_expiries(scrips, idx_name, n=2)
        if not expiries:
            print(f"[WARN] No expiries found for {idx_name}. Skipping.")
            continue
            
        opt_tokens = find_option_tokens(scrips, idx_name, atm_strike, info["gap"], expiries)
        print(f"[INFO] Found {len(opt_tokens)} Option contracts to download.")
        
        # 3. Download Options
        opt_file = os.path.join(OUTPUT_DIR, f"{idx_name}_options_{HISTORY_DAYS}d_1min.csv")
        success = 0
        total_rows = 0
        
        with open(opt_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["token", "symbol", "strike", "opt_type", "expiry", 
                        "timestamp", "open", "high", "low", "close", "volume"])
            
            for i, tok_info in enumerate(opt_tokens):
                c_data = fetch_option_historical(client, tok_info["exch_seg"], tok_info["token"], from_date, to_date)
                if c_data:
                    for row in c_data:
                        w.writerow([
                            tok_info["token"], tok_info["symbol"], tok_info["strike"], 
                            tok_info["opt_type"], tok_info["expiry"],
                            row[0], row[1], row[2], row[3], row[4], row[5]
                        ])
                    success += 1
                    total_rows += len(c_data)
                    status = f"OK ({len(c_data)} bars)"
                else:
                    status = "FAIL / NO DATA"
                    
                print(f"  [{i+1:>3}/{len(opt_tokens)}] {tok_info['symbol']:<30} {status}")
                time.sleep(0.3) 
                
        print(f"\n[DONE] {idx_name} Options -> Downloaded {total_rows} rows from {success}/{len(opt_tokens)} contracts.")
        print(f"[SAVED] {opt_file}")

if __name__ == "__main__":
    run()
