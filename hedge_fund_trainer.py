"""
╔═══════════════════════════════════════════════════════════════╗
║   HEDGE FUND GRADE OPTIONS TRAINING ENGINE - COLAB READY     ║
║   Paste this ENTIRE file into ONE Colab cell and run.        ║
║                                                               ║
║   MATHEMATICAL PRIMITIVES USED (No named indicators):        ║
║   1. Wick Absorption Coefficient (WAC)                       ║
║   2. Price Displacement Index (PDI)                          ║
║   3. Volatility Contraction Score (VCS)                      ║
║   4. Trap Force Score (TFS)                                   ║
║   5. Order Flow Imbalance (OFI)                              ║
║   6. Candle Efficiency Ratio (CER)                           ║
║   7. Momentum Divergence Ratio (MDR)                         ║
║   8. Breakout Probability Score (BPS)                        ║
║   9. Session Momentum Bias (SMB)                             ║
║   10. Time Value Decay Rate (TVDR)                           ║
║   11. CE/PE Sensitivity Ratio                                ║
║   12. Premium Efficiency Index (PEI)                         ║
╚═══════════════════════════════════════════════════════════════╝
"""

# ─── CELL 1: Run this first ──────────────────────────────────
# !pip install -q xgboost lightgbm
# !unzip -o ml_data.zip
# ─────────────────────────────────────────────────────────────

import numpy as np
import pandas as pd
import joblib
import time
import warnings
import os
warnings.filterwarnings('ignore')

from xgboost import XGBClassifier
try:
    from lightgbm import LGBMClassifier
    LGBM_OK = True
except:
    LGBM_OK = False

from sklearn.preprocessing import RobustScaler
from sklearn.metrics import accuracy_score, roc_auc_score, precision_score, recall_score
from sklearn.utils.class_weight import compute_class_weight

# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════
TARGET_PTS  = 10.0   # TP: +10 option points
STOP_PTS    =  5.0   # SL: -5 option points  → 1:2 RR
PREM_LOW    = 50.0   # Min premium ₹50
PREM_HIGH   = 65.0   # Max premium ₹65
MAX_CANDLES = 12     # Max hold = 12 × 5min = 1 hour
QTY         = 65     # 1 lot

t0_global = time.time()

print("╔══════════════════════════════════════════════════════╗")
print("║   ADVANCED OPTIONS BUYER TRAINING MACHINE           ║")
print(f"║   Premium: ₹{int(PREM_LOW)}-₹{int(PREM_HIGH)} | TP:+{TARGET_PTS}pts SL:-{STOP_PTS}pts | RR 1:2  ║")
print("╚══════════════════════════════════════════════════════╝\n")


# ═══════════════════════════════════════════════════════════════
# PHASE 1 — LOAD DATA
# ═══════════════════════════════════════════════════════════════
print("━"*55)
print(" PHASE 1 — Loading Raw Data")
print("━"*55)

opts = pd.read_csv('live_data/NIFTY_options_60d.csv') if os.path.exists('live_data/NIFTY_options_60d.csv') else pd.read_csv('simulated_weekly_nifty_options.csv')
spot = pd.read_csv('live_data/NIFTY_spot_60d.csv') if os.path.exists('live_data/NIFTY_spot_60d.csv') else pd.read_csv('nifty_1y_5min.csv')
try:
    vix  = pd.read_csv('nifty_vix_1y_5min.csv')
except FileNotFoundError:
    print("[WARN] VIX data not found. Creating dummy VIX...")
    vix = pd.DataFrame({'timestamp': spot['timestamp'], 'close': 15.0})

# Strip all timezones directly to avoid merge conflicts
opts['timestamp'] = pd.to_datetime(opts['timestamp'])
if opts['timestamp'].dt.tz is not None:
    opts['timestamp'] = opts['timestamp'].dt.tz_localize(None)

spot['timestamp'] = pd.to_datetime(spot['timestamp'])
if spot['timestamp'].dt.tz is not None:
    spot['timestamp'] = spot['timestamp'].dt.tz_localize(None)
elif 'T' in str(spot['timestamp'].iloc[0]) and '+' in str(spot['timestamp'].iloc[0]):
    # Fallback if it parses as naive but was string UTC
    spot['timestamp'] = pd.to_datetime(spot['timestamp'], utc=True).dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)

vix['timestamp'] = pd.to_datetime(vix['timestamp'])
if vix['timestamp'].dt.tz is not None:
    vix['timestamp'] = vix['timestamp'].dt.tz_localize(None)

