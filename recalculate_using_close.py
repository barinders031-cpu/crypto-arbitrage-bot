import pandas as pd
import numpy as np
import os

def recalculate_using_first_candle_close():
    if not os.path.exists("nifty_1y_5min.csv") or not os.path.exists("sensex_1y_5min.csv"):
        print("Data files not found.")
        return
        
    print("Loading Data...\n")
    df_nf = pd.read_csv("nifty_1y_5min.csv", parse_dates=['timestamp'])
    df_sx = pd.read_csv("sensex_1y_5min.csv", parse_dates=['timestamp'])
    
    df_nf.set_index('timestamp', inplace=True)
    df_sx.set_index('timestamp', inplace=True)
    
    df = pd.merge(df_nf, df_sx, left_index=True, right_index=True, suffixes=('_nf', '_sx'))
    df['date'] = df.index.date
    df['time'] = df.index.time
    
    total_days = 0
    
    # Short Reversal Variables
    bearish_reversals_triggered = 0
    short_success = 0
    short_points_list = []
    
    # Long Reversal Variables
    bullish_reversals_triggered = 0
    long_success = 0
    long_points_list = []
    
    for date, group in df.groupby('date'):
        total_days += 1
        group = group.sort_index()
        
        # USE THE CLOSE OF THE FIRST CANDLE
        first_close_nf = group.iloc[0]['close_nf']
        
        # --- SHORT REVERSAL LOGIC (Distance calculated from First Close) ---
        morning_high = group['high_nf'].max()
        morning_high_idx = group['high_nf'].idxmax()
        
        if morning_high - first_close_nf >= 50: # The baseline condition for a "stretch"
            bearish_reversals_triggered += 1
            post_high_data = group.loc[morning_high_idx:]
            if not post_high_data.empty:
                lowest_after_high = post_high_data['low_nf'].min()
                fall_points = morning_high - lowest_after_high
                if fall_points >= 40:
                    short_success += 1
                    short_points_list.append(fall_points)
                    
        # --- LONG REVERSAL LOGIC (Distance calculated from First Close) ---
        morning_low = group['low_nf'].min()
        morning_low_idx = group['low_nf'].idxmin()
        
        if first_close_nf - morning_low >= 50: # Baseline condition for downward stretch
            bullish_reversals_triggered += 1
            post_low_data = group.loc[morning_low_idx:]
            if not post_low_data.empty:
                highest_after_low = post_low_data['high_nf'].max()
                bounce_points = highest_after_low - morning_low
                if bounce_points >= 40:
                    long_success += 1
                    long_points_list.append(bounce_points)
                    
    print("="*60)
    print("NEW CALCULATION: BASED ON 9:15 CANDLE 'CLOSE'")
    print("="*60)
    print(f"Total Trading Days Analyzed: {total_days}")
    
    print("\n1. SHORT REVERSALS (Market upar gaya First Close se, fir gira)")
    print(f"Market first close se 50+ points upar gaya: {bearish_reversals_triggered} days")
    if bearish_reversals_triggered > 0:
        print(f"Successfully Reversed (40+ points fall): {short_success} times")
        print(f"Accuracy: {(short_success/bearish_reversals_triggered)*100:.1f}%")
        print(f"Average Fall: {np.mean(short_points_list):.1f} points")
        
    print("\n2. LONG REVERSALS (Market first close se neeche gira, fir bounce hua)")
    print(f"Market first close se 50+ points neeche gira: {bullish_reversals_triggered} days")
    if bullish_reversals_triggered > 0:
        print(f"Successfully Bounced (40+ points recovery): {long_success} times")
        print(f"Accuracy: {(long_success/bullish_reversals_triggered)*100:.1f}%")
        print(f"Average Bounce: {np.mean(long_points_list):.1f} points")

if __name__ == "__main__":
    recalculate_using_first_candle_close()
