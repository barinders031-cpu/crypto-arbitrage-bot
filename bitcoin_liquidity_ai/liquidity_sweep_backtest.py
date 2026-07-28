import pandas as pd
import numpy as np

def calculate_rsi(data, window=14):
    delta = data.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=window - 1, adjust=False).mean()
    ema_down = down.ewm(com=window - 1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))

def identify_swings(df, window=10):
    """
    Identify recent swing highs and swing lows.
    """
    df['Swing_High'] = df['High'].rolling(window=window*2+1, center=True).max()
    df['Swing_Low'] = df['Low'].rolling(window=window*2+1, center=True).min()
    
    # Forward fill the swing levels since we only know it after the fact
    # To avoid lookahead bias in trading, we define a swing high if the past 'window' bars and future 'window' bars are lower
    # A practical way to do this in backtesting without lookahead bias at the moment of the sweep:
    # We find the rolling max/min of the LAST N bars, excluding the current bar.
    
    df['Prev_Swing_High'] = df['High'].rolling(window=window).max().shift(1)
    df['Prev_Swing_Low'] = df['Low'].rolling(window=window).min().shift(1)
    return df

def backtest_sweeps(csv_file, target_points=900, swing_window=20, risk_reward_limit=None):
    df = pd.read_csv(csv_file, index_col='Datetime', parse_dates=True)
    df = identify_swings(df, window=swing_window)
    df['RSI'] = calculate_rsi(df['Close'])
    
    # Calculate volume moving average for volume spike detection
    df['Vol_MA'] = df['Volume'].rolling(window=20).mean()
    
    trades = []
    
    # We iterate through to find sweeps
    for i in range(swing_window, len(df)):
        current = df.iloc[i]
        prev = df.iloc[i-1]
        
        # We need the previous swing high/low that has been established
        recent_high = current['Prev_Swing_High']
        recent_low = current['Prev_Swing_Low']
        
        if pd.isna(recent_high) or pd.isna(recent_low):
            continue
            
        trade = None
        
        # 1. Bearish Sweep (Sweeps BSL, looking for Shorts)
        # Price goes above recent high, but closes below it.
        if current['High'] > recent_high and current['Close'] < recent_high:
            # Wick size above the high
            wick_size = current['High'] - max(current['Open'], current['Close'])
            total_size = current['High'] - current['Low']
            
            # Entry logic
            entry_price = current['Close']
            stop_loss = current['High'] + 10  # 10 points buffer
            target = entry_price - target_points
            
            if risk_reward_limit and (entry_price - target) / (stop_loss - entry_price) < risk_reward_limit:
                pass # skip bad R:R
            else:
                trade = {
                    'Type': 'Short',
                    'Entry_Time': df.index[i],
                    'Entry_Price': entry_price,
                    'Stop_Loss': stop_loss,
                    'Target': target,
                    'RSI': current['RSI'],
                    'Vol_Spike': current['Volume'] / current['Vol_MA'] if current['Vol_MA'] > 0 else 1,
                    'Wick_Ratio': wick_size / total_size if total_size > 0 else 0,
                    'Hour': df.index[i].hour
                }
                
        # 2. Bullish Sweep (Sweeps SSL, looking for Longs)
        # Price goes below recent low, but closes above it.
        elif current['Low'] < recent_low and current['Close'] > recent_low:
            wick_size = min(current['Open'], current['Close']) - current['Low']
            total_size = current['High'] - current['Low']
            
            entry_price = current['Close']
            stop_loss = current['Low'] - 10
            target = entry_price + target_points
            
            trade = {
                'Type': 'Long',
                'Entry_Time': df.index[i],
                'Entry_Price': entry_price,
                'Stop_Loss': stop_loss,
                'Target': target,
                'RSI': current['RSI'],
                'Vol_Spike': current['Volume'] / current['Vol_MA'] if current['Vol_MA'] > 0 else 1,
                'Wick_Ratio': wick_size / total_size if total_size > 0 else 0,
                'Hour': df.index[i].hour
            }
            
        if trade:
            # Evaluate trade outcome by looking forward
            outcome = 'Pending'
            exit_time = None
            max_favorable = 0
            
            for j in range(i+1, len(df)):
                future_bar = df.iloc[j]
                if trade['Type'] == 'Short':
                    max_favorable = max(max_favorable, trade['Entry_Price'] - future_bar['Low'])
                    if future_bar['High'] >= trade['Stop_Loss']:
                        outcome = 'Loss'
                        exit_time = df.index[j]
                        break
                    if future_bar['Low'] <= trade['Target']:
                        outcome = 'Win'
                        exit_time = df.index[j]
                        break
                elif trade['Type'] == 'Long':
                    max_favorable = max(max_favorable, future_bar['High'] - trade['Entry_Price'])
                    if future_bar['Low'] <= trade['Stop_Loss']:
                        outcome = 'Loss'
                        exit_time = df.index[j]
                        break
                    if future_bar['High'] >= trade['Target']:
                        outcome = 'Win'
                        exit_time = df.index[j]
                        break
            
            if outcome != 'Pending':
                trade['Outcome'] = outcome
                trade['Exit_Time'] = exit_time
                trade['Max_Favorable'] = max_favorable
                trades.append(trade)

    trades_df = pd.DataFrame(trades)
    if not trades_df.empty:
        print(f"Total Trades: {len(trades_df)}")
        print(f"Wins: {len(trades_df[trades_df['Outcome'] == 'Win'])}")
        print(f"Losses: {len(trades_df[trades_df['Outcome'] == 'Loss'])}")
        win_rate = len(trades_df[trades_df['Outcome'] == 'Win']) / len(trades_df) * 100
        print(f"Win Rate: {win_rate:.2f}%")
        trades_df.to_csv('backtest_results.csv', index=False)
    else:
        print("No trades found.")
        
    return trades_df

if __name__ == "__main__":
    print("Running Backtest on 5m data...")
    backtest_sweeps('btc_5m_data.csv', target_points=800, swing_window=30)
