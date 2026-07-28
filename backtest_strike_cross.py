import pandas as pd
import numpy as np
import datetime
import os
import sys
import time

try:
    from angel_client import AngelOneClient
except ImportError:
    print("Could not import AngelOneClient")

def fetch_data(exchange, symboltoken, interval, start_dt, end_dt):
    client = AngelOneClient()
    if not client.login():
        print("Login failed")
        return []
    
    all_data = []
    current_start = start_dt
    
    while current_start < end_dt:
        current_end = current_start + datetime.timedelta(days=30)
        if current_end > end_dt:
            current_end = end_dt
            
        req_data = {
            "exchange": exchange,
            "symboltoken": symboltoken,
            "interval": interval,
            "fromdate": current_start.strftime("%Y-%m-%d %H:%M"),
            "todate": current_end.strftime("%Y-%m-%d %H:%M")
        }
        
        print(f"Fetching {symboltoken} from {req_data['fromdate']} to {req_data['todate']}")
        res = client.get_candle_data_throttled(req_data)
        
        if res and res.get("status") and res.get("data"):
            all_data.extend(res["data"])
            current_start = current_end + datetime.timedelta(minutes=5)
            time.sleep(2)
        else:
            print("Error or empty response:", res)
            msg = res.get("message", "") if res else ""
            if msg == "Too Many Requests" or "exceeding access rate" in str(msg) or "Access denied" in str(msg):
                print("Rate limit hit, sleeping for 5 seconds...")
                time.sleep(5)
                continue
            else:
                current_start = current_end + datetime.timedelta(minutes=5)
                time.sleep(2)
    return all_data

def get_data(name, exch, token, days=365):
    filename = f"{name.lower()}_1y_5min.csv"
    if os.path.exists(filename):
        print(f"Loading {name} from {filename}")
        df = pd.read_csv(filename, parse_dates=['timestamp'])
        return df
    
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=days)
    
    print(f"Downloading 1 year 5-min data for {name}...")
    data = fetch_data(exch, token, "FIVE_MINUTE", start_date, end_date)
    if not data:
        print(f"Failed to fetch 1 year data for {name}. Falling back to 6m if available.")
        fallback = f"{name.lower()}_6m_5min.csv"
        if os.path.exists(fallback):
             df = pd.read_csv(fallback, parse_dates=['timestamp'])
             return df
        return pd.DataFrame()
        
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df.to_csv(filename, index=False)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

