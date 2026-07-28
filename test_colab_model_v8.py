import os
import time
import joblib
import pandas as pd
import numpy as np
import torch
import torch.nn as nn

class GatedSignalRefiner(nn.Module):
    def __init__(self, input_dim=9):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 128),
            nn.ReLU(),
            nn.Dropout(0.2), # Index 2
            nn.Linear(128, 64), # Index 3
            nn.ReLU(), # Index 4
            nn.Linear(64, 1), # Index 5
            nn.Sigmoid() # Index 6
        )
    def forward(self, x):
        return self.net(x)

def load_data():
    opts = pd.read_csv('live_data/NIFTY_options_60d.csv')
    spot = pd.read_csv('live_data/NIFTY_spot_60d.csv')
    try:
        vix = pd.read_csv('nifty_vix_1y_5min.csv')
    except:
        vix = pd.DataFrame({'timestamp': spot['timestamp'], 'close': 15.0})
    
    opts['timestamp'] = pd.to_datetime(opts['timestamp']).dt.tz_localize(None)
    spot['timestamp'] = pd.to_datetime(spot['timestamp']).dt.tz_localize(None)
    vix['timestamp'] = pd.to_datetime(vix['timestamp']).dt.tz_localize(None)
    return opts, spot, vix

def eng_features(opts, spot, vix):
    # Match the 9 features expected by Colab scaler:
    # ['close_opt' 'strike' 'VCS' 'TFS_bull' 'WAC' 'PDV_3' 'PDV_5' 'vix_norm', 'atr_5']
    
    # 1. Spot Features
    s = spot.copy()
    s['H'] = s['high']; s['L'] = s['low']; s['O'] = s['open']; s['C'] = s['close']
    s['range'] = s['H'] - s['L']
    
    # VCS (Volatility Compression Score)
    s['atr_5'] = s['range'].rolling(5).mean()
    s['atr_20'] = s['range'].rolling(20).mean()
    s['VCS'] = np.where(s['atr_20'] > 0, s['atr_5'] / s['atr_20'], 1.0)
    
    # TFS_bull (Trend Flow Score)
    s['TFS_bull'] = (s['C'] - s['L']) / s['range'].replace(0, 1)
    
    # WAC (Wick Absorption Coefficient)
    upper = s['H'] - s[['O','C']].max(axis=1)
    lower = s[['O','C']].min(axis=1) - s['L']
    s['WAC'] = np.where(s['range'] > 0, (upper - lower) / s['range'], 0)
    
    # PDV_3 and PDV_5 (Using Momentum Divergence as proxy if missing)
    s['PDV_3'] = (s['C'] - s['C'].shift(3)) / s['atr_5'].replace(0, 1)
    s['PDV_5'] = (s['C'] - s['C'].shift(5)) / s['atr_5'].replace(0, 1)
    
    # VIX Norm
    vix_s = vix.rename(columns={'close':'vix_val'}).sort_values('timestamp')
    s = pd.merge_asof(s.sort_values('timestamp'), vix_s[['timestamp', 'vix_val']], on='timestamp', direction='backward')
    s['vix_norm'] = s['vix_val'] / 20.0
    
    # Merge options
    opts = opts.rename(columns={'close': 'close_opt'})
    df = pd.merge(opts, s[['timestamp', 'VCS', 'TFS_bull', 'WAC', 'PDV_3', 'PDV_5', 'vix_norm', 'C', 'atr_5']], on='timestamp', how='inner')
    
    df = df.dropna().reset_index(drop=True)
    return df

def run_test():
    print("Loading Colab models v8...")
    try:
        xgb_model = joblib.load('E:/nse/ensemble_xgb_v8.pkl')
        xgb_loaded = True
    except Exception as e:
        print(f"[WARN] Failed to load XGBoost: {e}")
        xgb_loaded = False
        
    scaler = joblib.load('E:/nse/ensemble_scaler_v8.pkl')
    
    nn_model = GatedSignalRefiner(9)
    nn_model.load_state_dict(torch.load('E:/nse/ensemble_refiner_v8.pt', map_location='cpu', weights_only=True))
    nn_model.eval()
    
    print("Processing live data...")
    opts, spot, vix = load_data()
    df = eng_features(opts, spot, vix)
    
    features = ['close_opt', 'strike', 'VCS', 'TFS_bull', 'WAC', 'PDV_3', 'PDV_5', 'vix_norm', 'atr_5']
    X = df[features].values
    
    print("Scaling...")
    X_sc = scaler.transform(X)
    
    if xgb_loaded:
        print("Predicting with XGBoost...")
        xgb_probs = xgb_model.predict_proba(X_sc)[:, 1]
    
    print("Predicting with PyTorch Neural Net...")
    with torch.no_grad():
        nn_probs = nn_model(torch.FloatTensor(X_sc)).numpy().flatten()
    
    print("Applying Colab Ensemble Logic v8...")
    if xgb_loaded:
        hybrid_probs = (0.5 * nn_probs) + (0.5 * xgb_probs)
    else:
        hybrid_probs = nn_probs
        
    df['prob'] = hybrid_probs
    
    # Colab rules: Base threshold 0.42, VCS > 0.45 or Adaptive VCS (we will just use base threshold first)
    signals = df[df['prob'] >= 0.42].copy()
    
    # ATR Gating (Bottom 30-40th percentile blocked - we'll just check if ATR > median for simplicity)
    atr_median = df['atr_5'].median()
    signals = signals[signals['atr_5'] > atr_median]
    
    print(f"\nFinal Trades found: {len(signals)}")
    if len(signals) > 0:
        print("Calculating Net PnL (QTY=25, Target=10, SL=5)...")
        # Let's print the probabilities and see if anything is close!
        print(signals[['timestamp', 'opt_type', 'strike', 'prob']].head(20))
    else:
        print("0 TRADES TAKEN by Colab model v8 on Real Data.")

if __name__ == "__main__":
    run_test()
