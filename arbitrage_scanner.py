import requests
import time
import datetime
import os

# Base URL for Delta Exchange India
BASE_URL = "https://api.india.delta.exchange"

# Minimum profit threshold in USD (to filter out tiny discrepancies and account for fees)
PROFIT_THRESHOLD_USD = 5.0  

def get_btc_spot_price():
    url = f"{BASE_URL}/v2/tickers/BTCUSD"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            result = response.json().get('result', {})
            spot = result.get('spot_price') or result.get('mark_price')
            if spot:
                return float(spot)
    except Exception as e:
        print(f"Error fetching spot price: {e}")
    return None

def get_active_btc_options():
    url = f"{BASE_URL}/v2/products"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            products = response.json().get('result', [])
            btc_options = []
            for p in products:
                underlying = p.get('underlying_asset', {})
                if underlying.get('symbol') == 'BTC' and p.get('contract_type') in ['call_options', 'put_options']:
                    btc_options.append(p)
            return btc_options
        else:
            return []
    except Exception as e:
        print(f"Failed to fetch products: {e}")
        return []

def fetch_l2_orderbook(symbol):
    url = f"{BASE_URL}/v2/l2orderbook/{symbol}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get('result', {})
        elif response.status_code == 429:
            time.sleep(2)
            return fetch_l2_orderbook(symbol)
    except Exception:
        pass
    return {}

def parse_expiry_from_symbol(symbol):
    parts = symbol.split('-')
    if len(parts) >= 4:
        date_str = parts[3]
        try:
            return datetime.datetime.strptime(date_str, "%d%m%y")
        except ValueError:
            pass
    return datetime.datetime.max

