"""
BTC/USDT Pure Spot Directional Trading - XGBoost + Optuna
===========================================================
- Capital/Margin: $100
- Leverage: 50x
- Effective Position Size: $5000
- TP: +0.4% | SL: -0.4%
- Strategy: Predict LONG breakouts/direction based on Spot indicators.
"""

import numpy as np
import pandas as pd
import joblib
import warnings
import optuna
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ─── STRATEGY PARAMS ────────────────────────────────────────────────────────
MARGIN_USD = 100.0
LEVERAGE = 50
POSITION_SIZE_USD = MARGIN_USD * LEVERAGE  # $5000

TAKE_PROFIT_PCT = 0.004   # 0.4%
STOP_LOSS_PCT   = 0.004   # 0.4%
LOOKAHEAD       = 288     # Max 288 candles forward (24 hours on 5-min data)
OPTUNA_TIMEOUT  = 60      # Seconds for Optuna search

print("=" * 60)
print("  BTC SPOT DIRECTIONAL LEVERAGE AI — XGBoost + Optuna")
print("=" * 60)

print("\n[1/4] Loading Spot Data & Engineering Features...")
df = pd.read_csv('live_data/DELTA_BTC_spot_60d.csv')
df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None)
df = df.sort_values('timestamp').reset_index(drop=True)

# EMAs
df['EMA_34'] = df['spot_close'].ewm(span=34, adjust=False).mean()
df['EMA_50'] = df['spot_close'].ewm(span=50, adjust=False).mean()
df['dist_EMA_34'] = (df['spot_close'] - df['EMA_34']) / df['EMA_34']
df['dist_EMA_50'] = (df['spot_close'] - df['EMA_50']) / df['EMA_50']

# ATR 14
prev_c = df['spot_close'].shift(1)
tr = pd.concat([
    df['spot_high'] - df['spot_low'],
    (df['spot_high'] - prev_c).abs(),
    (df['spot_low']  - prev_c).abs()
], axis=1).max(axis=1)
df['ATR_14'] = tr.rolling(14).mean()
df['ATR_pct'] = df['ATR_14'] / df['spot_close']

# RSI 14
delta = df['spot_close'].diff()
gain  = delta.clip(lower=0).rolling(14).mean()
loss  = (-delta.clip(upper=0)).rolling(14).mean()
df['RSI_14'] = 100 - (100 / (1 + gain / loss.replace(0, 1e-9)))

# Bollinger Bands (20, 2)
df['BB_mid'] = df['spot_close'].rolling(20).mean()
df['BB_std'] = df['spot_close'].rolling(20).std()
df['BB_up'] = df['BB_mid'] + 2 * df['BB_std']
df['BB_low'] = df['BB_mid'] - 2 * df['BB_std']
df['BB_bandwidth'] = (df['BB_up'] - df['BB_low']) / df['BB_mid']
df['BB_pct_b'] = (df['spot_close'] - df['BB_low']) / (df['BB_up'] - df['BB_low'] + 1e-9)

df = df.dropna().reset_index(drop=True)
print(f"    Spot rows after indicators: {len(df)}")

print("\n[2/4] Labelling Trades (Simulating LONG positions)...")
closes = df['spot_close'].values
highs = df['spot_high'].values
lows = df['spot_low'].values
n = len(closes)
wins = np.zeros(n, dtype=int)

# Loop to find which hits first: +0.4% or -0.4%
for i in range(n):
    entry_price = closes[i]
    tp_price = entry_price * (1 + TAKE_PROFIT_PCT)
    sl_price = entry_price * (1 - STOP_LOSS_PCT)
    
    win = 0
    for j in range(i + 1, min(i + 1 + LOOKAHEAD, n)):
        fh = highs[j]
        fl = lows[j]
        # Conservative check: If low drops below SL in the same candle, we consider it a loss first.
        if fl <= sl_price:
            win = 0
            break
        elif fh >= tp_price:
            win = 1
            break
    wins[i] = win

df['WIN'] = wins
print(f"    Total setups: {n}")
print(f"    WIN  : {df['WIN'].sum()} ({df['WIN'].mean()*100:.1f}%)")
print(f"    LOSS : {n - df['WIN'].sum()} ({(1 - df['WIN'].mean())*100:.1f}%)")

