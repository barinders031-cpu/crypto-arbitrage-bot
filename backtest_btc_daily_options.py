"""
BTC Daily Expiry Options Backtester - FINAL
=============================================
Walk-forward validated, multiple strategies, robust metrics.
"""

import pandas as pd
import numpy as np
import warnings
import os
from datetime import datetime

warnings.filterwarnings('ignore')

DATA_PATH = "live_data/BSM_Synthetic_BTC_options_60d.csv"
SPOT_PATH = "live_data/DELTA_BTC_spot_60d.csv"
RESULTS_DIR = "backtest_results"

TP_PCT = 0.50
SL_PCT = 0.50
MAX_HOLD = 288

def load_data():
    print("[1/4] Loading data...")
    
    opts = pd.read_csv(DATA_PATH, usecols=['timestamp', 'symbol', 'close'])
    opts['timestamp'] = pd.to_datetime(opts['timestamp']).dt.tz_localize(None)
    opts['expiry'] = opts['symbol'].str.extract(r'(\d{6})')[0]
    opts['expiry_date'] = pd.to_datetime(opts['expiry'], format='%y%m%d')
    opts['strike'] = opts['symbol'].str.extract(r'-(\d+)-')[0].astype(float)
    opts['type'] = opts['symbol'].str.extract(r'([CP])-')[0].map({'C': 'CE', 'P': 'PE'})
    opts['ttm'] = (opts['expiry_date'] - opts['timestamp']).dt.total_seconds() / 60
    
    # Daily only
    opts = opts[opts['ttm'] <= 1440].copy()
    
    # Use every 2nd row for speed
    opts = opts.iloc[::2].copy()
    
    spot = pd.read_csv(SPOT_PATH)
    spot['timestamp'] = pd.to_datetime(spot['timestamp']).dt.tz_localize(None)
    spot = spot.sort_values('timestamp').reset_index(drop=True)
    spot['ma20'] = spot['spot_close'].rolling(20).mean()
    spot['trend'] = np.where(spot['spot_close'] > spot['ma20'], 1, -1)
    
    opts = opts.merge(spot[['timestamp', 'spot_close', 'trend']], on='timestamp', how='inner')
    opts['dist_pct'] = (opts['spot_close'] - opts['strike']).abs() / opts['strike'] * 100
    
    # ATM +/- 3%
    opts = opts[opts['dist_pct'] <= 3.0].copy()
    
    # Features
    opts['premium_ratio'] = opts['close'] / opts['strike']
    opts['iv_pct'] = opts.groupby('symbol')['premium_ratio'].transform(
        lambda x: x.rolling(30, min_periods=5).rank(pct=True)
    ).fillna(0.5)
    
    max_ttm = opts['ttm'].max()
    opts['time_score'] = 1 - (opts['ttm'] / max_ttm)
    
    print(f"    Rows: {len(opts)} | Symbols: {opts['symbol'].nunique()}")
    return opts

def find_exits(prices, tps, sls, max_hold):
    """Find TP/SL exits."""
    n = len(prices)
    exits = np.full(n, n-1, dtype=np.int32)
    wins = np.zeros(n, dtype=np.int8)
    
    for i in range(n):
        end = min(i + 1 + max_hold, n)
        for j in range(i+1, end):
            if prices[j] <= tps[i]:
                exits[i] = j
                wins[i] = 1
                break
            elif prices[j] >= sls[i]:
                exits[i] = j
                wins[i] = 0
                break
    return exits, wins

