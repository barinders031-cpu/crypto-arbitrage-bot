import time
import json
import os
import sys
import csv
from datetime import datetime, timedelta
from angel_client import AngelOneClient

def download_historical_options():
    client = AngelOneClient()
    if not client.login():
        print("Login failed! Check credentials in config.py")
        sys.exit(1)
        
    scrip_path = "scrip_master.json"
    if not os.path.exists(scrip_path):
        import urllib.request
        print("Downloading scrip master...")
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        urllib.request.urlretrieve(url, scrip_path)
        
    with open(scrip_path, 'r') as f:
        scrips = json.load(f)
        
    option_tokens = []
    
    # Filter NIFTY and SENSEX options
    for scrip in scrips:
        if scrip.get("exch_seg") == "NFO" and scrip.get("name") == "NIFTY" and scrip.get("instrumenttype") == "OPTIDX":
            option_tokens.append(scrip)
        elif scrip.get("exch_seg") == "BFO" and scrip.get("name") == "SENSEX" and scrip.get("instrumenttype") in ["OPTIDX", "OPTSTK"]:
            option_tokens.append(scrip)
            
    print(f"Total Nifty & Sensex options found in scrip master: {len(option_tokens)}")
    
    # Fetch data for the last 7 days (Angel One limits historical data for options)
    now = datetime.now()
    from_date_obj = now - timedelta(days=7)
    from_date = from_date_obj.strftime("%Y-%m-%d 09:15")
    to_date = now.strftime("%Y-%m-%d 15:30")
    
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    csv_file = f"full_historical_options_{timestamp}.csv"
    
    keys = ["token", "symbol", "exchange", "timestamp", "open", "high", "low", "close", "volume"]
    with open(csv_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        
    print(f"Starting download of FIVE_MINUTE data from {from_date} to {to_date}...")
    print(f"Note: Due to Angel One's strict 3 req/sec limit, this will take approximately {len(option_tokens)*0.35 / 60:.1f} minutes.")
    
    success_count = 0
    empty_count = 0
    error_count = 0
    
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
        
        # We wrap in a loop for minor retry logic on rate limits
        retries = 3
        while retries > 0:
            res = client.get_candle_data_throttled(params)
            
            # If rate limited (too many requests), wait and retry
            if res and not res.get("status") and "limit" in str(res.get("message", "")).lower():
                time.sleep(2)
                retries -= 1
                continue
            
            break # break while loop if request completed (success or non-rate-limit error)
            
        if res and res.get("status") and res.get("data"):
            data_list = res["data"]
            with open(csv_file, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                for row in data_list:
                    # Angel One historic format: [timestamp, open, high, low, close, volume]
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
        else:
            if res and not res.get("status"):
                error_count += 1
            else:
                empty_count += 1
                
        if (i+1) % 100 == 0:
            print(f"Processed {i+1}/{len(option_tokens)}... (Success: {success_count}, Empty: {empty_count}, Errors: {error_count})")
            
        # Respect historical API strict limit (~3 requests per second)
        time.sleep(0.35) 
        
    print(f"\nDownload Complete!")
    print(f"Total Processed: {len(option_tokens)}")
    print(f"Success (Data Found): {success_count}")
    print(f"Empty (No trades/Out of range): {empty_count}")
    print(f"Errors: {error_count}")
    print(f"All data saved securely to {csv_file}")

if __name__ == "__main__":
    download_historical_options()
