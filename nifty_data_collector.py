import time
import sys
import os
import json
import urllib.request
import datetime
import threading
import csv

if sys.platform == 'win32':
    os.system('')

from angel_client import AngelOneClient
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

CSV_FILENAME = "nifty_ai_training_data.csv"
NIFTY_SPOT_TOKEN = "99926000"
STRIKE_STEP = 50
NUM_STRIKES = 5 # 5 above, 5 below + ATM = 11

# State
# live_data mapping: token -> dict of snapshot data
live_data = {NIFTY_SPOT_TOKEN: {"ltp": 0.0}}
tracked_tokens = {} # token -> metadata (symbol, type, strike)
data_lock = threading.Lock()

def get_22_option_tokens(spot_price):
    atm_strike = float(round(spot_price / STRIKE_STEP) * STRIKE_STEP)
    scrip_path = "scrip_master.json"
    
    if not os.path.exists(scrip_path):
        urllib.request.urlretrieve("https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json", scrip_path)
        
    with open(scrip_path, 'r') as f:
        scrips = json.load(f)
        
    ce_options = []
    pe_options = []
    
    for s in scrips:
        if s.get("exch_seg") == "NFO" and s.get("name") == "NIFTY" and s.get("instrumenttype") == "OPTIDX":
            try:
                strike = float(s.get("strike", 0)) / 100.0
                expiry_str = s.get("expiry")
                expiry = datetime.datetime.strptime(expiry_str, "%d%b%Y")
                if s.get("symbol").endswith("CE"):
                    ce_options.append((expiry, strike, s))
                elif s.get("symbol").endswith("PE"):
                    pe_options.append((expiry, strike, s))
            except:
                continue
                
    # We want the nearest expiry. Let's find the minimum expiry date first
    ce_options.sort(key=lambda x: x[0])
    if not ce_options: return [], [], atm_strike
    nearest_expiry = ce_options[0][0]
    
    # Filter by nearest expiry
    ce_nearest = [x for x in ce_options if x[0] == nearest_expiry]
    pe_nearest = [x for x in pe_options if x[0] == nearest_expiry]
    
    # Convert to dictionary for easy strike lookup
    ce_map = {x[1]: x[2] for x in ce_nearest}
    pe_map = {x[1]: x[2] for x in pe_nearest}
    
    selected_ce = []
    selected_pe = []
    
    for i in range(-NUM_STRIKES, NUM_STRIKES + 1):
        target_strike = atm_strike + (i * STRIKE_STEP)
        if target_strike in ce_map:
            selected_ce.append(ce_map[target_strike])
        if target_strike in pe_map:
            selected_pe.append(pe_map[target_strike])
            
    return selected_ce, selected_pe, atm_strike

