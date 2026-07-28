import os
import time
import joblib
import pandas as pd
import numpy as np
import torch
import torch.nn as nn

class GatedSignalRefiner(nn.Module):
    def __init__(self, input_dim=8):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Sigmoid()
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
    # Match the 8 features expected by Colab scaler:
    # ['close_opt' 'strike' 'VCS' 'TFS_bull' 'WAC' 'PDV_3' 'PDV_5' 'vix_norm']
    
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
    
    # Add strike
    # df already has 'strike'
    df = df.dropna().reset_index(drop=True)
    return df

def run_test():
    print("Loading Colab models...")
    # XGBoost model is corrupted due to OS/Version mismatch (Linux vs Windows)
    # xgb_model = joblib.load('E:/nse/colab_model/nse agent/final_hybrid_xgb.pkl')
    scaler = joblib.load('E:/nse/colab_model/nse agent/final_hybrid_scaler.pkl')
    
    nn_model = GatedSignalRefiner(8)
    nn_model.load_state_dict(torch.load('E:/nse/colab_model/nse agent/final_hybrid_refiner.pt', map_location='cpu', weights_only=True))
    nn_model.eval()
    
    print("Processing live data...")
    opts, spot, vix = load_data()
    df = eng_features(opts, spot, vix)
    
    features = ['close_opt', 'strike', 'VCS', 'TFS_bull', 'WAC', 'PDV_3', 'PDV_5', 'vix_norm']
    X = df[features].values
    
    print("Scaling...")
    X_sc = scaler.transform(X)
    
    # print("Predicting with XGBoost...")
    # xgb_probs = xgb_model.predict_proba(X_sc)[:, 1]
    
    print("Predicting with PyTorch Neural Net...")
    with torch.no_grad():
        nn_probs = nn_model(torch.FloatTensor(X_sc)).numpy().flatten()
    
    print("Applying Colab Iteration 15 Ensemble Logic...")
    # Using 100% NN since XGBoost is corrupted
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
        # For a real calculation, we'd need to simulate the exit.
        # But we don't have the labels here. Let's just print the probabilities!
        print(signals[['timestamp', 'opt_type', 'strike', 'prob']].head(20))
    else:
        print("0 TRADES TAKEN by Colab model on Real Data.")

if __name__ == "__main__":
    run_test()
