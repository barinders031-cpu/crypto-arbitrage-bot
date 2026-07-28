import requests
import pandas as pd
import time
import datetime
import os

BASE_URL = "https://api.india.delta.exchange"
SAVE_PATH = "live_data/DELTA_BTC_options_historical.csv"

# Make sure live_data directory exists
os.makedirs("live_data", exist_ok=True)

def get_spot_candles(days=60):
    print(f"Fetching {days} days of BTC Spot Data...")
    end_time = int(time.time())
    start_time = end_time - (days * 86400)
    
    params = {
        "symbol": ".DEXBTUSDT",
        "resolution": "1d",
        "start": start_time,
        "end": end_time
    }
    
    response = requests.get(f"{BASE_URL}/v2/history/candles", params=params)
    if response.status_code == 200:
        data = response.json().get('result', [])
        return data
    else:
        print(f"Failed to fetch spot data. Status: {response.status_code}")
        return []

def fetch_option_data(symbol, start_time, end_time):
    params = {
        "symbol": symbol,
        "resolution": "5m",
        "start": start_time,
        "end": end_time
    }
    try:
        response = requests.get(f"{BASE_URL}/v2/history/candles", params=params, timeout=10)
        if response.status_code == 200:
            data = response.json().get('result', [])
            return data
        else:
            return []
    except Exception as e:
        print(f"Request failed for {symbol}: {e}")
        return []

def main():
    LOOKBACK_DAYS = 60 # Change to 1 for quick testing
    
    spot_data = get_spot_candles(days=LOOKBACK_DAYS)
    if not spot_data:
        return
        
    all_options_data = []
    total_symbols_found = 0
    
    print(f"Generating symbols and fetching options data...")
    
    for day in spot_data:
        # Delta timestamp is in seconds
        day_time = datetime.datetime.fromtimestamp(day['time'])
        # Option expires on the next day typically, but let's just generate the date string for current day
        date_str = day_time.strftime("%d%m%y")
        
        # We will fetch data for the 24 hours surrounding this day's start time
        start_ts = day['time']
        end_ts = start_ts + 86400
        
        base_price = int(day['close'])
        clean_base = round(base_price / 100) * 100
        
        # Generate strikes: +/- 10 strikes (100 point steps) from clean base price
        # This will generate offsets from -1000 to +1000
        strikes = set()
        for offset in range(-1000, 1001, 100):
            strikes.add(clean_base + offset)
            
        strikes = sorted(list(strikes))
        
        for strike in strikes:
            # Round strike to nearest 100 (as Delta uses clean numbers usually)
            clean_strike = round(strike / 100) * 100
            
            for opt_type in ['C', 'P']:
                symbol = f"{opt_type}-BTC-{clean_strike}-{date_str}"
                
                # Fetch data
                candles = fetch_option_data(symbol, start_ts, end_ts)
                
                if candles:
                    total_symbols_found += 1
                    print(f"Found data for {symbol} ({len(candles)} candles)")
                    for c in candles:
                        all_options_data.append({
                            'timestamp': datetime.datetime.fromtimestamp(c['time']),
                            'symbol': symbol,
                            'strike': clean_strike,
                            'type': 'CE' if opt_type == 'C' else 'PE',
                            'open': c['open'],
                            'high': c['high'],
                            'low': c['low'],
                            'close': c['close'],
                            'volume': c['volume']
                        })
                
                time.sleep(0.1) # Be nice to the API
                
    if all_options_data:
        df = pd.DataFrame(all_options_data)
        df = df.sort_values(by=['timestamp', 'symbol']).reset_index(drop=True)
        df.to_csv(SAVE_PATH, index=False)
        print(f"\nSaved {len(df)} rows across {total_symbols_found} unique option symbols to {SAVE_PATH}")
    else:
        print("\nNo options data found!")

if __name__ == "__main__":
    main()
