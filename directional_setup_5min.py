import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

def load_data():
    nifty = pd.read_csv('nifty_6m_5min.csv', parse_dates=['timestamp']).set_index('timestamp')
    sensex = pd.read_csv('sensex_6m_5min.csv', parse_dates=['timestamp']).set_index('timestamp')
    
    df = nifty[['high', 'low', 'close']].join(sensex[['high', 'low', 'close']], rsuffix='_sensex', how='inner')
    df.columns = ['high_nifty', 'low_nifty', 'close_nifty', 'high_sensex', 'low_sensex', 'close_sensex']
    df = df.dropna()
    return df

def analyze_directional_setups(df):
    print(f"Total Rows (5-min candles): {len(df)}")
    
    # Target: 60-minute Forward Return (12 candles of 5 mins)
    forward_window = 12
    df['fwd_pts_nifty'] = df['close_nifty'].shift(-forward_window) - df['close_nifty']
    
    # Lookback for High/Low: 1 Day (75 candles)
    lookback = 75
    df['nifty_high_1d'] = df['high_nifty'].rolling(lookback).max()
    df['nifty_low_1d'] = df['low_nifty'].rolling(lookback).min()
    
    df['sensex_high_1d'] = df['high_sensex'].rolling(lookback).max()
    df['sensex_low_1d'] = df['low_sensex'].rolling(lookback).min()
    
    # Identify New Daily Highs/Lows
    df['nifty_new_high'] = df['high_nifty'] >= df['nifty_high_1d'].shift(1)
    df['nifty_new_low'] = df['low_nifty'] <= df['nifty_low_1d'].shift(1)
    
    df['sensex_new_high'] = df['high_sensex'] >= df['sensex_high_1d'].shift(1)
    df['sensex_new_low'] = df['low_sensex'] <= df['sensex_low_1d'].shift(1)
    
    df = df.dropna()
    
    # SETUP 1: DIVERGENCE (Trend Reversal)
    # Nifty makes new Daily high, but Sensex does NOT -> Bearish Reversal
    div_bear = df[df['nifty_new_high'] & (~df['sensex_new_high'])]
    # Nifty makes new Daily low, but Sensex does NOT -> Bullish Reversal
    div_bull = df[df['nifty_new_low'] & (~df['sensex_new_low'])]
    
    # Let's also check the opposite:
    # Sensex makes new High, Nifty doesn't -> Bearish
    div_bear_2 = df[df['sensex_new_high'] & (~df['nifty_new_high'])]
    # Sensex makes new Low, Nifty doesn't -> Bullish
    div_bull_2 = df[df['sensex_new_low'] & (~df['nifty_new_low'])]
    
    def print_stats(name, signal_df, direction_is_up):
        count = len(signal_df)
        if count == 0: return
        
        if direction_is_up:
            win_rate = (signal_df['fwd_pts_nifty'] > 15).mean() * 100 # > 15 pts to cover slippage
            avg_pts = signal_df['fwd_pts_nifty'].mean()
        else:
            win_rate = (signal_df['fwd_pts_nifty'] < -15).mean() * 100
            avg_pts = -signal_df['fwd_pts_nifty'].mean() 
            
        print(f"\n--- {name} ---")
        print(f"Total Signals: {count}")
        print(f"Win Rate (Net of 15 pts slippage): {win_rate:.2f}%")
        print(f"Average Nifty Points Captured: {avg_pts:.2f} Points")
        
    print("\n================ DIVERGENCE (EXPECT REVERSAL) ================")
    print_stats("Bearish Divergence (Nifty hits High, Sensex doesn't)", div_bear, direction_is_up=False)
    print_stats("Bullish Divergence (Nifty hits Low, Sensex doesn't)", div_bull, direction_is_up=True)
    
    print_stats("Bearish Divergence 2 (Sensex hits High, Nifty doesn't)", div_bear_2, direction_is_up=False)
    print_stats("Bullish Divergence 2 (Sensex hits Low, Nifty doesn't)", div_bull_2, direction_is_up=True)

if __name__ == '__main__':
    df = load_data()
    analyze_directional_setups(df)