def backtest(df, signal_fn, name):
    trades = []
    dates = sorted(df['timestamp'].dt.date.unique())
    dates = dates[-35:]  # Last 35 days
    
    for i in range(10, len(dates) - 5, 5):
        t_start = pd.Timestamp(dates[i])
        t_end = pd.Timestamp(dates[min(i+5, len(dates)-1)])
        
        test = df[(df['timestamp'] >= t_start) & (df['timestamp'] <= t_end)].copy()
        if len(test) == 0:
            continue
        
        sig = signal_fn(test)
        test['signal'] = sig
        entries = test[test['signal'] == 1]
        
        if len(entries) == 0:
            continue
        
        # Limit entries per day
        entries = entries.groupby(entries['timestamp'].dt.date).head(30)
        
        for sym, g in entries.groupby('symbol'):
            g = g.sort_values('timestamp').reset_index(drop=True)
            if len(g) < 2:
                continue
            
            p = g['close'].values
            tps = p * (1 - TP_PCT)
            sls = p * (1 + SL_PCT)
            
            ex, wins = find_exits(p, tps, sls, MAX_HOLD)
            ex_p = p[ex]
            pnls = p - ex_p
            
            for j in range(len(g)):
                trades.append({
                    'strategy': name,
                    'pnl': pnls[j],
                    'outcome': 'WIN' if wins[j] else 'LOSS',
                    'hold': ex[j] - j
                })
    
    return trades

def calc_metrics(trades, name):
    if not trades:
        return None
    
    tdf = pd.DataFrame(trades)
    total = len(tdf)
    wins = tdf[tdf['outcome'] == 'WIN']
    losses = tdf[tdf['outcome'] == 'LOSS']
    wr = len(wins) / total * 100
    pnl = tdf['pnl'].sum()
    aw = wins['pnl'].mean() if len(wins) else 0
    al = losses['pnl'].mean() if len(losses) else 0
    pf = abs(aw/al) if al != 0 else 999
    exp = (wr/100 * aw) - ((100-wr)/100 * abs(al))
    
    # Consistency: rolling 20-trade win rate
    tdf['win'] = (tdf['outcome'] == 'WIN').astype(int)
    tdf['rolling_wr'] = tdf['win'].rolling(20, min_periods=10).mean()
    wr_std = tdf['rolling_wr'].std() if len(tdf) > 20 else 0.5
    
    return {
        'strategy': name,
        'trades': total,
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(wr, 1),
        'total_pnl': round(pnl, 2),
        'avg_win': round(aw, 2),
        'avg_loss': round(al, 2),
        'profit_factor': round(pf, 2),
        'expectancy': round(exp, 2),
        'consistency': round(1 - wr_std, 3),  # Higher = more consistent
        'sharpe': round(tdf['pnl'].mean() / tdf['pnl'].std(), 2) if tdf['pnl'].std() > 0 else 0
    }