FEATURES = ['dist_EMA_34', 'dist_EMA_50', 'ATR_pct', 'RSI_14', 'BB_bandwidth', 'BB_pct_b']
print("\n[3/4] Preparing Training Data...")
X = df[FEATURES].values
y = df['WIN'].values

# Split chronologically
split = int(len(X) * 0.70)
X_tr, y_tr = X[:split], y[:split]
X_oos, y_oos = X[split:], y[split:]

scaler = RobustScaler()
X_tr_sc  = scaler.fit_transform(X_tr)
X_oos_sc = scaler.transform(X_oos)

print(f"    Train : {len(X_tr)} | OOS: {len(X_oos)}")

print(f"\n[4/4] Optuna Hyperparameter Search ({OPTUNA_TIMEOUT}s)...")
best_auc = [0.0]

def objective(trial):
    params = {
        'n_estimators':     trial.suggest_int('n_estimators', 100, 500, step=100),
        'learning_rate':    trial.suggest_float('learning_rate', 0.01, 0.2, log=True),
        'max_depth':        trial.suggest_int('max_depth', 3, 7),
    }

    n_splits  = 3
    fold_size = len(X_tr_sc) // (n_splits + 1)
    aucs = []

    for fold in range(n_splits):
        te_start = (fold + 1) * fold_size
        te_end   = te_start + fold_size

        X_f_tr = X_tr_sc[:te_start]
        y_f_tr = y_tr[:te_start]
        X_f_te = X_tr_sc[te_start:te_end]
        y_f_te = y_tr[te_start:te_end]

        spw = max(1, len(y_f_tr[y_f_tr == 0])) / max(1, len(y_f_tr[y_f_tr == 1]))

        model = XGBClassifier(
            **params,
            scale_pos_weight=spw,
            random_state=42,
            n_jobs=-1,
            verbosity=0,
            use_label_encoder=False,
            eval_metric='logloss',
        )
        model.fit(X_f_tr, y_f_tr)
        proba = model.predict_proba(X_f_te)[:, 1]

        try:
            auc = roc_auc_score(y_f_te, proba)
        except Exception:
            return 0.5
        aucs.append(auc)

    mean_auc = np.mean(aucs)

    if mean_auc > best_auc[0]:
        best_auc[0] = mean_auc
        spw = max(1, len(y_tr[y_tr == 0])) / max(1, len(y_tr[y_tr == 1]))
        final = XGBClassifier(
            **params,
            scale_pos_weight=spw,
            random_state=42,
            n_jobs=-1,
            verbosity=0,
            use_label_encoder=False,
            eval_metric='logloss',
        )
        final.fit(X_tr_sc, y_tr)
        final.save_model('btc_spot_xgb.json')
        joblib.dump(scaler, 'btc_spot_scaler.pkl')

    return mean_auc

study = optuna.create_study(direction='maximize')
study.optimize(objective, timeout=OPTUNA_TIMEOUT)

print("\n" + "=" * 60)
print("  TRAINING COMPLETE")
print("=" * 60)
print(f"  Best CV AUC : {best_auc[0]:.4f}")
print(f"  Best Params : {study.best_params}")

import xgboost as xgb
best_model = xgb.Booster()
best_model.load_model('btc_spot_xgb.json')
dm_oos = xgb.DMatrix(X_oos_sc)
proba_oos = best_model.predict(dm_oos)

# Evaluate Dollar PnL
WIN_USD = POSITION_SIZE_USD * TAKE_PROFIT_PCT  # $20
LOSS_USD = POSITION_SIZE_USD * STOP_LOSS_PCT   # $20

print("\n  OOS Results (unseen data) on $5000 Position ($100 margin x 50):")
print(f"  {'Threshold':>9} | {'Signals':>7} | {'WinRate':>7} | {'PnL ($)':>10}")
print("  " + "-" * 44)
for thr in [0.50, 0.55, 0.60, 0.65, 0.70]:
    mask    = proba_oos >= thr
    preds   = y_oos[mask]
    signals = int(mask.sum())
    if signals > 0:
        wr  = preds.mean() * 100
        pnl = (preds * WIN_USD + (1 - preds) * (-LOSS_USD)).sum()
        print(f"  {thr:>9.2f} | {signals:>7} | {wr:>6.1f}% | {pnl:>+10.0f} USD")
    else:
        print(f"  {thr:>9.2f} | {signals:>7} | {'--':>7} | {'--':>10}")

print("\nSaved Models: btc_spot_xgb.json & btc_spot_scaler.pkl")
