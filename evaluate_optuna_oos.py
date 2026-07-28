import numpy as np
import pandas as pd
import joblib
import xgboost as xgb

TARGET_PTS  = 10.0
STOP_PTS    = 5.0
PREM_LOW    = 50.0
PREM_HIGH   = 65.0
QTY         = 25

print("Loading Data & Re-engineering features...")
opts = pd.read_csv('live_data/NIFTY_options_60d.csv')
spot = pd.read_csv('live_data/NIFTY_spot_60d.csv')
try:
    vix  = pd.read_csv('nifty_vix_1y_5min.csv')
except FileNotFoundError:
    vix = pd.DataFrame({'timestamp': spot['timestamp'], 'close': 15.0})

opts['timestamp'] = pd.to_datetime(opts['timestamp']).dt.tz_localize(None)
spot['timestamp'] = pd.to_datetime(spot['timestamp']).dt.tz_localize(None)
vix['timestamp'] = pd.to_datetime(vix['timestamp']).dt.tz_localize(None)

s = spot.copy()
s['H'] = s['high']; s['L'] = s['low']; s['O'] = s['open']; s['C'] = s['close']; s['spot_close'] = s['close']
s['range'] = s['H'] - s['L']
s['atr_5'] = s['range'].rolling(5).mean()
s['atr_20'] = s['range'].rolling(20).mean()
s['VCS'] = np.where(s['atr_20'] > 0, s['atr_5'] / s['atr_20'], 1.0)
s['TFS_bull'] = (s['C'] - s['L']) / s['range'].replace(0, 1)
upper = s['H'] - s[['O','C']].max(axis=1)
lower = s[['O','C']].min(axis=1) - s['L']
s['WAC'] = np.where(s['range'] > 0, (upper - lower) / s['range'], 0)
s['PDV_3'] = (s['C'] - s['C'].shift(3)) / s['atr_5'].replace(0, 1)
s['PDV_5'] = (s['C'] - s['C'].shift(5)) / s['atr_5'].replace(0, 1)
vix_s = vix.rename(columns={'close':'vix_val'}).sort_values('timestamp')
s = pd.merge_asof(s.sort_values('timestamp'), vix_s[['timestamp', 'vix_val']], on='timestamp', direction='backward')
s['vix_norm'] = s['vix_val'] / 20.0

opts = opts.rename(columns={'close': 'close_opt'})
df = pd.merge(opts, s[['timestamp', 'spot_close', 'VCS', 'TFS_bull', 'WAC', 'PDV_3', 'PDV_5', 'vix_norm', 'C', 'atr_5']], on='timestamp', how='inner')
df = df.dropna().reset_index(drop=True)
df['moneyness'] = df['spot_close'] / df['strike']

cands = df[(df['close_opt'] >= PREM_LOW) & (df['close_opt'] <= PREM_HIGH)].copy()

cands['future_max'] = cands.groupby('symbol')['close_opt'].transform(lambda x: x.shift(-12).rolling(12, min_periods=1).max())
cands['future_min'] = cands.groupby('symbol')['close_opt'].transform(lambda x: x.shift(-12).rolling(12, min_periods=1).min())

def label_trade(row):
    if pd.isna(row['future_max']): return 0
    if row['future_max'] >= row['close_opt'] + TARGET_PTS and row['future_min'] > row['close_opt'] - STOP_PTS:
        return 1
    return 0

cands['WIN'] = cands.apply(label_trade, axis=1)

features = ['close_opt', 'strike', 'VCS', 'TFS_bull', 'WAC', 'PDV_3', 'PDV_5', 'vix_norm', 'atr_5', 'moneyness']
cands = cands.dropna(subset=features + ['WIN']).sort_values('timestamp').reset_index(drop=True)

X = cands[features].values
y = cands['WIN'].values

# Split Data to get the exact 30% OOS
split_idx = int(len(X) * 0.70)
X_oos = X[split_idx:]
y_oos = y[split_idx:]
timestamps_oos = cands['timestamp'].values[split_idx:]
close_opt_oos = cands['close_opt'].values[split_idx:]

print(f"OOS Set Size: {len(X_oos)}")

# Load Scaler
scaler = joblib.load('optuna_scaler.pkl')
X_oos_sc = scaler.transform(X_oos)

# Load Best Model as raw Booster to avoid sklearn wrapper issues
print("\nLoading Best Model Checkpoint for True Out-of-Sample Test...")
best_model = xgb.Booster()
best_model.load_model('optuna_best_xgb.json')
dmatrix_oos = xgb.DMatrix(X_oos_sc)
y_proba_oos = best_model.predict(dmatrix_oos)

print("Predicting on 30% Unseen OOS Data...\n")
for thresh in [0.55, 0.60, 0.65]:
    mask = y_proba_oos >= thresh
    preds = y_oos[mask]
    signals = len(preds)
    if signals > 0:
        wr = preds.mean() * 100
        pnl = (preds * TARGET_PTS + (1-preds) * (-STOP_PTS)).sum() * QTY
        print(f"Thresh {thresh:.2f} | Signals: {signals:>4} | WinRate: {wr:.1f}% | OOS PnL: Rs {pnl:,.0f}")
    else:
        print(f"Thresh {thresh:.2f} | Signals:    0 | WinRate: 0.0% | OOS PnL: Rs 0")