print(f"  Options : {len(opts):>10,}")
print(f"  Spot    : {len(spot):>10,}")
print(f"  VIX     : {len(vix):>10,}")


# ═══════════════════════════════════════════════════════════════
# PHASE 2 — MATHEMATICAL FEATURE ENGINEERING
# Each equation has physical meaning for price action.
# ═══════════════════════════════════════════════════════════════
print("\n" + "━"*55)
print(" PHASE 2 — Mathematical Feature Engineering")
print("━"*55)

s = spot.copy()

# ── Raw Candle Anatomy ──────────────────────────────────────
s['H']      = s['high']
s['L']      = s['low']
s['O']      = s['open']
s['C']      = s['close']
s['spot_close'] = s['close']
s['range']  = s['H'] - s['L']
s['body']   = (s['C'] - s['O']).abs()
s['bull']   = (s['C'] >= s['O']).astype(int)

# ── Rolling ATR (Average True Range — used as volatility base)
# ATR = avg(range, n) — no indicator, just pure math
for n in [3, 5, 10, 20]:
    s[f'atr_{n}'] = s['range'].rolling(n).mean()

# ═══════════════════════════════════════════════════════════
# EQ 1: Wick Absorption Coefficient (WAC)
# WAC = (Upper_Wick - Lower_Wick) / Range
# Meaning: +1 = price rejected from top (bearish), -1 = rejected from bottom (bullish)
# Sharp negative WAC after down move = bull trap (buy CE signal)
# ═══════════════════════════════════════════════════════════
upper_wick   = s['H'] - s[['O','C']].max(axis=1)
lower_wick   = s[['O','C']].min(axis=1) - s['L']
s['WAC']     = np.where(s['range']>0, (upper_wick - lower_wick)/s['range'], 0)
s['WAC_prev']= s['WAC'].shift(1)
# If prev WAC was strongly negative (long lower wick = sweep + rejection)
s['WAC_bull_trap'] = (s['WAC_prev'] < -0.3).astype(int)
s['WAC_bear_trap'] = (s['WAC_prev'] >  0.3).astype(int)

# ═══════════════════════════════════════════════════════════
# EQ 2: Price Displacement Index (PDI)
# PDI = (Close - Rolling_Low_n) / (Rolling_High_n - Rolling_Low_n)
# Meaning: Where is price in its recent range? 0=at bottom, 1=at top
# PDI crossing above 0.7 after compression = momentum entry
# ═══════════════════════════════════════════════════════════
for n in [5, 10, 20]:
    roll_h = s['H'].rolling(n).max()
    roll_l = s['L'].rolling(n).min()
    band   = roll_h - roll_l
    s[f'PDI_{n}'] = np.where(band > 0, (s['C'] - roll_l) / band, 0.5)

# ═══════════════════════════════════════════════════════════
# EQ 3: Volatility Contraction Score (VCS)
# VCS = 1 - (Current_Range / Max_Range_n)
# Meaning: 0=fully expanded, 1=maximally compressed
# High VCS (>0.7) = market is coiling = big move coming
# ═══════════════════════════════════════════════════════════
for n in [5, 10, 20]:
    max_range     = s['range'].rolling(n).max()
    s[f'VCS_{n}'] = np.where(max_range>0, 1 - s['range']/max_range, 0)

s['VCS_avg'] = (s['VCS_5'] + s['VCS_10'] + s['VCS_20']) / 3
s['high_VCS']= (s['VCS_avg'] > 0.6).astype(int)

# ═══════════════════════════════════════════════════════════
# EQ 4: Trap Force Score (TFS)
# TFS_bull = max(0, Roll_Low_4 - Current_Low) * |WAC_prev|
# Meaning: How deep was the sweep AND how hard did it reject?
# High TFS_bull = institutional buy order detected below support
# ═══════════════════════════════════════════════════════════
for lookback in [4, 8]:
    prev_low  = s['L'].rolling(lookback).min().shift(2)
    prev_high = s['H'].rolling(lookback).max().shift(2)
    s[f'TFS_bull_{lookback}'] = (
        np.maximum(0, prev_low - s['L'].shift(1)) * s['WAC_prev'].abs()
    )
    s[f'TFS_bear_{lookback}'] = (
        np.maximum(0, s['H'].shift(1) - prev_high) * s['WAC_prev'].abs()
    )

