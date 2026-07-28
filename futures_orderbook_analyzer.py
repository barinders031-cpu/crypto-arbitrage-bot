import requests
import json
import datetime
import os

BASE_URL = "https://api.india.delta.exchange"

def fetch_l2_orderbook(symbol="BTCUSD"):
    url = f"{BASE_URL}/v2/l2orderbook/{symbol}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get('result', {})
    except Exception as e:
        print(f"Error fetching orderbook: {e}")
    return {}

def analyze_order_book(symbol="BTCUSD"):
    ob = fetch_l2_orderbook(symbol)
    if not ob:
        print("[!] Could not fetch order book.")
        return
        
    bids = ob.get('buy', [])
    asks = ob.get('sell', [])
    
    if not bids or not asks:
        print("[!] Order book is empty or has zero liquidity.")
        return
        
    mid_price = (float(bids[0]['price']) + float(asks[0]['price'])) / 2.0
    
    # Filter out junk orders (e.g., bids at $1) that are too far away from mid_price. 
    # Let's keep orders within 2% of the mid_price.
    threshold_pct = 0.02
    valid_bids = [b for b in bids if (mid_price - float(b['price'])) / mid_price <= threshold_pct]
    valid_asks = [a for a in asks if (float(a['price']) - mid_price) / mid_price <= threshold_pct]
    
    # Sort orders by size (descending) to find the largest individual block orders
    large_bids = sorted(valid_bids, key=lambda x: float(x.get('size', 0)), reverse=True)
    large_asks = sorted(valid_asks, key=lambda x: float(x.get('size', 0)), reverse=True)
    
    print("=" * 65)
    print(f"      DELTA EXCHANGE INDIA - BTC FUTURES ORDER BOOK ANALYSIS")
    print(f"      Symbol: {symbol} | Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)
    print(f"Mid Price: ${mid_price:.2f}")
    print(f"Best Bid: ${bids[0]['price']} | Best Ask: ${asks[0]['price']}")
    print(f"Spread: ${float(asks[0]['price']) - float(bids[0]['price']):.2f}")
    print("-" * 65)
    
    print("\n[+] Top 5 Largest REAL Buy Orders (Support Walls / Bids):")
    total_support_size = 0
    for b in large_bids[:5]:
        price = float(b['price'])
        size = float(b['size'])
        total_support_size += size
        distance = mid_price - price
        distance_pct = (distance / mid_price) * 100
        print(f"  Price: ${price:<10.2f} | Size: {size:<8.0f} contracts | Dist: -${distance:<6.2f} (-{distance_pct:.2f}%)")
        
    print("\n[+] Top 5 Largest REAL Sell Orders (Resistance Walls / Asks):")
    total_resistance_size = 0
    for a in large_asks[:5]:
        price = float(a['price'])
        size = float(a['size'])
        total_resistance_size += size
        distance = price - mid_price
        distance_pct = (distance / mid_price) * 100
        print(f"  Price: ${price:<10.2f} | Size: {size:<8.0f} contracts | Dist: +${distance:<6.2f} (+{distance_pct:.2f}%)")
        
    # Calculate Order Book Imbalance within the valid 2% range
    total_bid_vol = sum(float(b['size']) for b in valid_bids)
    total_ask_vol = sum(float(a['size']) for a in valid_asks)
    
    imbalance = (total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol) if (total_bid_vol + total_ask_vol) > 0 else 0
    
    print("\n" + "-" * 65)
    print(f"Order Book Imbalance (within 2% price range): {imbalance:+.4f}")
    print(f"  Total Valid Bid Volume: {total_bid_vol:.0f} contracts")
    print(f"  Total Valid Ask Volume: {total_ask_vol:.0f} contracts")
    
    print("\n*** TRADING SIGNALS & ANALYSIS ***")
    
    if imbalance > 0.15:
        print("[*] TENDENCY: BULLISH")
        print("    -> Strong buying liquidity (Support Walls) close to current price.")
    elif imbalance < -0.15:
        print("[*] TENDENCY: BEARISH")
        print("    -> Strong selling liquidity (Resistance Walls) close to current price.")
    else:
        print("[*] TENDENCY: NEUTRAL")
        print("    -> Buying and selling pressure are relatively balanced.")
        
    # Generate basic Buy/Sell signals based on Support/Resistance walls
    if total_support_size > total_resistance_size * 1.5:
        print("[SIGNAL] 🟢 BUY SIGNAL: Support walls are 1.5x larger than resistance walls.")
        print(f"         Consider long positions near strong support: ${float(large_bids[0]['price']):.2f}")
    elif total_resistance_size > total_support_size * 1.5:
        print("[SIGNAL] 🔴 SELL SIGNAL: Resistance walls are 1.5x larger than support walls.")
        print(f"         Consider short positions near strong resistance: ${float(large_asks[0]['price']):.2f}")
    else:
        print("[SIGNAL] ⚪ WAIT: No clear directional advantage based on wall sizes.")
        
    print("=" * 65)

if __name__ == "__main__":
    import time
    symbol = "BTCUSD"
    
    while True:
        try:
            # Clear the terminal for a clean real-time dashboard look
            os.system('cls' if os.name == 'nt' else 'clear')
            analyze_order_book(symbol)
            print("\n[INFO] Refreshing in 5 seconds... Press Ctrl+C to stop.")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n[INFO] Exiting monitor. Goodbye!")
            break
        except Exception as e:
            print(f"\n[!] Error in monitor: {e}")
            time.sleep(5)
