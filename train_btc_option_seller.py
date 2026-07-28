"""
BTC Daily Expiry Option Seller - XGBoost + Optuna
===================================================
Logic:
  - SELL when option premium is between $180 - $220 (target ~$200)
  - Take Profit : premium drops by $100  => sell price $200, exit at $100  => WIN
  - Stop Loss   : premium rises by $100  => sell price $200, exit at $300  => LOSS
  - Lookahead   : up to 288 candles (full trading day on 5-min data)

Key Fix: Lookahead is done on FULL symbol OHLCV data, not on filtered rows.
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
TAKE_PROFIT_PCT = 0.50   # 50% drop in premium = WIN
STOP_LOSS_PCT   = 0.50   # 50% rise in premium = LOSS
LOOKAHEAD       = 288    # Max 288 candles forward (1 full day on 5-min data)
TRAIN_SUBSET    = 0.10   # Use 10% of data for fast training
CONFIDENCE_THR  = 0.55   # Min model confidence to take a trade
OPTUNA_TIMEOUT  = 60     # Seconds for Optuna search

print("=" * 60)
print("  BTC OPTION SELLER AI — XGBoost + Optuna")
print("=" * 60)

# ─── 1. LOAD SPOT DATA & ENGINEER FEATURES ──────────────────────────────────
print("\n[1/5] Loading Spot Data & Engineering Features...")
spot = pd.read_csv('live_data/DELTA_BTC_spot_60d.csv')
spot['timestamp'] = pd.to_datetime(spot['timestamp']).dt.tz_localize(None)
spot = spot.sort_values('timestamp').reset_index(drop=True)

# EMA 34
spot['EMA_34'] = spot['spot_close'].ewm(span=34, adjust=False).mean()
spot['dist_EMA_34'] = (spot['spot_close'] - spot['EMA_34']) / spot['EMA_34']

# ATR 14
prev_c = spot['spot_close'].shift(1)
tr = pd.concat([
    spot['spot_high'] - spot['spot_low'],
    (spot['spot_high'] - prev_c).abs(),
    (spot['spot_low']  - prev_c).abs()
], axis=1).max(axis=1)
spot['ATR_14'] = tr.rolling(14).mean()
spot['ATR_pct'] = spot['ATR_14'] / spot['spot_close']

# RSI 14
delta = spot['spot_close'].diff()
gain  = delta.clip(lower=0).rolling(14).mean()
loss  = (-delta.clip(upper=0)).rolling(14).mean()
spot['RSI_14'] = 100 - (100 / (1 + gain / loss.replace(0, 1e-9)))

# Candle body direction
spot['body'] = (spot['spot_close'] - spot['spot_open']) / spot['spot_open']

spot = spot.dropna().reset_index(drop=True)
print(f"    Spot rows: {len(spot)}")

# ─── 2. LOAD OPTIONS DATA ────────────────────────────────────────────────────
print("\n[2/5] Loading Synthetic Options Data...")
opts = pd.read_csv('live_data/BSM_Synthetic_BTC_options_60d.csv')
opts['timestamp'] = pd.to_datetime(opts['timestamp']).dt.tz_localize(None)
opts = opts.sort_values(['symbol', 'timestamp']).reset_index(drop=True)
print(f"    Options rows: {len(opts)} | Symbols: {opts['symbol'].nunique()}")

# ─── 3. LABEL TRADES (KEY FIX) ───────────────────────────────────────────────
print("\n[3/5] Labelling Trades (looking ahead in full symbol data)...")

#  For each symbol, we have the full price series.
#  We find every candle where price is in [SELL_PREM_MIN, SELL_PREM_MAX]
#  and look FORWARD (in the same symbol) to see which hits first: TP or SL.

records = []

for sym, grp in opts.groupby('symbol'):
    grp = grp.sort_values('timestamp').reset_index(drop=True)
    prices = grp['close'].values
    timestamps = grp['timestamp'].values
    strikes = grp['strike'].values
    opt_type = grp['type'].values[0]   # CE or PE
    n = len(prices)

    for i in range(n):
        sell_price = prices[i]
        
        # dynamic target and stop loss (50% profit, 50% risk)
        tp_price = sell_price - (sell_price * TAKE_PROFIT_PCT)
        sl_price = sell_price + (sell_price * STOP_LOSS_PCT)

        label = -1   # undecided
        for j in range(i + 1, min(i + 1 + LOOKAHEAD, n)):
            fp = prices[j]
            if fp <= tp_price:
                label = 1   # WIN — premium decayed enough
                break
            elif fp >= sl_price:
                label = 0   # LOSS — premium spiked
                break

        if label == -1:
            label = 0   # trade expired without hitting TP → treat as no-win

        records.append({
            'timestamp': timestamps[i],
            'symbol':    sym,
            'strike':    strikes[i],
            'opt_type':  opt_type,
            'sell_price': sell_price,
            'tp_price':  tp_price,
            'sl_price':  sl_price,
            'WIN':       label,
        })

df_trades = pd.DataFrame(records)
print(f"    Total sell opportunities: {len(df_trades)}")
print(f"    WIN  : {df_trades['WIN'].sum()} ({df_trades['WIN'].mean()*100:.1f}%)")
print(f"    LOSS : {(df_trades['WIN']==0).sum()} ({(df_trades['WIN']==0).mean()*100:.1f}%)")

if df_trades['WIN'].sum() == 0:
    print("\n  [!] Zero wins found — check your data or reduce TAKE_PROFIT_PT")
    exit(1)

# ─── 4. MERGE SPOT FEATURES ──────────────────────────────────────────────────
print("\n[4/5] Merging Spot Features & Preparing Training Data...")
df = df_trades.merge(
    spot[['timestamp', 'dist_EMA_34', 'ATR_pct', 'RSI_14', 'body', 'spot_close']],
    on='timestamp', how='inner'
)
df['moneyness'] = df['spot_close'] / df['strike']

FEATURES = ['sell_price', 'strike', 'dist_EMA_34', 'ATR_pct', 'RSI_14', 'body', 'moneyness']
df = df.dropna(subset=FEATURES + ['WIN']).sort_values('timestamp').reset_index(drop=True)
print(f"    Merged rows: {len(df)}")

# 10% subset for fast training
subset_n = int(len(df) * TRAIN_SUBSET)
df = df.iloc[:subset_n].copy()
print(f"    Training subset (10%): {len(df)} rows")

X = df[FEATURES].values
y = df['WIN'].values

# Chronological split: 70% train / 30% OOS test (no future leakage)
split = int(len(X) * 0.70)
X_tr, y_tr = X[:split], y[:split]
X_oos, y_oos = X[split:], y[split:]

scaler = RobustScaler()
X_tr_sc  = scaler.fit_transform(X_tr)
X_oos_sc = scaler.transform(X_oos)

print(f"    Train : {len(X_tr)} | OOS: {len(X_oos)}")
print(f"    Train WIN%: {y_tr.mean()*100:.1f}% | OOS WIN%: {y_oos.mean()*100:.1f}%")

# ─── 5. OPTUNA + XGBOOST ─────────────────────────────────────────────────────
print(f"\n[5/5] Optuna Hyperparameter Search ({OPTUNA_TIMEOUT}s)...")

best_auc = [0.0]

def objective(trial):
    params = {
        'n_estimators':     trial.suggest_int('n_estimators', 100, 600, step=100),
        'learning_rate':    trial.suggest_float('learning_rate', 0.01, 0.2, log=True),
        'max_depth':        trial.suggest_int('max_depth', 3, 7),
        'subsample':        trial.suggest_float('subsample', 0.6, 1.0),
        'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
        'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
        'gamma':            trial.suggest_float('gamma', 0, 1.0),
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
        
        # Unscaled sell_price as sample weights
        w_f_tr = X_tr[:te_start, 0]

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
        model.fit(X_f_tr, y_f_tr, sample_weight=w_f_tr)
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
        w_tr = X_tr[:, 0]
        final.fit(X_tr_sc, y_tr, sample_weight=w_tr)
        final.save_model('btc_seller_xgb.json')
        joblib.dump(scaler, 'btc_seller_scaler.pkl')
        joblib.dump(FEATURES, 'btc_seller_features.pkl')

    return mean_auc

study = optuna.create_study(direction='maximize')
study.optimize(objective, timeout=OPTUNA_TIMEOUT)

# ─── RESULTS ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  TRAINING COMPLETE")
print("=" * 60)
print(f"  Best CV AUC : {best_auc[0]:.4f}")
print(f"  Best Params : {study.best_params}")

import xgboost as xgb
best_model = xgb.Booster()
best_model.load_model('btc_seller_xgb.json')
dm_oos = xgb.DMatrix(X_oos_sc)
proba_oos = best_model.predict(dm_oos)

print("\n  OOS Results (unseen data):")
print(f"  {'Threshold':>9} | {'Signals':>7} | {'WinRate':>7} | {'PnL ($)':>10}")
print("  " + "-" * 44)
for thr in [0.50, 0.55, 0.60, 0.65, 0.70]:
    mask    = proba_oos >= thr
    preds   = y_oos[mask]
    signals = int(mask.sum())
    if signals > 0:
        wr  = preds.mean() * 100
        
        # Fixed Dollar Risk PnL Calculation
        actual_sell_prices = X_oos[mask, 0]
        fixed_risk_usd = 100.0
        
        # With 1:1 dynamic risk (50% TP, 50% SL), win = +100, loss = -100
        pnl = (preds * fixed_risk_usd + (1 - preds) * (-fixed_risk_usd)).sum()
        
        print(f"  {thr:>9.2f} | {signals:>7} | {wr:>6.1f}% | {pnl:>+10.0f} USDT")
    else:
        print(f"  {thr:>9.2f} | {signals:>7} | {'--':>7} | {'--':>10}")

print("\n  Saved:")
print("    btc_seller_xgb.json")
print("    btc_seller_scaler.pkl")
print("    btc_seller_features.pkl")
print("=" * 60)
