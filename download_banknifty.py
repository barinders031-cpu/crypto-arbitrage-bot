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
            current_start = current_end + datetime.timedelta(minutes=1)
            time.sleep(2)
        else:
            print("Error or empty response:", res)
            msg = res.get("message", "") if res else ""
            if msg == "Too Many Requests" or "exceeding access rate" in str(msg) or "Access denied" in str(msg):
                print("Rate limit hit, sleeping for 5 seconds and retrying...")
                time.sleep(5)
                continue
            else:
                current_start = current_end + datetime.timedelta(minutes=1)
                time.sleep(2)
        
    return all_data

# Use exact timestamps from the existing Nifty data to align the start and end dates
try:
    nifty = pd.read_csv('nifty_6m_1min.csv')
    start_date = pd.to_datetime(nifty['timestamp'].iloc[0]).replace(tzinfo=None)
    end_date = pd.to_datetime(nifty['timestamp'].iloc[-1]).replace(tzinfo=None) + datetime.timedelta(minutes=1)
except Exception as e:
    print(f"Could not load Nifty dates: {e}")
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=180)

print(f"Fetching BANKNIFTY from {start_date} to {end_date}...")
banknifty_data = fetch_data("NSE", "99926009", "ONE_MINUTE", start_date, end_date)
banknifty_df = pd.DataFrame(banknifty_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
banknifty_df.to_csv("banknifty_6m_1min.csv", index=False)
print(f"Saved {len(banknifty_df)} rows for BANKNIFTY.")
