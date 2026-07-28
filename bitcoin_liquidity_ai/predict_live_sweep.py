import pandas as pd
import numpy as np
import json
import yfinance as yf
from liquidity_sweep_backtest import identify_swings, calculate_rsi

def sigmoid(z):
    z = np.clip(z, -250, 250)
    return 1 / (1 + np.exp(-z))

def scan_live_sweeps(symbol="BTC-USD", interval="5m", model_file='sweep_model.json', swing_window=30):
    print(f"Fetching latest {interval} data for {symbol}...")
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="5d", interval=interval)
    
    if df.empty:
        print("No data.")
        return
        
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
    df = identify_swings(df, window=swing_window)
    df['RSI'] = calculate_rsi(df['Close'])
    df['Vol_MA'] = df['Volume'].rolling(window=20).mean()
    
    # Load AI Memory
    with open(model_file, 'r') as f:
        model = json.load(f)
        
    weights = np.array(model['weights'])
    bias = model['bias']
    features = model['features']
    mean = np.array(model['mean'])
    std = np.array(model['std'])
    threshold = model['threshold']
    
    # Get the latest completed candle
    current = df.iloc[-2]
    prev = df.iloc[-3]
    recent_high = current['Prev_Swing_High']
    recent_low = current['Prev_Swing_Low']
    
    sweep_detected = False
    
    if pd.isna(recent_high) or pd.isna(recent_low):
        print("Not enough data for swings.")
        return
        
    if current['High'] > recent_high and current['Close'] < recent_high:
        print("Bearish Sweep Detected! (BSL taken)")
        sweep_detected = True
        wick_size = current['High'] - max(current['Open'], current['Close'])
        total_size = current['High'] - current['Low']
        wick_ratio = wick_size / total_size if total_size > 0 else 0
        
    elif current['Low'] < recent_low and current['Close'] > recent_low:
        print("Bullish Sweep Detected! (SSL taken)")
        sweep_detected = True
        wick_size = min(current['Open'], current['Close']) - current['Low']
        total_size = current['High'] - current['Low']
        wick_ratio = wick_size / total_size if total_size > 0 else 0
        
    if sweep_detected:
        vol_spike = current['Volume'] / current['Vol_MA'] if current['Vol_MA'] > 0 else 1
        x = np.array([current['RSI'], vol_spike, wick_ratio, current.name.hour])
        
        # Scale
        x_scaled = (x - mean) / std
        
        # Predict
        linear_model = np.dot(x_scaled, weights) + bias
        prob = sigmoid(linear_model)
        
        print(f"AI Model Probability of 800+ point win: {prob*100:.2f}%")
        if prob > threshold:
            print(">>> AI RECOMMENDS SAFE ENTRY (HIGH PROBABILITY) <<<")
        else:
            print(">>> AI SUGGESTS SKIPPING (LOW PROBABILITY) <<<")
    else:
        print(f"No sweep detected on the most recent completed candle ({current.name}).")

if __name__ == "__main__":
    scan_live_sweeps()
