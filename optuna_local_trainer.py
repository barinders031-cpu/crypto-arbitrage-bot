import numpy as np
import pandas as pd
import joblib
import time
import warnings
import os
import optuna
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import accuracy_score, roc_auc_score, precision_score, recall_score
from sklearn.utils.class_weight import compute_class_weight
from xgboost import XGBClassifier
import xgboost as xgb

warnings.filterwarnings('ignore')

TARGET_PTS  = 10.0
STOP_PTS    = 5.0
PREM_LOW    = 50.0
PREM_HIGH   = 65.0
QTY         = 25 # Nifty new lot size

print("********************************************************")
print("*   1-MINUTE OPTUNA LOCAL TRAINING SESSION (XGBOOST)   *")
print("********************************************************\n")

print("Loading Data...")
opts = pd.read_csv('live_data/NIFTY_options_60d.csv')
spot = pd.read_csv('live_data/NIFTY_spot_60d.csv')
try:
    vix  = pd.read_csv('nifty_vix_1y_5min.csv')
except FileNotFoundError:
    vix = pd.DataFrame({'timestamp': spot['timestamp'], 'close': 15.0})

opts['timestamp'] = pd.to_datetime(opts['timestamp']).dt.tz_localize(None)
spot['timestamp'] = pd.to_datetime(spot['timestamp']).dt.tz_localize(None)
vix['timestamp'] = pd.to_datetime(vix['timestamp']).dt.tz_localize(None)

print("Engineering Features (from Phase 2 & 3)...")
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

print("Labelling Winners/Losers...")
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

# Split Data (70% Train+Val for Optuna, 30% for Final Out-of-Sample)
split_idx = int(len(X) * 0.70)
X_study = X[:split_idx]
y_study = y[:split_idx]
X_oos = X[split_idx:]
y_oos = y[split_idx:]

# Scaler is fitted on X_study only
scaler = RobustScaler()
X_study_sc = scaler.fit_transform(X_study)
X_oos_sc = scaler.transform(X_oos)

cw = compute_class_weight('balanced', classes=np.array([0,1]), y=y_study)
spw = cw[1]/cw[0]

print(f"Total Candidates: {len(X)}")
print(f"Study Set: {len(X_study)} | Out-of-Sample Set: {len(X_oos)}")
print(f"Base Win Rate: {y.mean()*100:.2f}%")
print("Starting 1-Minute Optuna Study...")

best_study_pnl = -999999

def objective(trial):
    params = {
        'n_estimators': trial.suggest_int('n_estimators', 500, 3000, step=500),
        'learning_rate': trial.suggest_float('learning_rate', 0.001, 0.1, log=True),
        'max_depth': trial.suggest_int('max_depth', 3, 10),
        'subsample': trial.suggest_float('subsample', 0.5, 1.0),
        'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 1.0),
        'min_child_weight': trial.suggest_int('min_child_weight', 1, 20),
        'reg_alpha': trial.suggest_float('reg_alpha', 1e-3, 10.0, log=True),
        'reg_lambda': trial.suggest_float('reg_lambda', 1e-3, 10.0, log=True),
    }

    # 5-Fold Walk Forward Cross Validation (Time Series)
    n_splits = 5
    fold_size = len(X_study_sc) // (n_splits + 1)
    
    auc_scores = []
    pnl_scores = []
    
    for fold in range(n_splits):
        train_end = (fold + 1) * fold_size
        test_end = train_end + fold_size
        
        X_tr, y_tr = X_study_sc[:train_end], y_study[:train_end]
        X_te, y_te = X_study_sc[train_end:test_end], y_study[train_end:test_end]
        
        model = XGBClassifier(
            **params,
            scale_pos_weight=spw,
            tree_method='hist',
            random_state=42,
            early_stopping_rounds=30,
            eval_metric='auc',
            verbosity=0
        )
        
        # We hold out 10% of train for early stopping to prevent overfit inside the fold
        es_split = int(len(X_tr) * 0.9)
        model.fit(X_tr[:es_split], y_tr[:es_split], eval_set=[(X_tr[es_split:], y_tr[es_split:])], verbose=False)
        
        y_proba = model.predict_proba(X_te)[:,1]
        
        try:
            auc = roc_auc_score(y_te, y_proba)
        except ValueError:
            auc = 0.5
            
        auc_scores.append(auc)
        
        # PnL Simulation @ Threshold 0.60
        conf_mask = y_proba >= 0.60
        fold_preds = y_te[conf_mask]
        signals = len(fold_preds)
        
        if signals > 0:
            fold_pnl = (fold_preds * TARGET_PTS + (1-fold_preds) * (-STOP_PTS)).sum() * QTY
        else:
            fold_pnl = 0
            
        pnl_scores.append(fold_pnl)
    
    mean_auc = np.mean(auc_scores)
    total_pnl = np.sum(pnl_scores)
    
    global best_study_pnl
    if total_pnl > best_study_pnl:
        best_study_pnl = total_pnl
        # Retrain on full study set and save checkpoint
        final_model = XGBClassifier(**params, scale_pos_weight=spw, tree_method='hist', random_state=42)
        final_model.fit(X_study_sc, y_study)
        final_model.save_model('optuna_best_xgb.json')
        joblib.dump(scaler, 'optuna_scaler.pkl')
    
    # We optimize for AUC + PnL Penalty (Focal-like objective)
    # If PnL is negative, we heavily penalize the score
    score = mean_auc + (total_pnl / 100000.0) # Scaled PnL bonus
    return score

# Study for 1 minute (60 seconds)
study = optuna.create_study(direction='maximize', pruner=optuna.pruners.MedianPruner())
study.optimize(objective, timeout=60, show_progress_bar=True)

print("\n" + "="*50)
print("OPTUNA STUDY COMPLETE")
print("="*50)
print(f"Best Trial Score: {study.best_value}")
print("Best Params:", study.best_params)

print("\nLoading Best Model Checkpoint for True Out-of-Sample Test...")
best_model = xgb.Booster()
best_model.load_model('optuna_best_xgb.json')

print("Predicting on 30% Unseen OOS Data...")
dmatrix_oos = xgb.DMatrix(X_oos_sc)
y_proba_oos = best_model.predict(dmatrix_oos)

# Test Thresholds
for thresh in [0.55, 0.60, 0.65]:
    mask = y_proba_oos >= thresh
    preds = y_oos[mask]
    signals = len(preds)
    if signals > 0:
        wr = preds.mean() * 100
        pnl = (preds * TARGET_PTS + (1-preds) * (-STOP_PTS)).sum() * QTY
        print(f"Thresh {thresh:.2f} | Signals: {signals:>4} | WinRate: {wr:.1f}% | OOS PnL: Rs {pnl:,.0f}")
    else:
        print(f"Thresh {thresh:.2f} | Signals: 0")

print("\nTraining Engine offline.")