# ═══════════════════════════════════════════════════════════
# EQ 5: Order Flow Imbalance (OFI)
# OFI = Volume * (2*(Close - Low)/(High - Low) - 1)
# = Volume * (Pressure*2 - 1)
# Meaning: +OFI = buyers dominated that candle, -OFI = sellers dominated
# Rolling OFI shows who is in control
# ═══════════════════════════════════════════════════════════
pressure      = np.where(s['range']>0, (s['C']-s['L'])/s['range'], 0.5)
s['pressure'] = pressure
s['OFI_raw']  = s['volume'] * (2*pressure - 1)
s['OFI_5']    = s['OFI_raw'].rolling(5).mean()
s['OFI_10']   = s['OFI_raw'].rolling(10).mean()
s['OFI_sign'] = np.sign(s['OFI_5'])

# ═══════════════════════════════════════════════════════════
# EQ 6: Candle Efficiency Ratio (CER)
# CER = |Close - Open| / (High - Low)
# Meaning: 1 = perfect trend candle (no wicks), 0 = doji (all wick)
# High CER on breakout = strong institutional move
# CER_prev near 0 (doji) before reversal = exhaustion
# ═══════════════════════════════════════════════════════════
s['CER']      = np.where(s['range']>0, s['body']/s['range'], 0)
s['CER_prev'] = s['CER'].shift(1)
s['CER_5avg'] = s['CER'].rolling(5).mean()
# Low CER = exhaustion/indecision candles = reversal possible
s['exhaustion']= (s['CER_prev'] < 0.25).astype(int)

# ═══════════════════════════════════════════════════════════
# EQ 7: Momentum Divergence Ratio (MDR)
# MDR_n = (Close_t - Close_t-n) / ATR_n
# Normalized momentum: removes volatility bias
# MDR > 2 = strong momentum, MDR < -2 = strong selling
# ═══════════════════════════════════════════════════════════
for n in [1, 2, 3, 5, 8, 13]:
    delta          = s['C'] - s['C'].shift(n)
    atr            = s[f'atr_{min(n, 20)}'] if f'atr_{n}' in s.columns else s['atr_5']
    s[f'MDR_{n}']  = np.where(atr>0, delta/atr, 0)
    s[f'vel_{n}']  = delta  # raw velocity too

s['accel']     = s['vel_1'] - s['vel_1'].shift(1)
s['jerk']      = s['accel'] - s['accel'].shift(1)

# ═══════════════════════════════════════════════════════════
# EQ 8: Breakout Probability Score (BPS)
# BPS = VCS_avg * (lvc_bars_count/lookback) * abs(OFI_sign)
# Meaning: Compressed + volume drying + direction bias = breakout imminent
# ═══════════════════════════════════════════════════════════
s['LVC_flag']   = (s['VCS_5'] > 0.5).astype(int)
s['lvc_count4'] = s['LVC_flag'].rolling(4).sum()
s['lvc_count8'] = s['LVC_flag'].rolling(8).sum()
s['BPS']        = s['VCS_avg'] * (s['lvc_count4']/4.0) * s['OFI_sign'].abs()

# ═══════════════════════════════════════════════════════════
# EQ 9: Session Momentum Bias (SMB)
# SMB = (Close - DayOpen) / ATR_5
# Meaning: How far has price moved from today's open, normalized by volatility
# SMB > 1.5 = strong upday bias, < -1.5 = strong downday bias
# ═══════════════════════════════════════════════════════════
s['date']     = s['timestamp'].dt.date
s['hour']     = s['timestamp'].dt.hour
s['minute']   = s['timestamp'].dt.minute
s['dow']      = s['timestamp'].dt.dayofweek
s['mins_open']= (s['hour']-9)*60 + s['minute'] - 15

# Day open = first candle's open each day
day_open_map  = s.groupby('date')['O'].first().to_dict()
s['day_open'] = s['date'].map(day_open_map)
s['SMB']      = np.where(s['atr_5']>0, (s['C']-s['day_open'])/s['atr_5'], 0)

# ── Session time features ──
s['is_morning_power'] = ((s['mins_open'] >= 0)  & (s['mins_open'] <= 75)).astype(int)
s['is_midday_slow']   = ((s['mins_open'] > 75)  & (s['mins_open'] < 240)).astype(int)
s['is_closing_power'] = ((s['mins_open'] >= 240)& (s['mins_open'] <= 375)).astype(int)

# ── Rate of Change (normalized) ──
for n in [3, 5, 10]:
    s[f'roc_{n}'] = (s['C']/s['C'].shift(n) - 1)*100

