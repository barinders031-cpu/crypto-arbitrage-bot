import requests
import json
import time
import os
import datetime
import pandas as pd

# Base URL for Delta Exchange India
BASE_URL = "https://api.india.delta.exchange"

# Make sure output directory exists
OUTPUT_DIR = "live_data/order_books"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_l2_orderbook(symbol):
    url = f"{BASE_URL}/v2/l2orderbook/{symbol}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get('result', {})
        elif response.status_code == 429:
            print(f"[{datetime.datetime.now()}] [!] Rate limit hit (429). Sleeping for 5 seconds...")
            time.sleep(5)
            return None
        else:
            print(f"[{datetime.datetime.now()}] [!] Error fetching order book: Status code {response.status_code}")
            return None
    except Exception as e:
        print(f"[{datetime.datetime.now()}] [!] Connection error: {e}")
        return None

def save_orderbook_to_csv(symbol, ob_data):
    if not ob_data:
        return
    
    timestamp = datetime.datetime.now()
    bids = ob_data.get('buy') or ob_data.get('bids') or []
    asks = ob_data.get('sell') or ob_data.get('asks') or []
    
    # We will format this into a flat structure
    records = []
    
    # Save top 5 levels of bids and asks
    max_levels = max(len(bids), len(asks))
    levels_to_save = min(max_levels, 5)
    
    for idx in range(levels_to_save):
        bid_price = bids[idx].get('price') if idx < len(bids) else ""
        bid_size = bids[idx].get('size') if idx < len(bids) else ""
        ask_price = asks[idx].get('price') if idx < len(asks) else ""
        ask_size = asks[idx].get('size') if idx < len(asks) else ""
        
        records.append({
            'timestamp': timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            'symbol': symbol,
            'level': idx + 1,
            'bid_price': bid_price,
            'bid_size': bid_size,
            'ask_price': ask_price,
            'ask_size': ask_size
        })
        
    df = pd.DataFrame(records)
    file_path = os.path.join(OUTPUT_DIR, f"{symbol}_orderbook.csv")
    
    # If file doesn't exist, write headers, otherwise append
    file_exists = os.path.isfile(file_path)
    df.to_csv(file_path, mode='a', header=not file_exists, index=False)
    
    # Also save as a single live status file for quick checks
    live_file_path = os.path.join(OUTPUT_DIR, f"{symbol}_live_state.json")
    with open(live_file_path, 'w') as f:
        json.dump({
            'timestamp': timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            'symbol': symbol,
            'bids': bids[:5],
            'asks': asks[:5]
        }, f, indent=4)

def main():
    print("=" * 60)
    print("      DELTA EXCHANGE INDIA LIVE ORDER BOOK TRACKER")
    print("=" * 60)
    
    # Allow user to input custom symbol or default to BTCUSD
    default_symbol = "BTCUSD"
    symbol = input(f"Enter Symbol to track (Default: {default_symbol}): ").strip()
    if not symbol:
        symbol = default_symbol
        
    interval_input = input("Enter refresh interval in seconds (Default: 2): ").strip()
    try:
        interval = float(interval_input) if interval_input else 2.0
    except ValueError:
        interval = 2.0
        
    print(f"\n[INFO] Starting live tracking for: {symbol}")
    print(f"[INFO] Refresh Interval: {interval} seconds")
    print(f"[INFO] Data will be saved to: {os.path.abspath(OUTPUT_DIR)}")
    print("[INFO] Press Ctrl+C to stop the script.\n")
    print(f"{'Time':^20} | {'Best Bid':^12} | {'Best Ask':^12} | {'Spread ($)':^12}")
    print("-" * 65)
    
    while True:
        try:
            ob = fetch_l2_orderbook(symbol)
            if ob:
                bids = ob.get('buy') or ob.get('bids') or []
                asks = ob.get('sell') or ob.get('asks') or []
                
                best_bid_str = "N/A"
                best_ask_str = "N/A"
                spread_str = "N/A"
                
                if bids and asks:
                    best_bid = float(bids[0]['price'])
                    best_ask = float(asks[0]['price'])
                    spread = best_ask - best_bid
                    
                    best_bid_str = f"${best_bid:.2f}"
                    best_ask_str = f"${best_ask:.2f}"
                    spread_str = f"${spread:.2f}"
                    
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"{now_str} | {best_bid_str:>12} | {best_ask_str:>12} | {spread_str:>12}")
                
                # Save data to CSV & JSON
                save_orderbook_to_csv(symbol, ob)
                
            time.sleep(interval)
            
        except KeyboardInterrupt:
            print("\n\n[INFO] Exiting program gracefully. Goodbye!")
            break
        except Exception as e:
            print(f"\n[!] Unexpected error in main loop: {e}")
            print("[INFO] Reconnecting in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    main()
