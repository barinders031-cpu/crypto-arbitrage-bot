import sys
import datetime
import pandas as pd
import time
from angel_client import AngelOneClient

client = AngelOneClient()
if not client.login():
    print("Login failed")
    sys.exit(1)

def fetch_data(exchange, symboltoken, interval, start_dt, end_dt):
    all_data = []
    current_start = start_dt
    
    while current_start < end_dt:
        current_end = current_start + datetime.timedelta(days=30)
        if current_end > end_dt:
            current_end = end_dt
            
        req_data = {
            "exchange": exchange,
            "symboltoken": symboltoken,
            "interval": interval,
            "fromdate": current_start.strftime("%Y-%m-%d %H:%M"),
            "todate": current_end.strftime("%Y-%m-%d %H:%M")
        }
        
        print(f"Fetching {symboltoken} from {req_data['fromdate']} to {req_data['todate']}")
        res = client.get_candle_data_throttled(req_data)
        
        if res and res.get("status") and res.get("data"):
            all_data.extend(res["data"])
            current_start = current_end + datetime.timedelta(minutes=5)
            time.sleep(2)
        else:
            print("Error or empty response:", res)
            msg = res.get("message", "") if res else ""
            if msg == "Too Many Requests" or "exceeding access rate" in str(msg) or "Access denied" in str(msg):
                print("Rate limit hit, sleeping for 5 seconds and retrying...")
                time.sleep(5)
                continue
            else:
                current_start = current_end + datetime.timedelta(minutes=5)
                time.sleep(2)
        
    return all_data

if __name__ == '__main__':
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=180) # ~6 months
    
    symbols = {
        "NIFTY": ("NSE", "99926000"),
        "SENSEX": ("BSE", "99919000"),
        "BANKNIFTY": ("NSE", "99926009")
    }
    
    for name, (exch, token) in symbols.items():
        print(f"\n--- Downloading 5-Minute Data for {name} ---")
        data = fetch_data(exch, token, "FIVE_MINUTE", start_date, end_date)
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        filename = f"{name.lower()}_6m_5min.csv"
        df.to_csv(filename, index=False)
        print(f"Saved {len(df)} rows for {name} to {filename}")