def run_backtest():
    # 1. Download/Load Data
    sensex_df = get_data("SENSEX", "BSE", "99919000", 365)
    nifty_df = get_data("NIFTY", "NSE", "99926000", 365)
    
    if sensex_df.empty or nifty_df.empty:
        print("Data missing, exiting.")
        return

    sensex_df.set_index('timestamp', inplace=True)
    nifty_df.set_index('timestamp', inplace=True)
    
    # Ensure both dataframes are aligned
    df = pd.merge(sensex_df, nifty_df, left_index=True, right_index=True, suffixes=('_sx', '_nf'))
    df.sort_index(inplace=True)
    
    # 2. Define the Conditions
    # Condition 1: Sensex crosses a 100-point strike and closes 10-20 points above it.
    df['sx_strike'] = (df['close_sx'] // 100) * 100
    df['sx_close_diff'] = df['close_sx'] - df['sx_strike']
    df['sx_crossed'] = df['low_sx'] < df['sx_strike']
    df['sx_cond'] = df['sx_crossed'] & (df['sx_close_diff'] >= 10) & (df['sx_close_diff'] <= 20)
    
    # Condition 2: Nifty crosses a 50-point strike and closes 10-20 points above it.
    df['nf_strike'] = (df['close_nf'] // 50) * 50
    df['nf_close_diff'] = df['close_nf'] - df['nf_strike']
    df['nf_crossed'] = df['low_nf'] < df['nf_strike']
    df['nf_cond'] = df['nf_crossed'] & (df['nf_close_diff'] >= 10) & (df['nf_close_diff'] <= 20)
    
    # The Setup: Sensex condition happens on candle T-1, Nifty condition happens on candle T.
    df['setup_triggered'] = df['sx_cond'].shift(1) & df['nf_cond']
    
    signals = df[df['setup_triggered']].copy()
    print(f"\n--- Backtest Started ---")
    print(f"Total trading periods analyzed: {len(df)}")
    print(f"Total setups found: {len(signals)}")
    
    if len(signals) == 0:
        print("No instances found matching the exact criteria in the given period.")
        return
        
    # 3. Analyze Forward Movement
    results = []
    
    for idx, row in signals.iterrows():
        pos = df.index.get_loc(idx)
        
        # We look at the next 15 candles (75 minutes)
        if pos + 15 < len(df):
            fwd_data = df.iloc[pos+1 : pos+16] 
            
            entry_nf = row['close_nf']
            # Max Up move in next 15 candles
            max_nf_up = fwd_data['high_nf'].max() - entry_nf
            # Max Down move in next 15 candles (positive number means it went down X points)
            max_nf_down = entry_nf - fwd_data['low_nf'].min()
            # Avg points closed away from entry after 15 candles
            avg_nf_move = fwd_data['close_nf'].mean() - entry_nf
            
            entry_sx = row['close_sx']
            max_sx_up = fwd_data['high_sx'].max() - entry_sx
            max_sx_down = entry_sx - fwd_data['low_sx'].min()
            avg_sx_move = fwd_data['close_sx'].mean() - entry_sx
            
            # Additional granular metrics: max move in first 3 candles, 5 candles
            fwd_3 = df.iloc[pos+1 : pos+4]
            nf_max_up_3 = fwd_3['high_nf'].max() - entry_nf
            nf_max_down_3 = entry_nf - fwd_3['low_nf'].min()
            
            results.append({
                'timestamp': idx,
                'nifty_entry': entry_nf,
                'sensex_entry': entry_sx,
                
                'nf_max_up_3_candles': nf_max_up_3,
                'nf_max_down_3_candles': nf_max_down_3,
                
                'nf_max_up_15_candles': max_nf_up,
                'nf_max_down_15_candles': max_nf_down,
                'nf_avg_move_15_candles': avg_nf_move,
                
                'sx_max_up_15_candles': max_sx_up,
                'sx_max_down_15_candles': max_sx_down,
                'sx_avg_move_15_candles': avg_sx_move,
            })
            
    res_df = pd.DataFrame(results)
    res_df.to_csv("setup_backtest_results.csv", index=False)
    
    print("\n--- Backtest Report ---")
    print(f"Total valid signals with forward data: {len(res_df)}")
    
    print("\nNifty Forward Movement (Next 3 Candles / 15 mins):")
    print(f"Average Max Up Move: +{res_df['nf_max_up_3_candles'].mean():.2f} points")
    print(f"Average Max Down Move: -{res_df['nf_max_down_3_candles'].mean():.2f} points")
    
    print("\nNifty Forward Movement (Next 15 Candles / 75 mins):")
    print(f"Average Max Up Move: +{res_df['nf_max_up_15_candles'].mean():.2f} points")
    print(f"Average Max Down Move: -{res_df['nf_max_down_15_candles'].mean():.2f} points")
    print(f"Average Close Diff (Directional Drift): {res_df['nf_avg_move_15_candles'].mean():.2f} points")
    
    print("\nSensex Forward Movement (Next 15 Candles / 75 mins):")
    print(f"Average Max Up Move: +{res_df['sx_max_up_15_candles'].mean():.2f} points")
    print(f"Average Max Down Move: -{res_df['sx_max_down_15_candles'].mean():.2f} points")
    print(f"Average Close Diff (Directional Drift): {res_df['sx_avg_move_15_candles'].mean():.2f} points")
    
    # Calculate Probability of a +30 point move in Nifty before a -20 point stoploss
    def prob_calc(row):
        # We need the path to check if +30 or -20 hits first. Since we just have 15 candles, we'll approximate.
        # This is basic approximation.
        pass

    # Save artifact as markdown
    with open("backtest_report.md", "w") as f:
        f.write("# Backtest Report: Strike Crossing Setup\n\n")
        f.write("## Setup Rules\n")
        f.write("1. **Sensex Condition (Candle T-1)**: Price low is below a 100-point strike (e.g., 75000, 75100), and closes 10-20 points above it.\n")
        f.write("2. **Nifty Condition (Candle T)**: Next candle, Nifty low is below a 50-point strike (e.g., 23400, 23450), and closes 10-20 points above it.\n\n")
        f.write(f"**Total Trading Periods Analyzed:** {len(df)}\n")
        f.write(f"**Total Setups Found:** {len(signals)}\n\n")
        
        f.write("## Results (Averages)\n")
        f.write("### Nifty Next 3 Candles (15 minutes)\n")
        f.write(f"- **Max Up Move:** +{res_df['nf_max_up_3_candles'].mean():.2f} points\n")
        f.write(f"- **Max Down Move:** -{res_df['nf_max_down_3_candles'].mean():.2f} points\n\n")
        
        f.write("### Nifty Next 15 Candles (75 minutes)\n")
        f.write(f"- **Max Up Move:** +{res_df['nf_max_up_15_candles'].mean():.2f} points\n")
        f.write(f"- **Max Down Move:** -{res_df['nf_max_down_15_candles'].mean():.2f} points\n")
        f.write(f"- **Average Net Drift:** {res_df['nf_avg_move_15_candles'].mean():.2f} points\n\n")
        
        f.write("### Sensex Next 15 Candles (75 minutes)\n")
        f.write(f"- **Max Up Move:** +{res_df['sx_max_up_15_candles'].mean():.2f} points\n")
        f.write(f"- **Max Down Move:** -{res_df['sx_max_down_15_candles'].mean():.2f} points\n")
        f.write(f"- **Average Net Drift:** {res_df['sx_avg_move_15_candles'].mean():.2f} points\n\n")
        
        f.write("Detailed trade logs are saved in `setup_backtest_results.csv`.\n")
        
if __name__ == '__main__':
    run_backtest()
