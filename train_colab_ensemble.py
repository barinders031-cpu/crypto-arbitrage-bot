import os
import joblib
import time
import warnings
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset, DataLoader
from sklearn.preprocessing import RobustScaler
from sklearn.utils.class_weight import compute_class_weight
from xgboost import XGBClassifier

warnings.filterwarnings('ignore')

# Config
TARGET_PTS  = 10.0
STOP_PTS    = 5.0
PREM_LOW    = 50.0
PREM_HIGH   = 80.0  # Slightly wider range for robust training sample size
QTY         = 25    # Lot size
MAX_CANDLES = 12    # 1 hour look-ahead

class GatedSignalRefiner(nn.Module):
    def __init__(self, input_dim=9):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 128),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid()
        )
    def forward(self, x):
        return self.net(x)

def load_data():
    print("[1/5] Loading data...")
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
    print("[2/5] Engineering features...")
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
    
    # PDV_3 and PDV_5
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

def label_data(df, opts_raw):
    print("[3/5] Labeling winner/loser trades...")
    # Filter candidates
    cands = df[(df['close_opt'] >= PREM_LOW) & (df['close_opt'] <= PREM_HIGH)].copy()
    
    # Pre-build lookup groups
    opts_s = opts_raw.sort_values(['strike', 'opt_type', 'expiry', 'timestamp'])
    opt_groups = {key: grp.reset_index(drop=True) for key, grp in opts_s.groupby(['strike', 'opt_type', 'expiry'])}
    
    labels = []
    for i, (_, row) in enumerate(cands.iterrows()):
        key = (row['strike'], row['opt_type'], row['expiry'])
        if key not in opt_groups:
            labels.append(-1)
            continue
        grp = opt_groups[key]
        fwd = grp[grp['timestamp'] > row['timestamp']].head(MAX_CANDLES)
        tp = row['close_opt'] + TARGET_PTS
        sl = row['close_opt'] - STOP_PTS
        lbl = 0
        for _, fr in fwd.iterrows():
            if fr['close'] >= tp:
                lbl = 1
                break
            if fr['close'] <= sl:
                lbl = 0
                break
        labels.append(lbl)
        
    cands['WIN'] = labels
    cands = cands[cands['WIN'] >= 0].copy()
    print(f"  Total labeled candidates: {len(cands)}")
    print(f"  WIN: {(cands.WIN == 1).sum()} | LOSS: {(cands.WIN == 0).sum()} | Base Win Rate: {cands.WIN.mean()*100:.2f}%")
    return cands, opt_groups