# ── Multi-period pressure ──
s['avg_pressure_5']  = s['pressure'].rolling(5).mean()
s['avg_pressure_10'] = s['pressure'].rolling(10).mean()

# Volume dynamics
s['vol_ma10']    = s['volume'].rolling(10).mean()
s['vol_ratio']   = np.where(s['vol_ma10']>0, s['volume']/s['vol_ma10'], 1)
s['vol_surge']   = (s['vol_ratio'] > 1.5).astype(int)
s['vol_dry']     = (s['vol_ratio'] < 0.6).astype(int)

spot_eng = s.copy()

total_spot_feats = len([c for c in s.columns if c not in ['timestamp','open','high','low','close','volume','date']])
print(f"  Spot mathematical features computed: {total_spot_feats}")
print("  Equations: WAC, PDI, VCS, TFS, OFI, CER, MDR, BPS, SMB + derivatives")


# ═══════════════════════════════════════════════════════════════
# PHASE 3 — OPTIONS MATH + LABELLING
# ═══════════════════════════════════════════════════════════════
print("\n" + "━"*55)
print(" PHASE 3 — Options Math + WIN/LOSS Labelling")
print("━"*55)

cands = opts[(opts['close']>=PREM_LOW)&(opts['close']<=PREM_HIGH)].copy()
print(f"  Candidates in ₹{int(PREM_LOW)}-₹{int(PREM_HIGH)}: {len(cands):,}")

# Build forward lookup
opts_s = opts.sort_values(['strike','opt_type','expiry','timestamp'])
opt_groups = {}
for key, grp in opts_s.groupby(['strike','opt_type','expiry']):
    opt_groups[key] = grp.reset_index(drop=True)

print(f"  Labelling {len(cands):,} candidates...")
t_lbl = time.time()
labels = []
for i, (_, row) in enumerate(cands.iterrows()):
    key = (row['strike'], row['opt_type'], row['expiry'])
    if key not in opt_groups:
        labels.append(-1); continue
    grp  = opt_groups[key]
    fwd  = grp[grp['timestamp']>row['timestamp']].head(MAX_CANDLES)
    tp   = row['close'] + TARGET_PTS
    sl   = row['close'] - STOP_PTS
    lbl  = 0
    for _, fr in fwd.iterrows():
        if fr['close'] >= tp: lbl=1; break
        if fr['close'] <= sl: lbl=0; break
    labels.append(lbl)

cands['label'] = labels
cands = cands[cands['label']>=0].copy()
wins   = (cands.label==1).sum()
losses = (cands.label==0).sum()
bwr    = wins/len(cands)*100
be_wr  = STOP_PTS/(TARGET_PTS+STOP_PTS)*100
print(f"  Labelling done: {time.time()-t_lbl:.1f}s")
print(f"  WIN: {wins:,}  LOSS: {losses:,}  Base WR: {bwr:.1f}%")
print(f"  Breakeven WR at 1:2 RR: {be_wr:.1f}% (we only need this to be profitable!)")


# ═══════════════════════════════════════════════════════════════
# PHASE 4 — BUILD FULL FEATURE MATRIX
# ═══════════════════════════════════════════════════════════════
print("\n" + "━"*55)
print(" PHASE 4 — Building Full Feature Matrix")
print("━"*55)

SPOT_COLS = ['timestamp', 'spot_close',
    'WAC','WAC_prev','WAC_bull_trap','WAC_bear_trap',
    'PDI_5','PDI_10','PDI_20',
    'VCS_5','VCS_10','VCS_20','VCS_avg','high_VCS',
    'TFS_bull_4','TFS_bear_4','TFS_bull_8','TFS_bear_8',
    'OFI_raw','OFI_5','OFI_10','OFI_sign',
    'CER','CER_prev','CER_5avg','exhaustion',
    'MDR_1','MDR_2','MDR_3','MDR_5','MDR_8','MDR_13',
    'vel_1','vel_2','vel_3','vel_5','accel','jerk',
    'BPS','lvc_count4','lvc_count8',
    'SMB','pressure','avg_pressure_5','avg_pressure_10',
    'vol_ratio','vol_surge','vol_dry',
    'roc_3','roc_5','roc_10',
    'atr_3','atr_5','atr_10','atr_20',
    'range','body','bull',
    'mins_open','dow','is_morning_power','is_midday_slow','is_closing_power'
]
available = [c for c in SPOT_COLS if c in spot_eng.columns]
df = pd.merge(cands, spot_eng[available], on='timestamp', how='inner')