def main():
    print("=" * 70)
    print("        DELTA EXCHANGE INDIA - BTC OPTIONS ARBITRAGE SCANNER")
    print("=" * 70)
    print("[INFO] Checking for Put-Call Parity pricing loopholes...")
    print(f"[INFO] Profit Threshold set to: ${PROFIT_THRESHOLD_USD} USD (excluding fees)")
    print("[INFO] Press Ctrl+C to stop the scanner.\n")
    
    while True:
        try:
            spot_price = get_btc_spot_price()
            if not spot_price:
                print("[!] Could not fetch BTC Spot price. Retrying in 5s...")
                time.sleep(5)
                continue
                
            options = get_active_btc_options()
            if not options:
                print("[!] Could not fetch active options. Retrying in 5s...")
                time.sleep(5)
                continue
            
            # Filter for ATM options (strike price within 3% of spot price)
            # This keeps the scan fast and focuses on the most liquid instruments
            atm_options = []
            for opt in options:
                try:
                    strike = float(opt.get('strike_price', 0))
                    if abs(strike - spot_price) / spot_price <= 0.03:
                        atm_options.append(opt)
                except ValueError:
                    continue
            
            # Sort by expiry date and group by expiry & strike
            # Key format: (expiry_datetime, strike_price)
            pairs = {}
            for opt in atm_options:
                symbol = opt.get('symbol')
                expiry = parse_expiry_from_symbol(symbol)
                
                # We only scan the nearest 2 expiries to prevent rate-limiting and check liquid contracts
                today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                if expiry > today + datetime.timedelta(days=2):
                    continue
                    
                strike = float(opt.get('strike_price'))
                opt_type = 'C' if opt.get('contract_type') == 'call_options' else 'P'
                
                key = (expiry, strike)
                if key not in pairs:
                    pairs[key] = {'C': None, 'P': None}
                pairs[key][opt_type] = symbol
                
            # Filter out incomplete pairs (we need both Call and Put for the same strike & expiry)
            valid_pairs = {k: v for k, v in pairs.items() if v['C'] and v['P']}
            
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Spot BTC: ${spot_price:.2f} | Scanning {len(valid_pairs)} Call-Put pairs close to spot...")
            
            discrepancy_found = False
            
            for (expiry, strike), symbols in valid_pairs.items():
                call_symbol = symbols['C']
                put_symbol = symbols['P']
                
                # Fetch order books
                call_ob = fetch_l2_orderbook(call_symbol)
                put_ob = fetch_l2_orderbook(put_symbol)
                
                # Get best bids and asks (using 'buy' and 'sell')
                call_bids = call_ob.get('buy', [])
                call_asks = call_ob.get('sell', [])
                put_bids = put_ob.get('buy', [])
                put_asks = put_ob.get('sell', [])
                
                if not (call_bids and call_asks and put_bids and put_asks):
                    continue # Skip if orderbook is empty or illiquid
                    
                c_bid = float(call_bids[0]['price'])
                c_ask = float(call_asks[0]['price'])
                p_bid = float(put_bids[0]['price'])
                p_ask = float(put_asks[0]['price'])
                
                # Put-Call Parity calculations
                # Formula: Call - Put = Spot - Strike (discounting risk-free rate as it is near-expiry)
                # Therefore: C - P + Strike - Spot = 0
                
                # -------------------------------------------------------------
                # Arbitrage Scenario 1: Reversal (Synthetic Long Arbitrage)
                # Buy Spot, Buy Put, Sell Call (Synthetic Short)
                # Cost to setup: Spot_Ask + Put_Ask - Call_Bid
                # Value at expiry: Strike Price
                # Profit = Strike - Cost
                # -------------------------------------------------------------
                cost_reversal = spot_price + p_ask - c_bid
                profit_reversal = strike - cost_reversal
                
                if profit_reversal > PROFIT_THRESHOLD_USD:
                    discrepancy_found = True
                    expiry_str = expiry.strftime("%d-%b-%Y")
                    print(f"\n[!!!] ARBITRAGE OPPORTUNITY FOUND (Reversal) [Expiry: {expiry_str} | Strike: {strike}]")
                    print(f"  Action: BUY Spot (${spot_price:.2f}), BUY Put ({put_symbol} @ ${p_ask:.2f}), SELL Call ({call_symbol} @ ${c_bid:.2f})")
                    print(f"  Total Cost: ${cost_reversal:.2f} | Guaranteed Payout: ${strike:.2f}")
                    print(f"  Estimated Profit: ${profit_reversal:.2f} per contract")
                    print("-" * 70)
                    
                # -------------------------------------------------------------
                # Arbitrage Scenario 2: Conversion (Synthetic Short Arbitrage)
                # Sell Spot (Short), Sell Put, Buy Call
                # Credit to setup: Call_Ask - Put_Bid + Strike
                # Cost to close: Spot_Bid
                # Profit = Credit - Spot_Bid = Spot_Bid + Put_Bid - Call_Ask - Strike
                # -------------------------------------------------------------
                profit_conversion = spot_price + p_bid - c_ask - strike
                
                if profit_conversion > PROFIT_THRESHOLD_USD:
                    discrepancy_found = True
                    expiry_str = expiry.strftime("%d-%b-%Y")
                    print(f"\n[!!!] ARBITRAGE OPPORTUNITY FOUND (Conversion) [Expiry: {expiry_str} | Strike: {strike}]")
                    print(f"  Action: SHORT Spot (${spot_price:.2f}), BUY Call ({call_symbol} @ ${c_ask:.2f}), SELL Put ({put_symbol} @ ${p_bid:.2f})")
                    print(f"  Net Setup Cost: ${c_ask - p_bid + strike:.2f} | Closing Value: ${spot_price:.2f}")
                    print(f"  Estimated Profit: ${profit_conversion:.2f} per contract")
                    print("-" * 70)
                
                # Small delay between pairs to prevent aggressive API rate-limiting
                time.sleep(0.1)
                
            if not discrepancy_found:
                print("  No pricing loopholes found in this cycle. Markets are currently efficient.")
                
            print(f"[INFO] Scanning complete. Sleeping 10 seconds before next scan...\n")
            time.sleep(10)
            
        except KeyboardInterrupt:
            print("\n[INFO] Exiting scanner gracefully. Goodbye!")
            break
        except Exception as e:
            print(f"\n[!] Error in scanner loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
