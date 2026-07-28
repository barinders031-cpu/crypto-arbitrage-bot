"""
Download more Nifty options data - Using 28JUL & 25AUG monthly expiry
These have data going back to May 2026 (2+ months)
Strategy: ATM +/- 15 strikes for both expiries = ~60 symbols x 2500 candles each
"""
import time
import json
import os
import csv
import glob
from datetime import datetime
from angel_client import AngelOneClient

def main():
    client = AngelOneClient()
    if not client.login():
        print("Login failed!")
        return

    # Get current spot (Nifty)
    spot_res = client.get_ltp_data_throttled("NSE", "NIFTY", "99926000")
    nifty_spot = float(spot_res["data"]["ltp"]) if spot_res and spot_res.get("status") else 24400.0
    print(f"Nifty Spot: {nifty_spot}")

    nifty_atm = round(nifty_spot / 50.0) * 50.0
    print(f"Nifty ATM: {nifty_atm}")

    with open('scrip_master.json', 'r') as f:
        scrips = json.load(f)

    # Pick 28JUL2026 and 25AUG2026 (both have 2+ months of history)
    target_expiries = ['28JUL2026', '25AUG2026']
    tokens_to_fetch = []

    for exp in target_expiries:
        exp_scrips = [s for s in scrips 
                      if s.get('name') == 'NIFTY' 
                      and s.get('expiry') == exp 
                      and s.get('instrumenttype') == 'OPTIDX'
                      and s.get('exch_seg') == 'NFO']

        # ATM +/- 15 strikes of 50 = 750 pts each side
        for s in exp_scrips:
            try:
                strike = float(s.get('strike', 0)) / 100.0
                if abs(strike - nifty_atm) <= 750:  # +/- 15 strikes
                    tokens_to_fetch.append(s)
            except:
                pass

    # Also add Nifty Spot for reference
    tokens_to_fetch.append({
        'token': '99926000', 'symbol': 'NIFTY_SPOT', 'exch_seg': 'NSE'
    })

    print(f"Total tokens to download: {len(tokens_to_fetch)}")
    print(f"Estimated time: {len(tokens_to_fetch) * 0.35 / 60:.1f} minutes")

    # Download from May 1 to today
    from_date = "2026-05-01 09:15"
    to_date   = datetime.now().strftime("%Y-%m-%d 15:30")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file  = f"nifty_options_extended_{timestamp}.csv"

    with open(csv_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['token','symbol','exchange','timestamp','open','high','low','close','volume'])
        writer.writeheader()

    success = 0
    empty   = 0
    errors  = 0

    for i, scrip in enumerate(tokens_to_fetch):
        token    = scrip.get('token')
        symbol   = scrip.get('symbol')
        exchange = scrip.get('exch_seg')

        params = {
            'exchange': exchange,
            'symboltoken': token,
            'interval': 'FIVE_MINUTE',
            'fromdate': from_date,
            'todate': to_date
        }

        res = client.get_candle_data_throttled(params)

        if res and res.get('status') and res.get('data'):
            rows = res['data']
            with open(csv_file, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['token','symbol','exchange','timestamp','open','high','low','close','volume'])
                for row in rows:
                    writer.writerow({
                        'token': token, 'symbol': symbol, 'exchange': exchange,
                        'timestamp': row[0], 'open': row[1], 'high': row[2],
                        'low': row[3], 'close': row[4], 'volume': row[5]
                    })
            success += 1
        elif res and res.get('data') == []:
            empty += 1
        else:
            errors += 1

        if (i + 1) % 20 == 0:
            print(f"Processed {i+1}/{len(tokens_to_fetch)} | Success:{success} Empty:{empty} Errors:{errors}")

        time.sleep(0.35)

    print(f"\nDone! Data saved to: {csv_file}")
    print(f"Success: {success} | Empty: {empty} | Errors: {errors}")

    # Quick stats
    import pandas as pd
    df = pd.read_csv(csv_file)
    print(f"Total rows downloaded: {len(df)}")
    print(f"Unique symbols: {df['symbol'].nunique()}")
    print(f"Date range: {df['timestamp'].min()[:10]} to {df['timestamp'].max()[:10]}")

if __name__ == "__main__":
    main()
