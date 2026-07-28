import pyotp
import config
import time
import datetime
import pandas as pd
import numpy as np
from SmartApi import SmartConnect

print("=" * 60)
print("  ANGEL ONE REAL NIFTY DATA UPDATER (WITH RETRY & RATE-LIMIT CONTROL)")
print("=" * 60)

# 1. Login to Angel One API
print("[1/5] Authenticating with Angel One SmartAPI...")
totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
smart_api = SmartConnect(api_key=config.ANGEL_API_KEY)
session_data = smart_api.generateSession(config.ANGEL_CLIENT_ID, config.ANGEL_PASSWORD, totp)

if not session_data.get('status'):
    print("[ERROR] Angel One API Login Failed:", session_data)
    exit(1)

print("  Logged in successfully! Waiting 3s for API rate limit window...")
time.sleep(3.0)

# 2. Check existing nifty_6m_1min.csv
csv_1min_path = 'nifty_6m_1min.csv'
csv_5min_path = 'nifty_6m_5min.csv'
csv_1y_5min_path = 'nifty_1y_5min.csv'

df_existing_1min = pd.read_csv(csv_1min_path)

# Determine start date for downloading
col_time = [c for c in df_existing_1min.columns if 'time' in c.lower() or 'date' in c.lower()][0]
df_existing_1min[col_time] = pd.to_datetime(df_existing_1min[col_time])
last_existing_date = df_existing_1min[col_time].max()

print(f"[2/5] Existing 1-min Nifty data end timestamp: {last_existing_date}")

# Check missing dates between 2026-07-10 and today
start_dt = datetime.date(2026, 7, 10)
end_dt = datetime.date.today()

print(f"  Fetching missing data from {start_dt} to {end_dt}...")

new_candles = []
current_dt = start_dt

while current_dt <= end_dt:
    # Skip weekends (Saturday=5, Sunday=6)
    if current_dt.weekday() in [5, 6]:
        current_dt += datetime.timedelta(days=1)
        continue
        
    from_str = f"{current_dt.strftime('%Y-%m-%d')} 09:15"
    to_str = f"{current_dt.strftime('%Y-%m-%d')} 15:30"
    
    historic_params = {
        'exchange': 'NSE',
        'symboltoken': '99926000', # Nifty 50 Index
        'interval': 'ONE_MINUTE',
        'fromdate': from_str,
        'todate': to_str
    }
    
    # Retry loop with exponential delay for rate-limits
    fetched = False
    for attempt in range(1, 4):
        try:
            resp = smart_api.getCandleData(historic_params)
            if resp.get('status') and resp.get('data'):
                day_data = resp['data']
                new_candles.extend(day_data)
                print(f"  [{current_dt.strftime('%Y-%m-%d')}] Downloaded {len(day_data)} 1-min candles.")
                fetched = True
                break
            else:
                print(f"  [{current_dt.strftime('%Y-%m-%d')}] Attempt {attempt} failed: {resp.get('message')}")
        except Exception as e:
            print(f"  [{current_dt.strftime('%Y-%m-%d')}] Attempt {attempt} API Error: {e}")
            
        time.sleep(2.5) # Wait 2.5s before retrying
        
    if not fetched:
        print(f"  [WARNING] Could not fetch data for {current_dt.strftime('%Y-%m-%d')} after 3 attempts.")
        
    time.sleep(1.5) # Safe rate-limit delay
    current_dt += datetime.timedelta(days=1)

if not new_candles:
    print("  No new candles fetched.")
else:
    print(f"\n[3/5] Processed {len(new_candles)} total candles from Angel One.")
    df_new = pd.DataFrame(new_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_new['timestamp'] = pd.to_datetime(df_new['timestamp'])

    # Merge with existing 1-min dataset
    df_combined_1min = pd.concat([df_existing_1min, df_new], ignore_index=True)
    df_combined_1min['timestamp'] = pd.to_datetime(df_combined_1min['timestamp'])
    
    # Clean & Deduplicate by timestamp
    df_combined_1min = df_combined_1min.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
    
    # Save updated nifty_6m_1min.csv
    df_combined_1min.to_csv(csv_1min_path, index=False)
    print(f"  [SAVED] {csv_1min_path} | Total rows: {len(df_combined_1min)} | New End Date: {df_combined_1min['timestamp'].iloc[-1]}")

    # 4. Generate & Update 5-minute datasets
    print("\n[4/5] Resampling 1-minute data into 5-minute candles...")
    df_combined_1min.set_index('timestamp', inplace=True)
    
    df_5min = df_combined_1min.resample('5min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna().reset_index()
    
    df_5min['timestamp'] = df_5min['timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%S+05:30')
    
    # Save nifty_6m_5min.csv
    df_5min.tail(9000).to_csv(csv_5min_path, index=False)
    print(f"  [SAVED] {csv_5min_path} | Total 5-min rows: {len(df_5min.tail(9000))} | End Date: {df_5min['timestamp'].iloc[-1]}")
    
    # Save nifty_1y_5min.csv
    df_5min.to_csv(csv_1y_5min_path, index=False)
    print(f"  [SAVED] {csv_1y_5min_path} | Total 1-year 5-min rows: {len(df_5min)} | End Date: {df_5min['timestamp'].iloc[-1]}")

print("\n" + "=" * 60)
print("  NIFTY REAL DATA UPDATE COMPLETED SUCCESSFULLY!")
print("=" * 60)