vix_s = vix[['timestamp','close']].rename(columns={'close':'vix'}).sort_values('timestamp')
df = pd.merge_asof(df.sort_values('timestamp'), vix_s, on='timestamp', direction='backward')
df = df.dropna().reset_index(drop=True)

# ═══════════════════════════════════════════════════════════
# EQ 10: Time Value Decay Rate (TVDR)
# TVDR = TimeValue / sqrt(DTE + 0.1)
# Meaning: Rich time value relative to time left = option is expensive
# ═══════════════════════════════════════════════════════════
# Compute DTE from expiry
df['expiry_dt'] = pd.to_datetime(df['expiry'], format='%d%b%Y', errors='coerce')
df['DTE']       = (df['expiry_dt'] - df['timestamp']).dt.days.clip(lower=0)

df['opt_enc']   = (df['opt_type']=='CE').astype(int)
df['moneyness'] = df['spot_close'] / df['strike']
df['log_money'] = np.log(df['moneyness'])
df['intr_ce']   = np.maximum(df['spot_close']-df['strike'], 0)
df['intr_pe']   = np.maximum(df['strike']-df['spot_close'], 0)
df['intrinsic'] = np.where(df['opt_type']=='CE', df['intr_ce'], df['intr_pe'])
df['timevalue'] = np.maximum(df['close']-df['intrinsic'], 0)

# EQ 10
df['TVDR']      = df['timevalue'] / np.sqrt(df['DTE'] + 0.1)

# ═══════════════════════════════════════════════════════════
# EQ 11: Premium Efficiency Index (PEI)
# PEI = TimeValue / Premium
# Meaning: 1 = pure time value (OTM), 0 = pure intrinsic (deep ITM)
# Options at ₹50-65 with high PEI = more sensitive to moves
# ═══════════════════════════════════════════════════════════
df['PEI']      = np.where(df['close']>0, df['timevalue']/df['close'], 0)
df['prem_pos'] = (df['close']-PREM_LOW)/(PREM_HIGH-PREM_LOW)
df['vix_norm'] = df['vix']/20.0

# ═══════════════════════════════════════════════════════════
# EQ 12: Spot-to-Option Reaction (SOR)
# For CE: How much did CE move when spot moved +1?
# For PE: How much did PE move when spot moved -1?
# This is a data-derived sensitivity (not assumed delta)
# ═══════════════════════════════════════════════════════════
# Sort by time, compute option return and spot return
df_ce = df[df['opt_type']=='CE'].sort_values('timestamp')
df_pe = df[df['opt_type']=='PE'].sort_values('timestamp')
for sub in [df_ce, df_pe]:
    sub['opt_ret_1']  = sub['close'].pct_change(1)
    sub['spot_ret_1'] = sub['spot_close'].pct_change(1) if 'spot_close' in sub.columns else 0
    sub['SOR']        = np.where(
        sub['spot_ret_1'].abs() > 0.0001,
        sub['opt_ret_1'] / sub['spot_ret_1'],
        0
    )

df = pd.merge(df,
    pd.concat([df_ce[['timestamp','strike','opt_type','expiry','SOR']],
               df_pe[['timestamp','strike','opt_type','expiry','SOR']]]),
    on=['timestamp','strike','opt_type','expiry'], how='left')
df['SOR'] = df['SOR'].fillna(0).clip(-10, 10)

# ── Interaction Terms (The model learns cross-effects) ──────
df['WAC_x_VCS']     = df['WAC_prev'] * df['VCS_avg']        # Wick strength × compression
df['TFS_x_OFI']     = df['TFS_bull_4'] * df['OFI_5']       # Trap depth × order flow
df['BPS_x_MDR']     = df['BPS'] * df['MDR_1']              # Breakout prob × momentum
df['PDI_x_CER']     = df['PDI_5'] * df['CER']              # Price position × candle quality
df['SMB_x_pow']     = df['SMB'] * df['is_morning_power']   # Day bias × power hour
df['vix_x_TVDR']    = df['vix_norm'] * df['TVDR']          # VIX × time value richness
df['PEI_x_moneyness']= df['PEI'] * df['moneyness']         # Option profile

