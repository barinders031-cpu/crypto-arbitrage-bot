import requests
import time
import sys
import datetime

# Setup Windows console to support ANSI escape codes
if sys.platform == 'win32':
    import os
    os.system('')

def fetch_delta_ob(symbol="BTCUSD"):
    try:
        r = requests.get(f"https://api.india.delta.exchange/v2/l2orderbook/{symbol}", timeout=2)
        if r.status_code == 200:
            return r.json().get('result', {})
    except:
        pass
    return None

def clear_screen():
    sys.stdout.write("\033[2J")
    sys.stdout.flush()

def reset_cursor():
    sys.stdout.write("\033[H")
    sys.stdout.flush()

def main():
    clear_screen()
    
    # --- PAPER TRADING STATE (SCALPING MODE) ---
    balance = 100.0
    position_type = None # 'LONG' or 'SHORT'
    entry_price = 0.0
    qty_btc = 0.0
    margin_used = 0.0
    leverage = 20
    trade_count = 0
    
    # Scalping Thresholds (Aiming for $4-$5 profit)
    take_profit_points = 40.0
    stop_loss_points = 20.0
    
    while True:
        try:
            delta_ob = fetch_delta_ob()
            reset_cursor()
            
            # --- Simulated Trading Dashboard ---
            print("=" * 80)
            print("   💰 SIMULATED TRADING ACCOUNT (Capital: $100 | Leverage: 20x) 💰")
            print(f"   Current Balance: ${balance:.2f} | Total Trades: {trade_count}")
            print("-" * 80)
            
            mid_price = 0
            if delta_ob and delta_ob.get('buy') and delta_ob.get('sell'):
                bids = delta_ob['buy']
                asks = delta_ob['sell']
                mid_price = (float(bids[0]['price']) + float(asks[0]['price'])) / 2
                
                # Check PNL and TP/SL if we have an open position
                unrealized_pnl = 0.0
                closed_trade = False
                close_reason = ""
                
                if position_type == 'LONG':
                    unrealized_pnl = (mid_price - entry_price) * qty_btc
                    pnl_points = mid_price - entry_price
                elif position_type == 'SHORT':
                    unrealized_pnl = (entry_price - mid_price) * qty_btc
                    pnl_points = entry_price - mid_price
                
                if position_type:
                    # Auto Close Logic
                    if pnl_points >= take_profit_points:
                        balance += unrealized_pnl
                        position_type = None
                        trade_count += 1
                        closed_trade = True
                        close_reason = "TAKE PROFIT HIT 🎯"
                    elif pnl_points <= -stop_loss_points:
                        balance += unrealized_pnl
                        position_type = None
                        trade_count += 1
                        closed_trade = True
                        close_reason = "STOP LOSS HIT 🛑"
                    elif balance + unrealized_pnl <= 0:
                        # Liquidation
                        balance = 0
                        position_type = None
                        closed_trade = True
                        close_reason = "LIQUIDATED ☠️"
                        
                # Display Position Status
                if closed_trade:
                    print(f"   \033[96m[TRADE CLOSED] {close_reason} | PNL: ${unrealized_pnl:+.2f}\033[0m")
                elif position_type:
                    color = "\033[92m" if unrealized_pnl >= 0 else "\033[91m"
                    print(f"   [OPEN POSITION] {position_type} @ ${entry_price:.2f} | Unrealized PNL: {color}${unrealized_pnl:+.2f}\033[0m")
                else:
                    print("   [OPEN POSITION] None (Waiting for Signal...)")
                
            print("=" * 80)
            print(f"   SCALPING SIGNAL GENERATOR | Time: {datetime.datetime.now().strftime('%H:%M:%S')} {' ' * 20}")
            print("=" * 80)
            
            if mid_price > 0:
                # Calculate total volume within 1000 points of mid price
                total_bid_vol = sum(float(b['size']) for b in bids if mid_price - float(b['price']) <= 1000)
                total_ask_vol = sum(float(a['size']) for a in asks if float(a['price']) - mid_price <= 1000)
                
                print(f"\n   Current BTC Price: ${mid_price:.2f} {' ' * 30}")
                print("-" * 80)
                print(f"   Total Support Volume (Bids):      {int(total_bid_vol):,} contracts {' ' * 10}")
                print(f"   Total Resistance Volume (Asks):   {int(total_ask_vol):,} contracts {' ' * 10}")
                print("-" * 80)
                
                # Signal Logic
                signal_color = "\033[93m"
                signal_text = "NO CLEAR SIGNAL - WAITING FOR SETUP..."
                action_text = "Market balanced. Do not trade."
                
                # We need a 1.8x imbalance to generate a signal
                if total_bid_vol > total_ask_vol * 1.8:
                    signal_color = "\033[92m"
                    signal_text = "STRONG BUY SIGNAL DETECTED! (SUPPORT WALL)"
                    action_text = "Market has massive support."
                    
                    if position_type is None and balance > 0:
                        position_type = 'LONG'
                        entry_price = mid_price
                        margin_used = 50.0 # Risk $50 of our $100 balance
                        qty_btc = (margin_used * leverage) / entry_price
                        
                elif total_ask_vol > total_bid_vol * 1.8:
                    signal_color = "\033[91m"
                    signal_text = "STRONG SELL SIGNAL DETECTED! (RESISTANCE WALL)"
                    action_text = "Market has massive resistance."
                    
                    if position_type is None and balance > 0:
                        position_type = 'SHORT'
                        entry_price = mid_price
                        margin_used = 50.0 
                        qty_btc = (margin_used * leverage) / entry_price
                        
                print("\n" + signal_color + "█" * 80)
                print("██" + signal_text.center(76) + "██")
                print("█" * 80 + "\033[0m")
                print(f"\n   [ACTION] {action_text}")
                
                print("\n" + "=" * 80)
                print("   Press Ctrl+C to exit. Updating every 1 second...          ")
                print("   " + " " * 70) 
                print("   " + " " * 70) 
            else:
                print("Waiting for data...                                       ")
                
            time.sleep(1)
        except KeyboardInterrupt:
            break
        except Exception as e:
            time.sleep(1)

if __name__ == '__main__':
    main()
