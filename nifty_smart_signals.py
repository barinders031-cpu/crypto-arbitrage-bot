import time
import sys
import os
import json
import urllib.request
import datetime
import threading

if sys.platform == 'win32':
    os.system('')

from angel_client import AngelOneClient
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

# Tokens
NIFTY_SPOT_TOKEN = "99926000"
HDFC_TOKEN = "1333"
RELIANCE_TOKEN = "2885"

# Global State
live_data = {
    NIFTY_SPOT_TOKEN: {"ltp": 0.0},
    HDFC_TOKEN: {"best_bid_vol": 0, "best_ask_vol": 0, "ltp": 0},
    RELIANCE_TOKEN: {"best_bid_vol": 0, "best_ask_vol": 0, "ltp": 0},
    "CE": {"token": "", "best_bid_vol": 0, "best_ask_vol": 0, "ltp": 0},
    "PE": {"token": "", "best_bid_vol": 0, "best_ask_vol": 0, "ltp": 0}
}
data_lock = threading.Lock()

def get_atm_tokens(spot_price):
    atm_strike = float(round(spot_price / 50.0) * 50.0)
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
                if strike == atm_strike:
                    expiry_str = s.get("expiry")
                    try:
                        expiry = datetime.datetime.strptime(expiry_str, "%d%b%Y")
                        if s.get("symbol").endswith("CE"):
                            ce_options.append((expiry, s))
                        elif s.get("symbol").endswith("PE"):
                            pe_options.append((expiry, s))
                    except:
                        continue
            except:
                pass
                
    ce_options.sort(key=lambda x: x[0])
    pe_options.sort(key=lambda x: x[0])
    
    ce_token = ce_options[0][1]["token"] if ce_options else ""
    pe_token = pe_options[0][1]["token"] if pe_options else ""
    ce_sym = ce_options[0][1]["symbol"] if ce_options else ""
    pe_sym = pe_options[0][1]["symbol"] if pe_options else ""
    
    return ce_token, pe_token, ce_sym, pe_sym, atm_strike

def on_data(wsapp, message):
    token = str(message.get("token"))
    if not token: return
        
    with data_lock:
        if "last_traded_price" in message:
            ltp = message["last_traded_price"] / 100.0
            
            # Spot Price
            if token == NIFTY_SPOT_TOKEN:
                live_data[token]["ltp"] = ltp
                
            # Heavyweights (Spoofing Filter: Top 3 only)
            elif token in [HDFC_TOKEN, RELIANCE_TOKEN]:
                live_data[token]["ltp"] = ltp
                if "best_5_buy_data" in message and "best_5_sell_data" in message:
                    bids = sum(b.get("quantity", 0) for b in message["best_5_buy_data"][:3])
                    asks = sum(a.get("quantity", 0) for a in message["best_5_sell_data"][:3])
                    live_data[token]["best_bid_vol"] = bids
                    live_data[token]["best_ask_vol"] = asks
            
            # Options (Spoofing Filter: Top 3 only)
            elif token == live_data["CE"]["token"]:
                live_data["CE"]["ltp"] = ltp
                if "best_5_buy_data" in message and "best_5_sell_data" in message:
                    bids = sum(b.get("quantity", 0) for b in message["best_5_buy_data"][:3])
                    asks = sum(a.get("quantity", 0) for a in message["best_5_sell_data"][:3])
                    live_data["CE"]["best_bid_vol"] = bids
                    live_data["CE"]["best_ask_vol"] = asks
                    
            elif token == live_data["PE"]["token"]:
                live_data["PE"]["ltp"] = ltp
                if "best_5_buy_data" in message and "best_5_sell_data" in message:
                    bids = sum(b.get("quantity", 0) for b in message["best_5_buy_data"][:3])
                    asks = sum(a.get("quantity", 0) for a in message["best_5_sell_data"][:3])
                    live_data["PE"]["best_bid_vol"] = bids
                    live_data["PE"]["best_ask_vol"] = asks

def on_error(wsapp, error): pass
def on_close(wsapp): pass
def clear_screen(): sys.stdout.write("\033[2J"); sys.stdout.flush()
def reset_cursor(): sys.stdout.write("\033[H"); sys.stdout.flush()

