import requests
import pandas as pd
import time
import datetime
import os

BASE_URL = "https://api.india.delta.exchange"
SAVE_PATH = "live_data/DELTA_BTC_options_live.csv"
os.makedirs("live_data", exist_ok=True)

def fetch_live_symbols():
    print("Fetching active BTC options from Delta Exchange INDIA...")
    response = requests.get(f"{BASE_URL}/v2/products")
    if response.status_code != 200:
        print(f"Error fetching products: {response.status_code}")
        return []
    
    data = response.json().get('result', [])
    live_btc_options = [p['symbol'] for p in data if p.get('underlying_asset', {}).get('symbol') == 'BTC' and p.get('contract_type') in ['call_options', 'put_options']]
    return live_btc_options

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
            return response.json().get('result', [])
    except Exception as e:
        print(f"Failed for {symbol}: {e}")
    return []

def main():
    symbols = fetch_live_symbols()
    if not symbols:
        return
        
    print(f"Found {len(symbols)} active BTC Option contracts.")
    
    end_time = int(time.time())
    start_time = end_time - (4 * 86400) # Fetch up to 4 days of history for active contracts
    
    all_data = []
    found_symbols = 0
    
    for i, symbol in enumerate(symbols):
        candles = fetch_option_data(symbol, start_time, end_time)
        if candles:
            found_symbols += 1
            print(f"[{i+1}/{len(symbols)}] Fetched {len(candles)} candles for {symbol}")
            
            # Extract strike and type from symbol (e.g. C-BTC-62800-170726)
            parts = symbol.split('-')
            opt_type = 'CE' if parts[0] == 'C' else 'PE'
            strike = int(parts[2])
            
            for c in candles:
                all_data.append({
                    'timestamp': datetime.datetime.fromtimestamp(c['time']),
                    'symbol': symbol,
                    'strike': strike,
                    'type': opt_type,
                    'open': c['open'],
                    'high': c['high'],
                    'low': c['low'],
                    'close': c['close'],
                    'volume': c['volume']
                })
        else:
            print(f"[{i+1}/{len(symbols)}] No data for {symbol} (Zero volume)")
            
        time.sleep(0.1) # Rate limiting
        
    if all_data:
        df = pd.DataFrame(all_data)
        df = df.sort_values(by=['timestamp', 'symbol']).reset_index(drop=True)
        df.to_csv(SAVE_PATH, index=False)
        print(f"\nSaved {len(df)} rows from {found_symbols} active options to {SAVE_PATH}")
    else:
        print("\nNo data found across all active options.")

if __name__ == "__main__":
    main()