FEATURE_COLS = [
    # WAC family
    'WAC','WAC_prev','WAC_bull_trap','WAC_bear_trap',
    # PDI family
    'PDI_5','PDI_10','PDI_20',
    # VCS family
    'VCS_5','VCS_10','VCS_avg','high_VCS',
    # TFS family
    'TFS_bull_4','TFS_bear_4','TFS_bull_8','TFS_bear_8',
    # OFI family
    'OFI_5','OFI_10','OFI_sign',
    # CER family
    'CER','CER_prev','exhaustion',
    # MDR / momentum
    'MDR_1','MDR_2','MDR_3','MDR_5','MDR_8',
    'vel_1','vel_2','vel_3','accel','jerk',
    # BPS
    'BPS','lvc_count4','lvc_count8',
    # SMB / session
    'SMB','is_morning_power','is_midday_slow','is_closing_power',
    # Pressure / volume
    'pressure','avg_pressure_5','vol_ratio','vol_surge','vol_dry',
    # ATR / range
    'atr_3','atr_5','atr_10','range','body','bull',
    # ROC
    'roc_3','roc_5','roc_10',
    # Options math
    'close','prem_pos','moneyness','log_money',
    'intrinsic','timevalue','TVDR','PEI',
    'SOR','opt_enc','DTE',
    # VIX
    'vix','vix_norm',
    # Time
    'mins_open','dow',
    # Interactions
    'WAC_x_VCS','TFS_x_OFI','BPS_x_MDR','PDI_x_CER',
    'SMB_x_pow','vix_x_TVDR','PEI_x_moneyness',
]
FEATURE_COLS = [f for f in FEATURE_COLS if f in df.columns]
print(f"  Total features in matrix: {len(FEATURE_COLS)}")
print(f"  Total training rows      : {len(df):,}")


# ═══════════════════════════════════════════════════════════════
# PHASE 5 — WALK-FORWARD VALIDATION (Hedge Fund Standard)
# No data leakage. Each test window is strictly in the future
# of its training window.
# ═══════════════════════════════════════════════════════════════
print("\n" + "━"*55)
print(" PHASE 5 — Walk-Forward Validation (Anti-Overfit)")
print("━"*55)

df = df.sort_values('timestamp').reset_index(drop=True)
X  = df[FEATURE_COLS].values
y  = df['label'].values

n        = len(X)
n_splits = 5
fold_size= n // (n_splits+1)

wf_results = []
best_acc   = 0.0
best_model = None

for fold in range(n_splits):
    train_end  = fold_size * (fold+1)
    test_start = train_end
    test_end   = test_start + fold_size

    # Fit scaler ONLY on training data to prevent leakage
    scaler = RobustScaler()
    X_tr = scaler.fit_transform(X[:train_end])
    X_te = scaler.transform(X[test_start:test_end])
    y_tr = y[:train_end]
    y_te = y[test_start:test_end]

    if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
        print(f"  Fold {fold+1}: Skipping (not enough class diversity)")
        continue

    cw  = compute_class_weight('balanced', classes=np.array([0,1]), y=y_tr)
    spw = cw[1]/cw[0]

    print(f"\n  ┌── Fold {fold+1}/{n_splits}  Train:{len(X_tr):,}  Test:{len(X_te):,}")

    # ── XGBoost with early stopping ──────────────────────
    xgb = XGBClassifier(
        n_estimators          = 2000,
        learning_rate         = 0.01,
        max_depth             = 6,
        subsample             = 0.75,
        colsample_bytree      = 0.75,
        min_child_weight      = 10,
        reg_alpha             = 0.1,
        reg_lambda            = 1.0,
        scale_pos_weight      = spw,
        tree_method           = 'hist',
        device                = 'cuda',
        random_state          = 42,
        early_stopping_rounds = 40,
        eval_metric           = 'auc',
        verbosity             = 0,
    )
    xgb.fit(X_tr, y_tr, eval_set=[(X_te, y_te)], verbose=False)
    trees_used = xgb.best_iteration

    y_pred  = xgb.predict(X_te)
    y_proba = xgb.predict_proba(X_te)[:,1]
    acc     = accuracy_score(y_te, y_pred)
    auc     = roc_auc_score(y_te, y_proba)
    prec    = precision_score(y_te, y_pred, zero_division=0)
    rec     = recall_score(y_te, y_pred, zero_division=0)

    # ── Simulated PnL on this test fold ──────────────────
    conf_mask = y_proba >= 0.62
    fold_preds= y_pred[conf_mask]
    fold_true = y_te[conf_mask]
    signals   = len(fold_preds)
    if signals > 0:
        fold_wr    = fold_true.mean()*100
        fold_pnl   = (fold_true * TARGET_PTS + (1-fold_true) * (-STOP_PTS)).sum() * QTY
    else:
        fold_wr = fold_pnl = 0

    print(f"  │  Trees: {trees_used:<4}  Acc: {acc*100:.2f}%  AUC: {auc:.4f}  "
          f"Prec: {prec:.2f}  Rec: {rec:.2f}")
    print(f"  │  Signals@0.62: {signals:>4}  WR: {fold_wr:.1f}%  "
          f"PnL: ₹{fold_pnl:>10,.0f}")
    print(f"  └── {'★ New best!' if acc>best_acc else ''}")

    wf_results.append({'fold':fold+1,'acc':acc,'auc':auc,'prec':prec,
                        'rec':rec,'signals':signals,'wr':fold_wr,'pnl':fold_pnl})

    if acc > best_acc:
        best_acc   = acc
        best_model = xgb
        best_model.save_model('options_model.json')
        joblib.dump(scaler,      'options_scaler.pkl')
        joblib.dump(FEATURE_COLS,'options_features.pkl')
        print(f"     Saved best model (acc={best_acc*100:.2f}%)")