def main():
    clear_screen()
    print("Logging into Angel One SmartAPI...")
    
    client = AngelOneClient()
    if not client.login():
        print("Login failed.")
        return
        
    print("Fetching Nifty Spot Price...")
    resp = client.get_ltp_data_throttled("NSE", "NIFTY", NIFTY_SPOT_TOKEN)
    spot_price = 24000.0
    if resp.get("status") and "data" in resp:
        spot_price = float(resp["data"]["ltp"])
        
    ce_token, pe_token, ce_sym, pe_sym, atm_strike = get_atm_tokens(spot_price)
    live_data["CE"]["token"] = ce_token
    live_data["PE"]["token"] = pe_token
    
    print("Connecting to SmartWebSocketV2 (Mode 3)...")
    sws = SmartWebSocketV2(client.jwt_token, client.api_key, client.client_id, client.feed_token)
    sws.on_data = on_data
    sws.on_error = on_error
    sws.on_close = on_close
    
    def on_open(wsapp):
        token_list = [
            {"exchangeType": 1, "tokens": [NIFTY_SPOT_TOKEN, HDFC_TOKEN, RELIANCE_TOKEN]}, 
            {"exchangeType": 2, "tokens": [ce_token, pe_token]} 
        ]
        sws.subscribe(correlation_id="nifty_signals", mode=3, token_list=token_list)
        
    sws.on_open = on_open
    t = threading.Thread(target=sws.connect, daemon=True)
    t.start()
    
    # State variables for Signal Machine
    active_signal = None  # None, 'CE', 'PE'
    signal_start_time = 0
    signal_entry_price = 0.0
    signal_target_price = 0.0
    signal_sl_price = 0.0
    
    last_strike_check = time.time()
    
    while True:
        try:
            reset_cursor()
            
            with data_lock:
                hdfc_bid = live_data[HDFC_TOKEN]["best_bid_vol"]
                hdfc_ask = live_data[HDFC_TOKEN]["best_ask_vol"]
                rel_bid = live_data[RELIANCE_TOKEN]["best_bid_vol"]
                rel_ask = live_data[RELIANCE_TOKEN]["best_ask_vol"]
                ce_bid = live_data["CE"]["best_bid_vol"]
                ce_ask = live_data["CE"]["best_ask_vol"]
                pe_bid = live_data["PE"]["best_bid_vol"]
                pe_ask = live_data["PE"]["best_ask_vol"]
                spot = live_data[NIFTY_SPOT_TOKEN]["ltp"]
                ce_ltp = live_data["CE"]["ltp"]
                pe_ltp = live_data["PE"]["ltp"]
                current_ce_token = live_data["CE"]["token"]
                current_pe_token = live_data["PE"]["token"]
                
            # Dynamic ATM Shifting (every 30s)
            now = time.time()
            if now - last_strike_check > 30 and spot > 0:
                expected_atm = float(round(spot / 50.0) * 50.0)
                if expected_atm != atm_strike:
                    new_ce_t, new_pe_t, new_ce_s, new_pe_s, _ = get_atm_tokens(spot)
                    if new_ce_t and new_pe_t:
                        # Unsubscribe old
                        sws.unsubscribe(correlation_id="nifty_sig_unsub", mode=3, token_list=[{"exchangeType": 2, "tokens": [current_ce_token, current_pe_token]}])
                        # Subscribe new
                        sws.subscribe(correlation_id="nifty_sig_sub", mode=3, token_list=[{"exchangeType": 2, "tokens": [new_ce_t, new_pe_t]}])
                        with data_lock:
                            atm_strike = expected_atm
                            ce_sym, pe_sym = new_ce_s, new_pe_s
                            live_data["CE"]["token"] = new_ce_t
                            live_data["PE"]["token"] = new_pe_t
                            live_data["CE"]["best_bid_vol"] = 0
                            live_data["CE"]["best_ask_vol"] = 0
                            live_data["PE"]["best_bid_vol"] = 0
                            live_data["PE"]["best_ask_vol"] = 0
                            # Reset signal on strike change
                            active_signal = None 
                last_strike_check = now
            
            print("=" * 80)
            print(f"   NIFTY PRO SMART SIGNAL GENERATOR | ATM Strike: {atm_strike:.0f}")
            print(f"   Time: {datetime.datetime.now().strftime('%H:%M:%S')} | Live Spot: {spot:.2f} {' ' * 20}")
            print("=" * 80)
            
            # Determine Heavyweight Trend (Using Top 3 Depth)
            hdfc_bullish = hdfc_bid > hdfc_ask * 1.5 if hdfc_ask > 0 else False
            hdfc_bearish = hdfc_ask > hdfc_bid * 1.5 if hdfc_bid > 0 else False
            rel_bullish = rel_bid > rel_ask * 1.5 if rel_ask > 0 else False
            rel_bearish = rel_ask > rel_bid * 1.5 if rel_bid > 0 else False
            
            heavy_bullish = hdfc_bullish and rel_bullish
            heavy_bearish = hdfc_bearish and rel_bearish
            
            print(f"\n   [HEAVYWEIGHTS TOP-3 DEPTH] {' ' * 30}")
            print("-" * 80)
            print(f"   HDFC Bank:  Bids {hdfc_bid:<8} | Asks {hdfc_ask:<8} -> " + ("Bullish" if hdfc_bullish else "Bearish" if hdfc_bearish else "Neutral"))
            print(f"   Reliance:   Bids {rel_bid:<8} | Asks {rel_ask:<8} -> " + ("Bullish" if rel_bullish else "Bearish" if rel_bearish else "Neutral"))
            print("-" * 80)
            
            print(f"\n   [ATM OPTIONS TOP-3 DEPTH] {' ' * 30}")
            print("-" * 80)
            print(f"   {ce_sym}: Bids {ce_bid:<8} | Asks {ce_ask:<8}")
            print(f"   {pe_sym}: Bids {pe_bid:<8} | Asks {pe_ask:<8}")
            print("-" * 80)
            
            # Signal Timeout Logic (3 Minutes = 180 seconds)
            if active_signal and now - signal_start_time > 180:
                active_signal = None  # Force timeout reset
            
            # Signal Generation Logic
            if active_signal is None:
                if heavy_bullish and ce_bid > ce_ask * 1.5 and ce_ask > 0:
                    active_signal = 'CE'
                    signal_start_time = now
                    signal_entry_price = ce_ltp
                    signal_target_price = signal_entry_price + 15
                    signal_sl_price = signal_entry_price - 10
                elif heavy_bearish and pe_bid > pe_ask * 1.5 and pe_ask > 0:
                    active_signal = 'PE'
                    signal_start_time = now
                    signal_entry_price = pe_ltp
                    signal_target_price = signal_entry_price + 15
                    signal_sl_price = signal_entry_price - 10

            # UI Rendering
            if active_signal == 'CE':
                elapsed = int(now - signal_start_time)
                print("\n\033[92m" + "█" * 80)
                print(f"██  STRONG BUY CE SIGNAL! ({ce_sym})  ██".center(80))
                print("█" * 80 + "\033[0m")
                print(f"\n   [ACTION] Massive support detected. Scalp LONG.")
                print(f"   [ENTRY LTP] {signal_entry_price:.2f} | Active for: {elapsed}s")
                print(f"   [TARGET] {signal_target_price:.2f} (+15 pts) \033[92m🎯\033[0m")
                print(f"   [STRICT SL] {signal_sl_price:.2f} (-10 pts) \033[91m🛑\033[0m")
                
            elif active_signal == 'PE':
                elapsed = int(now - signal_start_time)
                print("\n\033[91m" + "█" * 80)
                print(f"██  STRONG BUY PE SIGNAL! ({pe_sym})  ██".center(80))
                print("█" * 80 + "\033[0m")
                print(f"\n   [ACTION] Massive resistance detected. Scalp SHORT.")
                print(f"   [ENTRY LTP] {signal_entry_price:.2f} | Active for: {elapsed}s")
                print(f"   [TARGET] {signal_target_price:.2f} (+15 pts) \033[92m🎯\033[0m")
                print(f"   [STRICT SL] {signal_sl_price:.2f} (-10 pts) \033[91m🛑\033[0m")
                
            else:
                print("\n\033[93m" + "█" * 80)
                print("██  NO CLEAR SIGNAL - WAITING FOR SETUP...  ██".center(80))
                print("█" * 80 + "\033[0m")
                print(f"\n   [ACTION] Heavyweights and Options are not aligned.")
                print(f"   [WAITING] Capital protected. Stand by for momentum.")
                print(f"   {' ' * 50}")
            
            print("\n" + "=" * 80)
            print("   Press Ctrl+C to exit. Updating every 1 second...          ")
            print("   " + " " * 70) 
            print("   " + " " * 70) 
            
            time.sleep(1)
        except KeyboardInterrupt:
            print("\nClosing WebSocket...")
            try:
                sws.close_connection()
            except:
                pass
            break
        except Exception as e:
            time.sleep(1)

if __name__ == '__main__':
    main()
