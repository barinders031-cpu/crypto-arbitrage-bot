import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

def load_data():
    nifty = pd.read_csv('nifty_6m_1min.csv', parse_dates=['timestamp']).set_index('timestamp')
    sensex = pd.read_csv('sensex_6m_1min.csv', parse_dates=['timestamp']).set_index('timestamp')
    
    df = nifty[['close']].join(sensex[['close']], rsuffix='_sensex', how='inner')
    df.columns = ['close_nifty', 'close_sensex']
    df = df.dropna()
    return df

def robust_backtest(df):
    print(f"Total Rows: {len(df)}")
    
    # Calculate Ratio and its Z-Score
    df['ratio'] = df['close_sensex'] / df['close_nifty']
    df['ratio_mean_200'] = df['ratio'].rolling(200).mean()
    df['ratio_std_200'] = df['ratio'].rolling(200).std()
    df['ratio_zscore'] = (df['ratio'] - df['ratio_mean_200']) / df['ratio_std_200']
    
    # Calculate Forward Returns (in percentage)
    df['fwd_ret_nifty_15m'] = df['close_nifty'].shift(-15) / df['close_nifty'] - 1
    df['fwd_ret_sensex_15m'] = df['close_sensex'].shift(-15) / df['close_sensex'] - 1
    
    # Outperformance of Nifty over Sensex
    df['fwd_diff'] = df['fwd_ret_nifty_15m'] - df['fwd_ret_sensex_15m']
    
    df = df.dropna()
    
    # Signal conditions
    signal_high = df[df['ratio_zscore'] > 2.0]  # Expect Nifty to outperform Sensex
    signal_low = df[df['ratio_zscore'] < -2.0]  # Expect Sensex to outperform Nifty
    
    # Strict Win Rate: Outperformance must be > 0.05% (5 basis points) to cover slippage/costs
    # 0.05% of Nifty 26000 is ~13 points
    SLIPPAGE_BPS = 2.0  # 2 basis points for slippage & brokerage
    SLIPPAGE_DECIMAL = SLIPPAGE_BPS / 10000.0
    
    def analyze_signal(signal_df, expect_nifty_outperform):
        count = len(signal_df)
        if count == 0: return
        
        if expect_nifty_outperform:
            diff = signal_df['fwd_diff']
        else:
            diff = -signal_df['fwd_diff']
            
        gross_win_rate = (diff > 0).mean() * 100
        net_win_rate = (diff > SLIPPAGE_DECIMAL).mean() * 100
        
        avg_gross_diff = diff.mean() * 10000 # in bps
        
        # When we win, how much do we win?
        avg_win_bps = diff[diff > 0].mean() * 10000
        # When we lose, how much do we lose?
        avg_loss_bps = diff[diff < 0].mean() * 10000
        
        expectancy = diff.mean() * 10000 - SLIPPAGE_BPS # Net average return per trade in bps
        
        print(f"Total Signals: {count}")
        print(f"Gross Win Rate (> 0): {gross_win_rate:.2f}%")
        print(f"Net Win Rate (beating {SLIPPAGE_BPS} bps slippage): {net_win_rate:.2f}%")
        print(f"Avg Outperformance (Gross): {avg_gross_diff:.2f} bps")
        print(f"Avg Win Magnitude: {avg_win_bps:.2f} bps")
        print(f"Avg Loss Magnitude: {avg_loss_bps:.2f} bps")
        print(f"Net Expectancy per trade: {expectancy:.2f} bps")
        print("-" * 30)

    print("\n--- CASE 1: Sensex Expensive (Z > 2.0) -> Expect Nifty to Outperform ---")
    analyze_signal(signal_high, expect_nifty_outperform=True)
    
    print("\n--- CASE 2: Sensex Cheap (Z < -2.0) -> Expect Sensex to Outperform ---")
    analyze_signal(signal_low, expect_nifty_outperform=False)

if __name__ == '__main__':
    df = load_data()
    robust_backtest(df)