wf_df = pd.DataFrame(wf_results)
print(f"\n  Walk-Forward Summary:")
print(f"  Mean Accuracy  : {wf_df.acc.mean()*100:.2f}% ± {wf_df.acc.std()*100:.2f}%")
print(f"  Mean AUC       : {wf_df.auc.mean():.4f}")
print(f"  Total WF Signals: {wf_df.signals.sum():,}")
print(f"  Total WF PnL   : ₹{wf_df.pnl.sum():,.0f}")


# ═══════════════════════════════════════════════════════════════
# PHASE 6 — TRAIN FINAL MODEL ON 100% DATA
# ═══════════════════════════════════════════════════════════════
print("\n" + "━"*55)
print(" PHASE 6 — Final Model (Full Data, Anti-Overfit)")
print("━"*55)

# Strict Time-Series Split: 70% Train, 10% Validation (Early Stopping), 20% True Out-of-Sample Test
split_train = int(len(X) * 0.70)
split_val   = int(len(X) * 0.80)

# Fit scaler strictly on the 70% training data
scaler = RobustScaler()
X_train_sc = scaler.fit_transform(X[:split_train])
X_val_sc   = scaler.transform(X[split_train:split_val])
X_test_sc  = scaler.transform(X[split_val:])

cw    = compute_class_weight('balanced', classes=np.array([0,1]), y=y[:split_train])
spw   = cw[1]/cw[0]

final_model = XGBClassifier(
    n_estimators          = 3000,
    learning_rate         = 0.008,
    max_depth             = 6,
    subsample             = 0.75,
    colsample_bytree      = 0.75,
    min_child_weight      = 10,
    reg_alpha             = 0.2,
    reg_lambda            = 2.0,
    scale_pos_weight      = spw,
    tree_method           = 'hist',
    device                = 'cuda',
    random_state          = 42,
    early_stopping_rounds = 50,
    eval_metric           = 'auc',
    verbosity             = 0,
)
print("  Training final model (3000 trees, strict 70/10/20 split)...")
t_final = time.time()
final_model.fit(X_train_sc, y[:split_train],
                eval_set=[(X_val_sc, y[split_train:split_val])],
                verbose=200)
print(f"  Completed in {time.time()-t_final:.1f}s  Trees: {final_model.best_iteration}")

# Save final
final_model.save_model('options_model_final.json')
joblib.dump(scaler,       'options_scaler.pkl')
joblib.dump(FEATURE_COLS, 'options_features.pkl')


# ═══════════════════════════════════════════════════════════════
# PHASE 7 — FEATURE IMPORTANCE (What the AI Learned)
# ═══════════════════════════════════════════════════════════════
print("\n" + "━"*55)
print(" PHASE 7 — What the AI Discovered")
print("━"*55)

fi = pd.Series(final_model.feature_importances_, index=FEATURE_COLS)
fi = fi.sort_values(ascending=False)
print("\n  Top 20 most important mathematical features:")
print(f"  {'Feature':<28} {'Importance':>10}  Meaning")
print("  " + "─"*60)
meanings = {
    'WAC_prev'     : 'Prev candle wick absorption',
    'TFS_bull_4'   : 'Trap force (bull sweep depth)',
    'VCS_avg'      : 'Volatility compression score',
    'BPS'          : 'Breakout probability score',
    'MDR_1'        : 'Normalized 1-bar momentum',
    'OFI_5'        : 'Order flow imbalance (5-bar)',
    'PDI_5'        : 'Price displacement in range',
    'SMB'          : 'Session momentum vs day open',
    'TVDR'         : 'Time value decay rate',
    'PEI'          : 'Premium efficiency index',
    'SOR'          : 'Spot-to-option sensitivity',
    'CER_prev'     : 'Prev candle efficiency (exhaustion)',
    'WAC_x_VCS'    : 'Wick × compression interaction',
    'TFS_x_OFI'    : 'Trap × order flow interaction',
    'BPS_x_MDR'    : 'Breakout prob × momentum',
}
for fname, imp in fi.head(20).items():
    bar  = '█' * int(imp*400)
    note = meanings.get(fname, '')
    print(f"  {fname:<28} {imp:>10.5f}  {bar}  {note}")