def main():
    t_start = time.time()
    opts_raw, spot, vix = load_data()
    df = eng_features(opts_raw, spot, vix)
    cands, opt_groups = label_data(df, opts_raw)
    
    features = ['close_opt', 'strike', 'VCS', 'TFS_bull', 'WAC', 'PDV_3', 'PDV_5', 'vix_norm', 'atr_5']
    X = cands[features].values
    y = cands['WIN'].values
    
    # Chronological Split (70% Train, 10% Val, 20% Out-of-Sample Test)
    split_train = int(len(X) * 0.70)
    split_val = int(len(X) * 0.80)
    
    scaler = RobustScaler()
    X_train_sc = scaler.fit_transform(X[:split_train])
    X_val_sc   = scaler.transform(X[split_train:split_val])
    X_test_sc  = scaler.transform(X[split_val:])
    
    y_train = y[:split_train]
    y_val   = y[split_train:split_val]
    y_test  = y[split_val:]
    
    print(f"\n[4/5] Training models (Train={len(X_train_sc)}, Val={len(X_val_sc)}, Test={len(X_test_sc)})...")
    
    # --- 1. Train XGBoost ---
    print("  -> Training XGBoost (CPU)...")
    cw = compute_class_weight('balanced', classes=np.array([0,1]), y=y_train)
    spw = cw[1]/cw[0]
    
    xgb_model = XGBClassifier(
        n_estimators=1200,
        learning_rate=0.01,
        max_depth=5,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=spw,
        tree_method='hist',
        device='cpu',
        random_state=42,
        early_stopping_rounds=40,
        eval_metric='auc',
        verbosity=0
    )
    xgb_model.fit(
        X_train_sc, y_train,
        eval_set=[(X_val_sc, y_val)],
        verbose=False
    )
    print(f"     XGBoost trained. Best iteration: {xgb_model.best_iteration}")
    
    # --- 2. Train PyTorch NN ---
    print("  -> Training PyTorch Neural Net (CPU)...")
    device = torch.device('cpu')
    nn_model = GatedSignalRefiner(input_dim=9).to(device)
    
    train_dataset = TensorDataset(torch.FloatTensor(X_train_sc), torch.FloatTensor(y_train).unsqueeze(1))
    train_loader = DataLoader(train_dataset, batch_size=128, shuffle=True)
    
    criterion = nn.BCELoss()
    optimizer = optim.Adam(nn_model.parameters(), lr=0.001, weight_decay=1e-5)
    
    nn_model.train()
    for epoch in range(1, 36):
        epoch_loss = 0.0
        for batch_x, batch_y in train_loader:
            optimizer.zero_grad()
            outputs = nn_model(batch_x)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            
        if epoch % 10 == 0 or epoch == 1:
            # Eval on Val
            nn_model.eval()
            with torch.no_grad():
                val_outputs = nn_model(torch.FloatTensor(X_val_sc)).numpy().flatten()
                val_loss = criterion(torch.FloatTensor(val_outputs).unsqueeze(1), torch.FloatTensor(y_val).unsqueeze(1)).item()
            nn_model.train()
            print(f"     Epoch {epoch:02d}/35 | Train Loss: {epoch_loss/len(train_loader):.5f} | Val Loss: {val_loss:.5f}")
            
    nn_model.eval()
    print("     PyTorch GatedSignalRefiner trained.")
    
    # --- 3. Evaluate Ensemble on Out-of-Sample Test ---
    print("\n[5/5] Evaluating Hybrid Ensemble on 20% Unseen OOS Test Data...")
    
    xgb_probs = xgb_model.predict_proba(X_test_sc)[:, 1]
    with torch.no_grad():
        nn_probs = nn_model(torch.FloatTensor(X_test_sc)).numpy().flatten()
        
    hybrid_probs = (0.5 * nn_probs) + (0.5 * xgb_probs)
    
    test_df = cands.iloc[split_val:].copy().reset_index(drop=True)
    test_df['prob'] = hybrid_probs
    
    # Threshold test
    best_thresh = 0.42
    signals = test_df[test_df['prob'] >= best_thresh].copy()
    
    print(f"  Out-of-Sample Period: {test_df.timestamp.min().date()} to {test_df.timestamp.max().date()}")
    print(f"  Total candidate options processed: {len(test_df)}")
    print(f"  Ensemble Signals Found (prob >= {best_thresh}): {len(signals)}")
    
    if len(signals) > 0:
        trades = []
        for _, row in signals.iterrows():
            key = (row['strike'], row['opt_type'], row['expiry'])
            if key not in opt_groups: continue
            grp = opt_groups[key]
            fwd = grp[grp['timestamp'] > row['timestamp']].head(MAX_CANDLES)
            tp = row['close_opt'] + TARGET_PTS
            sl = row['close_opt'] - STOP_PTS
            win = 0
            for _, fr in fwd.iterrows():
                if fr['close'] >= tp: win = 1; break
                if fr['close'] <= sl: win = 0; break
            pnl = (TARGET_PTS if win else -STOP_PTS) * QTY
            trades.append(pnl)
            
        trades = np.array(trades)
        win_rate = (trades > 0).mean() * 100
        net_pnl = trades.sum()
        print(f"  --- Out-of-Sample Performance Summary (Threshold {best_thresh}) ---")
        print(f"  Total Trades Taken: {len(trades)}")
        print(f"  Win Rate          : {win_rate:.2f}%")
        print(f"  Net PnL           : Rs. {net_pnl:,.2f}")
    else:
        print("  No trades taken at threshold 0.42.")
        
    # --- 4. Save Models to Disk ---
    print("\nSaving ensemble model files for test_colab_model_v8.py...")
    joblib.dump(xgb_model, 'ensemble_xgb_v8.pkl')
    joblib.dump(scaler, 'ensemble_scaler_v8.pkl')
    torch.save(nn_model.state_dict(), 'ensemble_refiner_v8.pt')
    
    print("[SUCCESS] All files saved successfully:")
    print("  - E:\\nse\\ensemble_xgb_v8.pkl")
    print("  - E:\\nse\\ensemble_scaler_v8.pkl")
    print("  - E:\\nse\\ensemble_refiner_v8.pt")
    print(f"Total time elapsed: {time.time() - t_start:.1f} seconds.")

if __name__ == '__main__':
    main()
