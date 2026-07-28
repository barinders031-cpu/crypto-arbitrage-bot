import requests
import time
import datetime

# Base URL for Delta Exchange India
BASE_URL = "https://api.india.delta.exchange"

# Estimated trading fee per side (approx 0.05% of value, or a small flat fee)
# We will use a safe buffer of $0.50 USD per contract to filter out tiny profit margins
MIN_PROFIT_BUFFER = 0.50  

def get_active_btc_options():
    url = f"{BASE_URL}/v2/products"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            products = response.json().get('result', [])
            btc_options = []
            for p in products:
                underlying = p.get('underlying_asset', {})
                if underlying.get('symbol') == 'BTC' and p.get('contract_type') in ['call_options', 'put_options']:
                    btc_options.append(p)
            return btc_options
    except Exception as e:
        print(f"Error fetching products: {e}")
    return []

def fetch_l2_orderbook(symbol):
    url = f"{BASE_URL}/v2/l2orderbook/{symbol}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json().get('result', {})
    except Exception:
        pass
    return {}

def parse_expiry_from_symbol(symbol):
    parts = symbol.split('-')
    if len(parts) >= 4:
        try:
            return parts[3] # Return the raw date string (e.g., '200726')
        except Exception:
            pass
    return ""

def main():
    print("=" * 75)
    print("       DELTA EXCHANGE INDIA - VERTICAL STRIKE ARBITRAGE SCANNER")
    print("                (Optimized for Small Capital: $100)")
    print("=" * 75)
    print("[INFO] Scanning option chains for Vertical Spread pricing violations...")
    print(f"[INFO] Profit Buffer set to: ${MIN_PROFIT_BUFFER} per contract (0.001 BTC)")
    print("[INFO] Press Ctrl+C to stop the scanner.\n")
    
    while True:
        try:
            options = get_active_btc_options()
            if not options:
                print("[!] No active options fetched. Retrying in 5s...")
                time.sleep(5)
                continue
                
            # Group options by expiry date
            grouped_by_expiry = {}
            for opt in options:
                symbol = opt.get('symbol')
                expiry = parse_expiry_from_symbol(symbol)
                if not expiry:
                    continue
                if expiry not in grouped_by_expiry:
                    grouped_by_expiry[expiry] = []
                grouped_by_expiry[expiry].append(opt)
                
            # Scan each expiry date separately
            discrepancies_found = 0
            
            for expiry, opts in grouped_by_expiry.items():
                # Separate Calls and Puts
                calls = [o for o in opts if o.get('contract_type') == 'call_options']
                puts = [o for o in opts if o.get('contract_type') == 'put_options']
                
                # Sort Calls by Strike ascending
                calls = sorted(calls, key=lambda x: float(x.get('strike_price', 0)))
                # Sort Puts by Strike ascending
                puts = sorted(puts, key=lambda x: float(x.get('strike_price', 0)))
                
                # -------------------------------------------------------------
                # 1. Call Option Strike Arbitrage (Vertical Debit/Credit Spread)
                # Rule: Higher strike call MUST be cheaper than lower strike call.
                # If Ask(K_lower) < Bid(K_higher) -> Loophole!
                # -------------------------------------------------------------
                for i in range(len(calls) - 1):
                    c1 = calls[i]      # Lower Strike
                    c2 = calls[i+1]    # Higher Strike
                    
                    k1 = float(c1.get('strike_price'))
                    k2 = float(c2.get('strike_price'))
                    
                    # Fetch order books
                    ob1 = fetch_l2_orderbook(c1.get('symbol'))
                    ob2 = fetch_l2_orderbook(c2.get('symbol'))
                    
                    bids1 = ob1.get('buy', [])
                    asks1 = ob1.get('sell', [])
                    bids2 = ob2.get('buy', [])
                    asks2 = ob2.get('sell', [])
                    
                    if not (bids1 and asks1 and bids2 and asks2):
                        continue
                        
                    c1_ask = float(asks1[0]['price']) # Cost to buy lower strike
                    c2_bid = float(bids2[0]['price']) # Credit from selling higher strike
                    
                    # If lower strike is cheaper than higher strike, we get a guaranteed net credit
                    # and lower strike gives us a better contract!
                    if c1_ask < c2_bid:
                        net_credit = c2_bid - c1_ask
                        # Convert to contract size profit (1 contract = 0.001 BTC)
                        profit_per_contract = net_credit * 0.001
                        
                        if profit_per_contract > MIN_PROFIT_BUFFER:
                            discrepancies_found += 1
                            print(f"\n[!!!] CALL STRIKE LOOPHOLE FOUND [Expiry: {expiry}]")
                            print(f"  BUY Lower Call:  {c1.get('symbol')} @ Ask Price ${c1_ask:.2f} (Strike {k1})")
                            print(f"  SELL Higher Call: {c2.get('symbol')} @ Bid Price ${c2_bid:.2f} (Strike {k2})")
                            print(f"  Net Credit: ${net_credit:.2f} USD per BTC")
                            print(f"  Guaranteed Profit per contract (0.001 BTC): ${profit_per_contract:.4f}")
                            print(f"  Capital Required: < $5 USD (To buy the cheaper contract)")
                            print("-" * 75)
                            
                # -------------------------------------------------------------
                # 2. Put Option Strike Arbitrage
                # Rule: Lower strike put MUST be cheaper than higher strike put.
                # If Ask(K_higher) < Bid(K_lower) -> Loophole!
                # -------------------------------------------------------------
                for i in range(len(puts) - 1):
                    p1 = puts[i]      # Lower Strike
                    p2 = puts[i+1]    # Higher Strike
                    
                    k1 = float(p1.get('strike_price'))
                    k2 = float(p2.get('strike_price'))
                    
                    ob1 = fetch_l2_orderbook(p1.get('symbol'))
                    ob2 = fetch_l2_orderbook(p2.get('symbol'))
                    
                    bids1 = ob1.get('buy', [])
                    asks1 = ob1.get('sell', [])
                    bids2 = ob2.get('buy', [])
                    asks2 = ob2.get('sell', [])
                    
                    if not (bids1 and asks1 and bids2 and asks2):
                        continue
                        
                    p1_bid = float(bids1[0]['price']) # Credit from selling lower strike
                    p2_ask = float(asks2[0]['price']) # Cost to buy higher strike
                    
                    # If higher strike is cheaper than lower strike, we get a guaranteed net credit
                    if p2_ask < p1_bid:
                        net_credit = p1_bid - p2_ask
                        profit_per_contract = net_credit * 0.001
                        
                        if profit_per_contract > MIN_PROFIT_BUFFER:
                            discrepancies_found += 1
                            print(f"\n[!!!] PUT STRIKE LOOPHOLE FOUND [Expiry: {expiry}]")
                            print(f"  BUY Higher Put: {p2.get('symbol')} @ Ask Price ${p2_ask:.2f} (Strike {k2})")
                            print(f"  SELL Lower Put: {p1.get('symbol')} @ Bid Price ${p1_bid:.2f} (Strike {k1})")
                            print(f"  Net Credit: ${net_credit:.2f} USD per BTC")
                            print(f"  Guaranteed Profit per contract (0.001 BTC): ${profit_per_contract:.4f}")
                            print(f"  Capital Required: < $5 USD")
                            print("-" * 75)
                            
                # Sleep briefly to avoid hitting rate limits while scanning
                time.sleep(0.05)
                
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            if discrepancies_found == 0:
                print(f"[{now_str}] Scan complete: No pricing violations found. Markets are efficient.")
            else:
                print(f"[{now_str}] Scan complete: Found {discrepancies_found} pricing loopholes!")
                
            print("[INFO] Sleeping 15 seconds before next scan...\n")
            time.sleep(15)
            
        except KeyboardInterrupt:
            print("\n[INFO] Exiting strike scanner gracefully. Goodbye!")
            break
        except Exception as e:
            print(f"\n[!] Error in scanner loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
