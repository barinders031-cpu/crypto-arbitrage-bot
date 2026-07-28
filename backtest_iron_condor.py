import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore')

DATA_PATH = "live_data/BSM_Synthetic_BTC_options_60d.csv"
SPOT_PATH = "live_data/DELTA_BTC_spot_60d.csv"

def run_iron_condor_backtest():
    print("Loading data...")
    opts = pd.read_csv(DATA_PATH, usecols=['timestamp', 'symbol', 'close'])
    opts['timestamp'] = pd.to_datetime(opts['timestamp']).dt.tz_localize(None)
    opts['expiry'] = opts['symbol'].str.extract(r'(\d{6})')[0]
    opts['expiry_date'] = pd.to_datetime(opts['expiry'], format='%y%m%d')
    opts['strike'] = opts['symbol'].str.extract(r'-(\d+)-')[0].astype(float)
    opts['type'] = opts['symbol'].str.extract(r'([CP])-')[0].map({'C': 'CE', 'P': 'PE'})
    
    # Expiry time is 12:00 UTC
    opts['expiry_date'] = opts['expiry_date'] + pd.Timedelta(hours=12)
    opts['ttm_mins'] = (opts['expiry_date'] - opts['timestamp']).dt.total_seconds() / 60
    
    spot = pd.read_csv(SPOT_PATH)
    spot['timestamp'] = pd.to_datetime(spot['timestamp']).dt.tz_localize(None)
    spot = spot.sort_values('timestamp').reset_index(drop=True)
    
    trades = []
    unique_expiries = opts['expiry_date'].unique()
    
    for expiry in sorted(unique_expiries):
        df_exp = opts[opts['expiry_date'] == expiry]
        
        # Look for entry approx 24 hours before expiry
        entry_candidates = df_exp[(df_exp['ttm_mins'] <= 1500) & (df_exp['ttm_mins'] >= 1300)]
        if entry_candidates.empty:
            continue
            
        entry_time = entry_candidates['timestamp'].min()
        entry_opts = entry_candidates[entry_candidates['timestamp'] == entry_time]
        
        spot_at_entry_df = spot[spot['timestamp'] <= entry_time]
        if spot_at_entry_df.empty:
            continue
        spot_at_entry = spot_at_entry_df['spot_close'].iloc[-1]
        
        ce_opts = entry_opts[entry_opts['type'] == 'CE']
        pe_opts = entry_opts[entry_opts['type'] == 'PE']
        
        if ce_opts.empty or pe_opts.empty:
            continue
            
        # Select CE strikes (Short >= Spot*1.01)
        # Find all OTM CE strikes (strike > spot)
        valid_ce = ce_opts[ce_opts['strike'] > spot_at_entry].sort_values('strike')
        if len(valid_ce) < 2:
            continue
        
        # Try to find a strike around 1% OTM, else take the highest available (excluding the very highest so we can buy a wing)
        target_short_ce = spot_at_entry * 1.01
        
        possible_short_ces = valid_ce[valid_ce['strike'] >= target_short_ce]
        if not possible_short_ces.empty:
            short_ce = possible_short_ces.iloc[0]
        else:
            # If 1% is not available, take the second highest strike as short leg
            short_ce = valid_ce.iloc[-2]
            
        long_ce = valid_ce[valid_ce['strike'] > short_ce['strike']].iloc[0]
        
        # Select PE strikes (Short <= Spot*0.99)
        valid_pe = pe_opts[pe_opts['strike'] < spot_at_entry].sort_values('strike', ascending=False)
        if len(valid_pe) < 2:
            continue
            
        target_short_pe = spot_at_entry * 0.99
        possible_short_pes = valid_pe[valid_pe['strike'] <= target_short_pe]
        if not possible_short_pes.empty:
            short_pe = possible_short_pes.iloc[0]
        else:
            short_pe = valid_pe.iloc[-2]
            
        long_pe = valid_pe[valid_pe['strike'] < short_pe['strike']].iloc[0]
        
        credit = short_ce['close'] - long_ce['close'] + short_pe['close'] - long_pe['close']
        
        spot_at_expiry_df = spot[spot['timestamp'] <= expiry]
        if spot_at_expiry_df.empty:
            continue
        spot_at_expiry = spot_at_expiry_df['spot_close'].iloc[-1]
        
        payoff_short_ce = -max(0, spot_at_expiry - short_ce['strike'])
        payoff_long_ce = max(0, spot_at_expiry - long_ce['strike'])
        payoff_short_pe = -max(0, short_pe['strike'] - spot_at_expiry)
        payoff_long_pe = max(0, long_pe['strike'] - spot_at_expiry)
        
        total_pnl = credit + payoff_short_ce + payoff_long_ce + payoff_short_pe + payoff_long_pe
        
        trades.append({
            'expiry': expiry,
            'spot_entry': spot_at_entry,
            'spot_expiry': spot_at_expiry,
            'short_ce': short_ce['strike'],
            'short_pe': short_pe['strike'],
            'credit': credit,
            'pnl': total_pnl,
            'win': 1 if total_pnl > 0 else 0
        })

    if not trades:
        print("No valid trades found.")
        return
        
    res = pd.DataFrame(trades)
    
    wins = res['win'].sum()
    total = len(res)
    win_rate = wins / total * 100
    avg_pnl = res['pnl'].mean()
    total_pnl = res['pnl'].sum()
    aw = res[res['pnl'] > 0]['pnl'].mean() if len(res[res['pnl'] > 0]) > 0 else 0
    al = res[res['pnl'] <= 0]['pnl'].mean() if len(res[res['pnl'] <= 0]) > 0 else 0
    pf = abs(aw / al) if al != 0 else np.inf
    
    print("="*60)
    print(" IRON CONDOR BACKTEST RESULTS (24h to Expiry, ~1% Wings)")
    print("="*60)
    print(f" Total Trades : {total}")
    print(f" Wins         : {wins} ({win_rate:.1f}%)")
    print(f" Losses       : {total - wins}")
    print(f" Total PnL    : ${total_pnl:.2f}")
    print(f" Avg PnL/Trade: ${avg_pnl:.2f}")
    print(f" Avg Win      : ${aw:.2f}")
    print(f" Avg Loss     : ${al:.2f}")
    print(f" Profit Factor: {pf:.2f}")
    print("="*60)
    
    print("\nSample Trades:")
    print(res[['expiry', 'spot_entry', 'short_ce', 'short_pe', 'spot_expiry', 'credit', 'pnl']].tail(10).to_string(index=False))

if __name__ == "__main__":
    run_iron_condor_backtest()
