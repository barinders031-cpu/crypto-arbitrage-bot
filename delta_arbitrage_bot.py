"""
Delta Exchange India - Live Conversion Arbitrage Bot & Scanner
Enforces:
1. Exact Contract Sizing:
   - 1 Lot ETH = 0.01 ETH (10 Lots = 0.1 ETH, 100 Lots = 1.0 ETH)
   - 1 Lot BTC = 0.001 BTC
2. Fee Benchmark:
   - 1 Lot ETH (0.01 ETH) = $0.015 USD Fee
   - 10 Lots ETH (0.1 ETH) = $0.15 USD Fee
   - 1 Lot BTC (0.001 BTC) = $0.05 USD Fee
3. 50% Profit Retention Rule: Gross Profit per Lot >= 2 * Fee (Net Retention >= 50%)
4. Limit Order Mid-Price Execution
"""

import urllib.request
import json
import pandas as pd
import datetime

BASE_URL = "https://api.india.delta.exchange"

# Contract Sizing Multipliers
ETH_LOT_VALUE = 0.01   # 1 Lot ETH = 0.01 ETH
BTC_LOT_VALUE = 0.001  # 1 Lot BTC = 0.001 BTC

# Empirical Fee Benchmark per 1 Lot (3 Legs)
ETH_FEE_PER_1_LOT = 0.015  # $0.015 USD per 1 Lot (0.01 ETH)
BTC_FEE_PER_1_LOT = 0.05   # $0.05 USD per 1 Lot (0.001 BTC)
MIN_RETENTION_PCT = 50.0   # Must retain >= 50% of gross profit after fees

def fetch_live_delta_data():
    try:
        products_url = f"{BASE_URL}/v2/products"
        req = urllib.request.Request(products_url, headers={'User-Agent': 'Mozilla/5.0'})
        res = urllib.request.urlopen(req, timeout=10)
        products = json.loads(res.read().decode('utf-8')).get('result', [])
        
        tickers_url = f"{BASE_URL}/v2/tickers"
        req = urllib.request.Request(tickers_url, headers={'User-Agent': 'Mozilla/5.0'})
        res = urllib.request.urlopen(req, timeout=10)
        tickers = {t['symbol']: t for t in json.loads(res.read().decode('utf-8')).get('result', [])}
        
        return products, tickers
    except Exception as e:
        print(f"[!] Error fetching Delta Exchange data: {e}")
        return [], {}

def scan_arbitrage_opportunities():
    products, tickers = fetch_live_delta_data()
    if not products or not tickers:
        return []
        
    now = datetime.datetime.now(datetime.timezone.utc)
    valid_setups = []
    
    for asset in ['ETH', 'BTC']:
        fee_per_1_lot = ETH_FEE_PER_1_LOT if asset == 'ETH' else BTC_FEE_PER_1_LOT
        lot_multiplier = ETH_LOT_VALUE if asset == 'ETH' else BTC_LOT_VALUE
        
        fut_symbol = 'ETHUSD' if asset == 'ETH' else 'BTCUSD'
        fut_tick = tickers.get(fut_symbol, tickers.get(f"{asset}USDT", {}))
        
        fut_quotes = fut_tick.get('quotes', {}) or {}
        fut_bid = float(fut_quotes.get('best_bid') or 0)
        fut_ask = float(fut_quotes.get('best_ask') or 0)
        fut_mark = float(fut_tick.get('mark_price') or 0)
        fut_mid = (fut_bid + fut_ask) / 2 if (fut_bid > 0 and fut_ask > 0) else fut_mark
        
        if fut_mid <= 0:
            continue
            
        opts = [p for p in products if (p.get('underlying_asset', {}).get('symbol') if isinstance(p.get('underlying_asset'), dict) else p.get('underlying_asset')) == asset and p.get('contract_type') in ['call_options', 'put_options']]
        df_opts = pd.DataFrame(opts)
        
        if df_opts.empty:
            continue
            
        expiries = sorted(df_opts['settlement_time'].dropna().unique())
        
        for exp in expiries:
            sub_df = df_opts[df_opts['settlement_time'] == exp]
            hours_to_expiry = 24.0
            try:
                settle_dt = datetime.datetime.fromisoformat(exp.replace('Z', '+00:00'))
                hours_to_expiry = max(0.1, (settle_dt - now).total_seconds() / 3600.0)
            except Exception:
                pass
                
            strikes = sorted(sub_df['strike_price'].astype(float).unique())
            strikes = [k for k in strikes if 0.90 * fut_mid <= k <= 1.10 * fut_mid]
            
            for k in strikes:
                c_row = sub_df[(sub_df['strike_price'].astype(float) == k) & (sub_df['contract_type'] == 'call_options')]
                p_row = sub_df[(sub_df['strike_price'].astype(float) == k) & (sub_df['contract_type'] == 'put_options')]
                
                if c_row.empty or p_row.empty:
                    continue
                    
                c, p = c_row.iloc[0], p_row.iloc[0]
                c_t, p_t = tickers.get(c['symbol'], {}), tickers.get(p['symbol'], {})
                
                c_quotes = c_t.get('quotes', {}) or {}
                p_quotes = p_t.get('quotes', {}) or {}
                
                c_bid = float(c_quotes.get('best_bid') or 0)
                c_ask = float(c_quotes.get('best_ask') or 0)
                p_bid = float(p_quotes.get('best_bid') or 0)
                p_ask = float(p_quotes.get('best_ask') or 0)
                
                if c_bid <= 0 or c_ask <= 0 or p_bid <= 0 or p_ask <= 0:
                    continue
                    
                c_mid = (c_bid + c_ask) / 2
                p_mid = (p_bid + p_ask) / 2
                
                implied_short_mid = c_mid - p_mid + k
                gross_profit_per_unit = implied_short_mid - fut_mid
                
                # Sizing base = 1 Lot (0.01 ETH / 0.001 BTC)
                gross_per_1_lot = gross_profit_per_unit * lot_multiplier
                net_per_1_lot = gross_per_1_lot - fee_per_1_lot
                
                # 10 Lots (0.1 ETH / 0.01 BTC)
                gross_per_10_lots = gross_per_1_lot * 10
                fee_per_10_lots = fee_per_1_lot * 10
                net_per_10_lots = net_per_1_lot * 10
                
                if gross_per_1_lot <= 0:
                    continue
                    
                retention_pct = (net_per_1_lot / gross_per_1_lot) * 100.0
                
                # ENFORCE 50% PROFIT RETENTION RULE
                if retention_pct >= MIN_RETENTION_PCT and gross_per_1_lot >= (2 * fee_per_1_lot):
                    valid_setups.append({
                        'asset': asset,
                        'expiry': exp[:10],
                        'days_left': round(hours_to_expiry / 24.0, 2),
                        'strike': k,
                        'fut_symbol': fut_symbol,
                        'fut_mid': round(fut_mid, 2),
                        'c_symbol': c['symbol'],
                        'c_mid': round(c_mid, 2),
                        'p_symbol': p['symbol'],
                        'p_mid': round(p_mid, 2),
                        'gross_1_lot': round(gross_per_1_lot, 4),
                        'fee_1_lot': round(fee_per_1_lot, 4),
                        'net_1_lot': round(net_per_1_lot, 4),
                        'gross_10_lots': round(gross_per_10_lots, 3),
                        'fee_10_lots': round(fee_per_10_lots, 3),
                        'net_10_lots': round(net_per_10_lots, 3),
                        'retention_pct': round(retention_pct, 1)
                    })
                    
    return valid_setups

