import time
import json
import os
import sys
import csv
from datetime import datetime, timedelta
from angel_client import AngelOneClient

def get_spot_price(client, index_name):
    if index_name == "NIFTY":
        res = client.get_ltp_data_throttled("NSE", "NIFTY", "99926000")
        if res and res.get("status") and "data" in res:
            return float(res["data"]["ltp"])
    elif index_name == "SENSEX":
        res = client.get_ltp_data_throttled("BSE", "SENSEX", "99919000")
        if res and res.get("status") and "data" in res:
            return float(res["data"]["ltp"])
    return None

def download_fast_historical_options():
    client = AngelOneClient()
    if not client.login():
        print("Login failed! Check credentials in config.py")
        sys.exit(1)
        
    nifty_spot = get_spot_price(client, "NIFTY")
    sensex_spot = get_spot_price(client, "SENSEX")
    
    if not nifty_spot: nifty_spot = 24400.0
    if not sensex_spot: sensex_spot = 80000.0
    
    print(f"NIFTY Spot: {nifty_spot}")
    print(f"SENSEX Spot: {sensex_spot}")
        
    scrip_path = "scrip_master.json"
    if not os.path.exists(scrip_path):
        import urllib.request
        print("Downloading scrip master...")
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        urllib.request.urlretrieve(url, scrip_path)
        
    with open(scrip_path, 'r') as f:
        scrips = json.load(f)
        
    option_tokens = []
    
    # Calculate ATM
    nifty_atm = round(nifty_spot / 50.0) * 50.0
    sensex_atm = round(sensex_spot / 100.0) * 100.0
    
    # Filter NIFTY and SENSEX options (+/- 10 strikes)
    for scrip in scrips:
        if scrip.get("exch_seg") == "NFO" and scrip.get("name") == "NIFTY" and scrip.get("instrumenttype") == "OPTIDX":
            try:
                strike = float(scrip.get("strike", 0)) / 100.0
                if abs(strike - nifty_atm) <= 500: # 10 strikes of 50
                    option_tokens.append(scrip)
            except:
                pass
        elif scrip.get("exch_seg") == "BFO" and scrip.get("name") == "SENSEX" and scrip.get("instrumenttype") in ["OPTIDX", "OPTSTK"]:
            try:
                strike = float(scrip.get("strike", 0)) / 100.0
                if strike < 10000: strike = float(scrip.get("strike", 0))
                if abs(strike - sensex_atm) <= 1000: # 10 strikes of 100
                    option_tokens.append(scrip)
            except:
                pass
                
    # Also append Spot tokens to fetch spot chart
    option_tokens.append({"token": "99926000", "symbol": "NIFTY_SPOT", "exch_seg": "NSE"})
    option_tokens.append({"token": "99919000", "symbol": "SENSEX_SPOT", "exch_seg": "BSE"})
            
    print(f"Total options (ATM +/- 10) + Spot indices to fetch: {len(option_tokens)}")
    
    # Fetch data for the last 7 days
    now = datetime.now()
    from_date_obj = now - timedelta(days=7)
    from_date = from_date_obj.strftime("%Y-%m-%d 09:15")
    to_date = now.strftime("%Y-%m-%d 15:30")
    
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    csv_file = f"fast_options_spot_{timestamp}.csv"
    
    keys = ["token", "symbol", "exchange", "timestamp", "open", "high", "low", "close", "volume"]
    with open(csv_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        
    print(f"Starting download of FIVE_MINUTE data from {from_date} to {to_date}...")
    
    success_count = 0
    
    for i, scrip in enumerate(option_tokens):
        token = scrip.get("token")
        symbol = scrip.get("symbol")
        exch = scrip.get("exch_seg")
        
        params = {
            "exchange": exch,
            "symboltoken": token,
            "interval": "FIVE_MINUTE",
            "fromdate": from_date,
            "todate": to_date
        }
        
        retries = 3
        while retries > 0:
            res = client.get_candle_data_throttled(params)
            if res and not res.get("status") and "limit" in str(res.get("message", "")).lower():
                time.sleep(1)
                retries -= 1
                continue
            break
            
        if res and res.get("status") and res.get("data"):
            data_list = res["data"]
            with open(csv_file, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                for row in data_list:
                    writer.writerow({
                        "token": token,
                        "symbol": symbol,
                        "exchange": exch,
                        "timestamp": row[0],
                        "open": row[1],
                        "high": row[2],
                        "low": row[3],
                        "close": row[4],
                        "volume": row[5]
                    })
            success_count += 1
                
        if (i+1) % 10 == 0:
            print(f"Processed {i+1}/{len(option_tokens)}...")
            
        time.sleep(0.35) 
        
    print(f"\nDownload Complete!")
    print(f"Total Processed: {len(option_tokens)}")
    print(f"Data saved to {csv_file}")

if __name__ == "__main__":
    download_fast_historical_options()