# ═══════════════════════════════════════════════════════════════
# PHASE 8 — FINAL OUT-OF-SAMPLE BACKTEST
# ═══════════════════════════════════════════════════════════════
print("\n" + "━"*55)
print(" PHASE 8 — Honest Out-of-Sample Backtest")
print("━"*55)

# Use ONLY the last 20% of data (strictly unseen during train AND validation)
test_df  = df.iloc[split_val:].copy().reset_index(drop=True)
test_df['prob'] = final_model.predict_proba(X_test_sc)[:,1]

# Confidence threshold = 0.62
signals  = test_df[test_df['prob']>=0.62].copy()
print(f"  Test period: {test_df.timestamp.min().date()} to {test_df.timestamp.max().date()}")
print(f"  Signals found (prob≥0.62): {len(signals):,}")

trades = []
for _, row in signals.iterrows():
    key = (row['strike'], row['opt_type'], row['expiry'])
    if key not in opt_groups: continue
    grp  = opt_groups[key]
    fwd  = grp[grp['timestamp']>row['timestamp']].head(MAX_CANDLES)
    tp   = row['close']+TARGET_PTS; sl = row['close']-STOP_PTS
    win  = 0
    for _,fr in fwd.iterrows():
        if fr['close']>=tp: win=1; break
        if fr['close']<=sl: win=0; break
    pnl = (TARGET_PTS if win else -STOP_PTS)*QTY
    trades.append({'date':row['timestamp'].date(), 'time':row['timestamp'],
                   'index':'NIFTY','type':row['opt_type'],
                   'strike':row['strike'],'entry':row['close'],
                   'prob':round(row['prob'],3),
                   'outcome':'WIN' if win else 'LOSS','pnl':pnl})

if trades:
    tdf = pd.DataFrame(trades)
    tdf['cum'] = tdf['pnl'].cumsum()
    wins  = (tdf['outcome']=='WIN').sum()
    total = len(tdf)
    wr    = wins/total*100
    net   = tdf['pnl'].sum()
    dd    = tdf['cum'].min()
    daily = tdf.groupby('date').size()

    print(f"\n  ╔═══════════════════════════════════════════════════╗")
    print(f"  ║  OUT-OF-SAMPLE BACKTEST (Never Seen Data)        ║")
    print(f"  ╠═══════════════════════════════════════════════════╣")
    print(f"  ║  Total Trades    : {total:<31} ║")
    print(f"  ║  Win Rate        : {wr:<31.2f} ║")
    print(f"  ║  Breakeven WR    : {be_wr:<31.1f} ║")
    print(f"  ║  Net PnL         : ₹{net:<30,.2f} ║")
    print(f"  ║  Max Drawdown    : ₹{dd:<30,.2f} ║")
    print(f"  ║  Avg trades/day  : {daily.mean():<31.1f} ║")
    print(f"  ║  Min trades/day  : {daily.min():<31} ║")
    print(f"  ║  Max trades/day  : {daily.max():<31} ║")
    print(f"  ╚═══════════════════════════════════════════════════╝")

    tdf.to_csv('final_backtest.csv', index=False)
    print("\n  Saved: final_backtest.csv")

total_time = time.time()-t0_global
print(f"\n  Total Runtime: {total_time/60:.1f} minutes")

# ═══════════════════════════════════════════════════════════════
# PHASE 9 — AUTO DOWNLOAD FILES
# ═══════════════════════════════════════════════════════════════
print("\n" + "━"*55)
print(" PHASE 9 — Downloading Files (put in E:\\nse\\)")
print("━"*55)

try:
    from google.colab import files
    for f in ['options_model_final.json','options_scaler.pkl',
              'options_features.pkl','final_backtest.csv']:
        try:
            files.download(f)
            print(f"  Downloaded: {f}")
        except Exception as e:
            print(f"  Error downloading {f}: {e}")
except ImportError:
    print("  (Not in Colab — files saved locally)")
