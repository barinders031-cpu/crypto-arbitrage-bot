"""
Multi-Exchange High Funding Rate Scanner (Binance & Delta Exchange India)
Scans live 8-hour funding rates across all perpetual futures contracts.
Identifies high funding yield coins for Instant Funding Sniping & Cash-and-Carry Arbitrage.
"""

import urllib.request
import json
import pandas as pd
import datetime

DELTA_URL = "https://api.india.delta.exchange/v2/tickers"
BINANCE_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"

def fetch_delta_high_funding():
    try:
        req = urllib.request.Request(DELTA_URL, headers={'User-Agent': 'Mozilla/5.0'})
        res = urllib.request.urlopen(req, timeout=10)
        tickers = json.loads(res.read().decode('utf-8')).get('result', [])
        
        delta_list = []
        for t in tickers:
            if 'perpetual' in t.get('contract_type', ''):
                symbol = t.get('symbol', '')
                funding_rate_8h = float(t.get('funding_rate') or 0)
                mark_price = float(t.get('mark_price') or 0)
                volume = float(t.get('volume', 0) or 0)
                
                rate_8h_pct = funding_rate_8h * 100.0
                daily_pct = rate_8h_pct * 3.0
                annual_apy = daily_pct * 365.0
                
                if mark_price > 0 and volume > 10000 and abs(rate_8h_pct) <= 20.0:
                    delta_list.append({
                        'exchange': 'Delta India',
                        'symbol': symbol,
                        'price': mark_price,
                        'funding_8h_pct': round(rate_8h_pct, 4),
                        'daily_pct': round(daily_pct, 4),
                        'annual_apy': round(annual_apy, 2),
                        'action': 'SHORT (Sell)' if funding_rate_8h > 0 else 'LONG (Buy)',
                        'volume_usd': round(volume, 2)
                    })
        return delta_list
    except Exception as e:
        print(f"[!] Error fetching Delta Exchange data: {e}")
        return []

def fetch_binance_high_funding():
    try:
        req = urllib.request.Request(BINANCE_URL, headers={'User-Agent': 'Mozilla/5.0'})
        res = urllib.request.urlopen(req, timeout=10)
        data = json.loads(res.read().decode('utf-8'))
        
        binance_list = []
        now_ms = datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000.0
        
        for item in data:
            symbol = item.get('symbol', '')
            if symbol.endswith('USDT'):
                funding_rate_8h = float(item.get('lastFundingRate') or 0)
                mark_price = float(item.get('markPrice') or 0)
                next_funding_time = float(item.get('nextFundingTime') or 0)
                
                minutes_left = max(0, (next_funding_time - now_ms) / 60000.0) if next_funding_time > 0 else 0
                
                rate_8h_pct = funding_rate_8h * 100.0
                daily_pct = rate_8h_pct * 3.0
                annual_apy = daily_pct * 365.0
                
                if mark_price > 0:
                    binance_list.append({
                        'exchange': 'Binance',
                        'symbol': symbol,
                        'price': mark_price,
                        'funding_8h_pct': round(rate_8h_pct, 4),
                        'daily_pct': round(daily_pct, 4),
                        'annual_apy': round(annual_apy, 2),
                        'action': 'SHORT (Sell)' if funding_rate_8h > 0 else 'LONG (Buy)',
                        'mins_to_cutoff': round(minutes_left, 1)
                    })
        return binance_list
    except Exception as e:
        print(f"[!] Error fetching Binance Futures data: {e}")
        return []

def run_high_funding_scanner():
    print("=" * 115)
    print("      HIGH FUNDING RATE ARBITRAGE SCANNER (BINANCE & DELTA EXCHANGE INDIA)")
    print("=" * 115)
    
    delta_data = fetch_delta_high_funding()
    binance_data = fetch_binance_high_funding()
    
    # 1. DELTA EXCHANGE TOP HIGH FUNDING COINS
    if delta_data:
        df_delta = pd.DataFrame(delta_data)
        df_delta_sorted = df_delta.reindex(df_delta['funding_8h_pct'].abs().sort_values(ascending=False).index)
        print("\n" + "=" * 115)
        print("  [+] TOP HIGH FUNDING RATE COINS ON DELTA EXCHANGE INDIA:")
        print("=" * 115)
        print(df_delta_sorted[['symbol', 'price', 'funding_8h_pct', 'daily_pct', 'annual_apy', 'action', 'volume_usd']].head(15).to_string(index=False))
        
    # 2. BINANCE FUTURES TOP HIGH FUNDING COINS
    if binance_data:
        df_binance = pd.DataFrame(binance_data)
        df_binance_sorted = df_binance.reindex(df_binance['funding_8h_pct'].abs().sort_values(ascending=False).index)
        print("\n" + "=" * 115)
        print("  [+] TOP HIGH FUNDING RATE COINS ON BINANCE FUTURES:")
        print("=" * 115)
        print(df_binance_sorted[['symbol', 'price', 'funding_8h_pct', 'daily_pct', 'annual_apy', 'action', 'mins_to_cutoff']].head(15).to_string(index=False))
        
        # Filter for High Funding (|Funding Rate| >= 0.03%)
        df_extreme = df_binance[df_binance['funding_8h_pct'].abs() >= 0.03]
        if not df_extreme.empty:
            print("\n" + "=" * 115)
            print("  [*] HIGH FUNDING OPPORTUNITIES (|Funding Rate| >= 0.03%):")
            print("=" * 115)
            print(df_extreme.sort_values(by='funding_8h_pct', key=abs, ascending=False)[['exchange', 'symbol', 'price', 'funding_8h_pct', 'daily_pct', 'action', 'mins_to_cutoff']].head(15).to_string(index=False))

if __name__ == '__main__':
    run_high_funding_scanner()