def run_bot():
    print("=" * 115)
    print("        DELTA EXCHANGE INDIA - ACCURATE CONTRACT SIZING ARBITRAGE BOT")
    print("        (Sizing: 1 Lot ETH = 0.01 ETH | 10 Lots = 0.1 ETH | 1 Lot BTC = 0.001 BTC)")
    print("=" * 115)
    
    setups = scan_arbitrage_opportunities()
    
    if setups:
        df = pd.DataFrame(setups).sort_values(by='days_left', ascending=True)
        print(f"\n[+] FOUND {len(df)} VALID TRADES PASSING THE >= 50% NET PROFIT RULE:\n")
        print(df[['asset', 'expiry', 'days_left', 'strike', 'fut_mid', 'gross_1_lot', 'fee_1_lot', 'net_1_lot', 'gross_10_lots', 'net_10_lots', 'retention_pct']].head(15).to_string(index=False))
        
        top = df.iloc[0]
        print("\n" + "=" * 115)
        print("[TOP RECOMMENDED TRADE INSTRUCTIONS]")
        print("=" * 115)
        print(f"Asset: {top['asset']} | Expiry: {top['expiry']} ({top['days_left']} Days Left) | Strike: ${top['strike']}")
        print(f"Set Unit in Strategy Builder: 'Lot'")
        print(f"Contract Size: 1 Lot = {0.01 if top['asset']=='ETH' else 0.001} {top['asset']}")
        print(f"Leg 1: BUY {top['fut_symbol']} @ Limit ${top['fut_mid']}")
        print(f"Leg 2: SELL {top['c_symbol']} @ Limit ${top['c_mid']}")
        print(f"Leg 3: BUY {top['p_symbol']} @ Limit ${top['p_mid']}")
        print(f"For 1 Lot ({0.01 if top['asset']=='ETH' else 0.001} {top['asset']}): Gross = ${top['gross_1_lot']} USD | Fee = ${top['fee_1_lot']} USD | Net = ${top['net_1_lot']} USD")
        print(f"For 10 Lots ({0.1 if top['asset']=='ETH' else 0.01} {top['asset']}): Gross = ${top['gross_10_lots']} USD | Fee = ${top['fee_10_lots']} USD | Net = ${top['net_10_lots']} USD")
        print(f"Net Profit Retention: {top['retention_pct']}% (>= 50% RULE PASSED)")
    else:
        print("\n[-] No active trades found right now passing the >= 50% Net Retention Rule.")

if __name__ == '__main__':
    run_bot()