def initialize_csv():
    file_exists = os.path.exists(CSV_FILENAME)
    with open(CSV_FILENAME, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            header = [
                "Timestamp", "Spot", "Token", "Symbol", "Type", "Strike", "LTP", "OI",
                "BidQ1", "BidP1", "BidQ2", "BidP2", "BidQ3", "BidP3", "BidQ4", "BidP4", "BidQ5", "BidP5",
                "AskQ1", "AskP1", "AskQ2", "AskP2", "AskQ3", "AskP3", "AskQ4", "AskP4", "AskQ5", "AskP5"
            ]
            writer.writerow(header)

def on_data(wsapp, message):
    token = str(message.get("token"))
    if not token: return
        
    with data_lock:
        if token == NIFTY_SPOT_TOKEN:
            if "last_traded_price" in message:
                live_data[token]["ltp"] = message["last_traded_price"] / 100.0
        elif token in tracked_tokens:
            if token not in live_data:
                live_data[token] = {}
            if "last_traded_price" in message:
                live_data[token]["ltp"] = message["last_traded_price"] / 100.0
            if "open_interest" in message:
                live_data[token]["oi"] = message["open_interest"]
            if "best_5_buy_data" in message:
                live_data[token]["bids"] = message["best_5_buy_data"]
            if "best_5_sell_data" in message:
                live_data[token]["asks"] = message["best_5_sell_data"]

def on_error(wsapp, error): pass
def on_close(wsapp): pass
def clear_screen(): sys.stdout.write("\033[2J"); sys.stdout.flush()
def reset_cursor(): sys.stdout.write("\033[H"); sys.stdout.flush()

def main():
    clear_screen()
    print("Initializing Nifty L2 Data Collector for AI Training...")
    initialize_csv()
    
    client = AngelOneClient()
    if not client.login():
        print("Login failed.")
        return
        
    print("Fetching Nifty Spot Price...")
    resp = client.get_ltp_data_throttled("NSE", "NIFTY", NIFTY_SPOT_TOKEN)
    spot_price = 24000.0
    if resp.get("status") and "data" in resp:
        spot_price = float(resp["data"]["ltp"])
        live_data[NIFTY_SPOT_TOKEN]["ltp"] = spot_price
        
    print(f"Current Nifty Spot: {spot_price}")
    
    ce_list, pe_list, atm_strike = get_22_option_tokens(spot_price)
    
    print(f"Tracking 22 Options around ATM: {atm_strike}")
    
    def register_tokens(ce_list, pe_list):
        tracked_tokens.clear()
        for c in ce_list:
            tk = str(c["token"])
            tracked_tokens[tk] = {"symbol": c["symbol"], "type": "CE", "strike": float(c["strike"])/100.0}
            live_data[tk] = {"ltp": 0.0, "oi": 0, "bids": [], "asks": []}
        for p in pe_list:
            tk = str(p["token"])
            tracked_tokens[tk] = {"symbol": p["symbol"], "type": "PE", "strike": float(p["strike"])/100.0}
            live_data[tk] = {"ltp": 0.0, "oi": 0, "bids": [], "asks": []}
            
    register_tokens(ce_list, pe_list)
    
    print("Connecting to SmartWebSocketV2 (Mode 3)...")
    sws = SmartWebSocketV2(client.jwt_token, client.api_key, client.client_id, client.feed_token)
    sws.on_data = on_data
    sws.on_error = on_error
    sws.on_close = on_close
    
    def on_open(wsapp):
        option_tokens = list(tracked_tokens.keys())
        token_list = [
            {"exchangeType": 1, "tokens": [NIFTY_SPOT_TOKEN]}, 
            {"exchangeType": 2, "tokens": option_tokens} 
        ]
        sws.subscribe(correlation_id="nifty_data", mode=3, token_list=token_list)
        
    sws.on_open = on_open
    t = threading.Thread(target=sws.connect, daemon=True)
    t.start()
    
    last_strike_check = time.time()
    rows_written = 0
    
    while True:
        try:
            time.sleep(1) # Run every 1 second
            now = time.time()
            
            with data_lock:
                spot = live_data[NIFTY_SPOT_TOKEN]["ltp"]
                
                # Dynamic ATM Shifting (every 60s to prevent thrashing)
                if now - last_strike_check > 60 and spot > 0:
                    expected_atm = float(round(spot / STRIKE_STEP) * STRIKE_STEP)
                    if expected_atm != atm_strike:
                        old_tokens = list(tracked_tokens.keys())
                        sws.unsubscribe(correlation_id="unsub", mode=3, token_list=[{"exchangeType": 2, "tokens": old_tokens}])
                        
                        new_ce, new_pe, atm_strike = get_22_option_tokens(spot)
                        register_tokens(new_ce, new_pe)
                        
                        new_tokens = list(tracked_tokens.keys())
                        sws.subscribe(correlation_id="sub", mode=3, token_list=[{"exchangeType": 2, "tokens": new_tokens}])
                    last_strike_check = now
                
                # Take Snapshot & Write to CSV
                snapshot_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                
                rows_to_write = []
                for tk, meta in tracked_tokens.items():
                    d = live_data.get(tk, {})
                    bids = d.get("bids", [])
                    asks = d.get("asks", [])
                    
                    row = [
                        snapshot_time, spot, tk, meta["symbol"], meta["type"], meta["strike"],
                        d.get("ltp", 0.0), d.get("oi", 0)
                    ]
                    
                    # 5 Bid Levels (Qty, Price)
                    for i in range(5):
                        if i < len(bids):
                            row.extend([bids[i].get("quantity", 0), bids[i].get("price", 0)/100.0])
                        else:
                            row.extend([0, 0.0])
                            
                    # 5 Ask Levels (Qty, Price)
                    for i in range(5):
                        if i < len(asks):
                            row.extend([asks[i].get("quantity", 0), asks[i].get("price", 0)/100.0])
                        else:
                            row.extend([0, 0.0])
                            
                    rows_to_write.append(row)
                    
            with open(CSV_FILENAME, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerows(rows_to_write)
                rows_written += len(rows_to_write)
                
            reset_cursor()
            print("=" * 80)
            print(f"   NIFTY AI DATA COLLECTOR | ACTIVE (Mode: SNAPQUOTE)")
            print("=" * 80)
            print(f"   Time:       {snapshot_time}")
            print(f"   Spot Price: {spot:.2f}")
            print(f"   ATM Strike: {atm_strike:.0f}")
            print(f"   Options:    {len(tracked_tokens)} (+/- 5 Strikes CE & PE)")
            print(f"   Rows Saved: {rows_written:,}")
            print(f"   File Size:  {os.path.getsize(CSV_FILENAME)/1024/1024:.2f} MB")
            print("=" * 80)
            print(f"   Logging full L2 Orderbook and Live Open Interest...")
            print(f"   Press Ctrl+C to stop.")
            
        except KeyboardInterrupt:
            print("\nShutting down collector...")
            try:
                sws.close_connection()
            except:
                pass
            break
        except Exception as e:
            pass

if __name__ == '__main__':
    main()