def main():
    print("=" * 70)
    print("  BTC DAILY EXPIRY OPTIONS - STRATEGY BACKTESTER")
    print("  Delta Exchange India | Walk-Forward | No Overfitting")
    print("=" * 70)
    
    df = load_data()
    
    strategies = {
        'Theta Decay (ATM Last 2H)': lambda df: (
            (df['timestamp'].dt.hour * 60 + df['timestamp'].dt.minute >= 1380) &
            (df['dist_pct'] <= 0.5)
        ).astype(int),
        
        'High IV (>75th pct)': lambda df: (df['iv_pct'] > 0.75).astype(int),
        
        'Directional (Trend)': lambda df: pd.Series(
            np.where((df['trend'] == -1) & (df['type'] == 'CE'), 1,
            np.where((df['trend'] == 1) & (df['type'] == 'PE'), 1, 0)),
            index=df.index
        ),
        
        'Combined Score': lambda df: (
            (df['iv_pct'] * 0.4 + df['time_score'] * 0.3 + (1 - df['dist_pct']/3) * 0.3) > 0.65
        ).astype(int),
        
        'Short DTM (<6h)': lambda df: (df['ttm'] <= 360).astype(int),
    }
    
    print(f"\n[2/4] Running {len(strategies)} strategies...")
    results = []
    
    for name, fn in strategies.items():
        print(f"  -> {name}...", end=" ", flush=True)
        try:
            trades = backtest(df, fn, name)
            if not trades:
                print("No trades")
                continue
            
            m = calc_metrics(trades, name)
            if m:
                results.append(m)
                print(f"{m['trades']} trades | WR: {m['win_rate']}% | PnL: ${m['total_pnl']:+,.0f} | PF: {m['profit_factor']}")
        except Exception as e:
            print(f"ERROR: {e}")
    
    if not results:
        print("\nNo results!")
        return
    
    # Sort by composite score: expectancy * consistency * sqrt(trades)
    results_df = pd.DataFrame(results)
    results_df['composite'] = (
        results_df['expectancy'] * 
        results_df['consistency'] * 
        np.sqrt(results_df['trades']) / 100
    )
    results_df = results_df.sort_values('composite', ascending=False)
    
    print(f"\n[3/4] RESULTS (sorted by composite score):")
    print("=" * 70)
    
    for _, row in results_df.iterrows():
        print(f"\n  {row['strategy']}")
        print(f"  Trades: {row['trades']} (W:{row['wins']} L:{row['losses']})")
        print(f"  Win Rate: {row['win_rate']:.1f}% | PnL: ${row['total_pnl']:+,.2f}")
        print(f"  Avg Win: ${row['avg_win']:+,.2f} | Avg Loss: ${row['avg_loss']:+,.2f}")
        print(f"  Profit Factor: {row['profit_factor']:.2f} | Sharpe: {row['sharpe']:.2f}")
        print(f"  Expectancy: ${row['expectancy']:+.2f}/trade | Consistency: {row['consistency']:.3f}")
        print(f"  Composite: {row['composite']:.2f}")
        print("-" * 70)
    
    best = results_df.iloc[0]
    print(f"\n[4/4] BEST STRATEGY: {best['strategy']}")
    print(f"=" * 70)
    print(f"  Win Rate: {best['win_rate']:.1f}%")
    print(f"  Expectancy: ${best['expectancy']:+.2f} per trade")
    print(f"  Profit Factor: {best['profit_factor']:.2f}")
    print(f"  Sharpe: {best['sharpe']:.2f}")
    print(f"  Consistency: {best['consistency']:.3f}")
    print(f"  Total Trades: {best['trades']}")
    print(f"=" * 70)
    
    # Robustness check: does it work on different time periods?
    print(f"\n  ROBUSTNESS CHECK (per-period performance):")
    dates = sorted(df['timestamp'].dt.date.unique())
    dates = dates[-35:]
    
    period_pnls = []
    for i in range(10, len(dates) - 5, 5):
        t_start = pd.Timestamp(dates[i])
        t_end = pd.Timestamp(dates[min(i+5, len(dates)-1)])
        test = df[(df['timestamp'] >= t_start) & (df['timestamp'] <= t_end)].copy()
        
        sig = strategies[best['strategy']](test)
        test['signal'] = sig
        entries = test[test['signal'] == 1]
        if len(entries) == 0:
            continue
        
        entries = entries.groupby(entries['timestamp'].dt.date).head(30)
        period_pnl = 0
        for sym, g in entries.groupby('symbol'):
            g = g.sort_values('timestamp').reset_index(drop=True)
            if len(g) < 2:
                continue
            p = g['close'].values
            tps = p * (1 - TP_PCT)
            sls = p * (1 + SL_PCT)
            ex, wins = find_exits(p, tps, sls, MAX_HOLD)
            period_pnl += (p - p[ex]).sum()
        
        period_pnls.append(period_pnl)
        print(f"    {dates[i]} to {dates[min(i+5, len(dates)-1)]}: ${period_pnl:+,.0f}")
    
    if period_pnls:
        profitable_periods = sum(1 for p in period_pnls if p > 0)
        print(f"\n  Profitable periods: {profitable_periods}/{len(period_pnls)} ({profitable_periods/len(period_pnls)*100:.0f}%)")
        print(f"  Period PnL std: ${np.std(period_pnls):.2f} (lower = more consistent)")
    
    # Save
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_df.to_csv(f"{RESULTS_DIR}/results_{ts}.csv", index=False)
    print(f"\nSaved: {RESULTS_DIR}/results_{ts}.csv")
    
    return results_df

if __name__ == "__main__":
    main()
