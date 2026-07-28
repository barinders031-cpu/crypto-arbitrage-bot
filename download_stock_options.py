"""
download_stock_options.py
=========================
Robust Historical Data Downloader for Top F&O Stocks.
Downloads Spot and Options (CE & PE) data for ML Model Testing.

Features:
- Rate Limit Protection (exponential backoff)
- Dynamic Strike Detection (Top 10 nearest strikes around ATM)
- Monthly Expiry Detection for Stocks
- Output: CSV format to live_data/ directory
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
HISTORY_DAYS      = 60      # Last 60 days
TIMEFRAME         = "FIVE_MINUTE"
STRIKES_EACH_SIDE = 10      # ATM +/- 10
OUTPUT_DIR        = "live_data"

# Top 15 Highly Liquid F&O Stocks
TOP_STOCKS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "AXISBANK", "KOTAKBANK", "ITC", "LT",
    "BAJFINANCE", "BHARTIARTL", "HINDUNILVR", "ASIANPAINT", "MARUTI"
]

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

def find_cash_token(scrips, stock_name):
    """Finds the NSE cash market token for the spot price."""
    for s in scrips:
        if s.get("exch_seg") == "NSE" and s.get("name") == stock_name and (s.get("symbol", "").endswith("-EQ") or s.get("symbol") == stock_name):
            return s.get("token")
    return None

def fetch_spot_historical(client, token, symbol, from_date, to_date):
    """Fetches spot data in chunks to avoid API limits"""
    all_data = []
    current_start = datetime.strptime(from_date, "%Y-%m-%d %H:%M")
    end_dt = datetime.strptime(to_date, "%Y-%m-%d %H:%M")
    
    print(f"\n[INFO] Fetching Spot data for {symbol} ({from_date} to {to_date})")
    
    while current_start < end_dt:
        current_end = current_start + timedelta(days=30)
        if current_end > end_dt:
            current_end = end_dt
            
        params = {
            "exchange": "NSE",
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
                if "limit" in msg or "too many" in msg:
                    print(f"  [WARN] Rate limit hit on Spot fetch. Waiting 10s...")
                    time.sleep(10)
                    retries -= 1
                    continue
            break
            
        current_start = current_end + timedelta(minutes=1)
        time.sleep(1) # Safe pause
        
    return all_data

def get_active_expiry(scrips, stock_name):
    """Stock options have monthly expiries. Finds the nearest active one."""
    today = date.today()
    expiry_strs = set()
    for s in scrips:
        if s.get('instrumenttype') == 'OPTSTK' and s.get('name') == stock_name:
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
    if upcoming:
        print(f"[INFO] Targeting active monthly expiry for {stock_name}: {upcoming[0][1]}")
        return upcoming[0][1]
    return None

def find_nearest_option_tokens(scrips, stock_name, atm_price, expiry):
    """Dynamically finds the closest strikes since strike gaps vary by stock."""
    options = []
    for scrip in scrips:
        if scrip.get('instrumenttype') != 'OPTSTK' or scrip.get('name') != stock_name:
            continue
        if scrip.get('expiry', '').upper() != expiry:
            continue
            
        try:
            strike = float(scrip.get("strike", 0)) / 100.0
        except:
            continue
            
        symbol = scrip.get("symbol", "")
        opt_type = "CE" if symbol.endswith("CE") else "PE" if symbol.endswith("PE") else None
        if not opt_type:
            continue
            
        options.append({
            "token": scrip["token"],
            "symbol": symbol,
            "strike": strike,
            "opt_type": opt_type,
            "expiry": scrip.get("expiry"),
            "exch_seg": scrip.get("exch_seg"),
            "distance": abs(strike - atm_price)
        })
        
    # Separate CE and PE, sort by distance, take nearest N
    ces = sorted([o for o in options if o["opt_type"] == "CE"], key=lambda x: x["distance"])[:STRIKES_EACH_SIDE * 2]
    pes = sorted([o for o in options if o["opt_type"] == "PE"], key=lambda x: x["distance"])[:STRIKES_EACH_SIDE * 2]
    
    matched = ces + pes
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
    print("  STOCK OPTIONS DATA DOWNLOADER (ML TRAINING READY)")
    print("=" * 60)
    
    client = AngelOneClient()
    if not client.login():
        print("[ERROR] Login failed.")
        sys.exit(1)
        
    scrips = load_scrip_master()
    
    now = datetime.now()
    from_date = (now - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d 09:15")
    to_date   = now.strftime("%Y-%m-%d 15:30")
    
    for stock_name in TOP_STOCKS:
        print(f"\n{'='*40}")
        print(f" PROCESSING: {stock_name}")
        print(f"{'='*40}")
        
        # 1. Find Spot Token
        spot_token = find_cash_token(scrips, stock_name)
        if not spot_token:
            print(f"[WARN] Could not find NSE token for {stock_name}. Skipping.")
            continue
            
        # 2. Fetch Spot
        spot_file = os.path.join(OUTPUT_DIR, f"{stock_name}_spot_{HISTORY_DAYS}d.csv")
        spot_data = fetch_spot_historical(client, spot_token, stock_name, from_date, to_date)
        
        if spot_data:
            with open(spot_file, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
                w.writerows(spot_data)
            print(f"[OK] Saved {len(spot_data)} rows for {stock_name} Spot.")
        else:
            print(f"[WARN] Failed to fetch spot data for {stock_name}. Skipping options.")
            continue
            
        # 3. Get ATM & Find Options
        atm_price = spot_data[-1][4]
        print(f"[INFO] Last Traded Price (ATM base): {atm_price}")
        
        active_expiry = get_active_expiry(scrips, stock_name)
        if not active_expiry:
            print(f"[WARN] No valid expiries found for {stock_name}. Skipping.")
            continue
            
        opt_tokens = find_nearest_option_tokens(scrips, stock_name, atm_price, active_expiry)
        print(f"[INFO] Found {len(opt_tokens)} closest Option contracts to download (+/- {STRIKES_EACH_SIDE} strikes).")
        
        # 4. Download Options
        opt_file = os.path.join(OUTPUT_DIR, f"{stock_name}_options_{HISTORY_DAYS}d.csv")
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
                time.sleep(0.3) # Hard delay to prevent rate limits
                
        print(f"\n[DONE] {stock_name} Options -> Downloaded {total_rows} rows from {success}/{len(opt_tokens)} contracts.")
        print(f"[SAVED] {opt_file}")

if __name__ == "__main__":
    run()
