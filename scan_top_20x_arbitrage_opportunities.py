"""
Top Funding Difference Arbitrage Scanner with $20 Capital 20x Leverage Profit Projections
Exchanges: Delta Exchange India vs CoinDCX (Binance Liquidity)
"""
import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        res = urllib.request.urlopen(req, timeout=10)
        data = json.loads(res.read().decode())
        if isinstance(data, dict) and 'result' in data:
            return data['result']
        return data
    except Exception as e:
        return []

print("[+] Fetching live raw data from Delta Exchange India...")
delta_products = fetch("https://api.india.delta.exchange/v2/products")
delta_tickers = fetch("https://api.india.delta.exchange/v2/tickers")

delta_interval = {}
for p in delta_products:
    sym = p.get('symbol', '')
    specs = p.get('product_specs') or {}
    rei = specs.get('rate_exchange_interval')
    delta_interval[sym] = int(rei) / 3600.0 if rei else 8.0

delta_map = {}
for t in delta_tickers:
    if 'perpetual' in t.get('contract_type', ''):
        sym = t.get('symbol', '')
        rate_pct = float(t.get('funding_rate') or 0)
        coin = sym.replace('USD', '')
        h = delta_interval.get(sym, 8.0)
        delta_map[coin] = {'rate': rate_pct, 'h': h, 'sym': sym}

print("[+] Fetching live raw data from CoinDCX (Binance Liquidity)...")
binance_funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")

coindcx_map = {}
for b in binance_funding:
    sym = b.get('symbol', '')
    if sym.endswith('USDT'):
        coin = sym.replace('USDT', '')
        rate_pct = float(b.get('lastFundingRate') or 0) * 100.0
        coindcx_map[coin] = {'rate': rate_pct, 'h': 8.0, 'sym': sym}

results = []

# Trade Parameters: $10 Margin Delta + $10 Margin CoinDCX @ 20x = $200 Notional each
notional = 200.0  # $200 USD
entry_fee = 0.20  # $0.20 total round-trip entry fee ($0.10 Delta + $0.10 CoinDCX)

for coin, d in delta_map.items():
    if coin in coindcx_map:
        c = coindcx_map[coin]
        d_rate = d['rate']
        c_rate = c['rate']
        
        d_h = d['h']
        c_h = c['h']
        
        # Daily funding income calculations
        # Delta: Short if positive (+), Long if negative (-)
        d_daily_usd = notional * (abs(d_rate) / 100.0) * (24.0 / d_h)
        
        # CoinDCX: Long if positive (+), Short if negative (-)
        c_daily_usd = notional * (c_rate / 100.0) * (24.0 / c_h)
        
        # Net Daily Funding Spread Income
        if d_rate >= 0:
            # Short Delta (+income), Long CoinDCX (-cost if c_rate > 0)
            net_daily_usd = d_daily_usd - c_daily_usd
            action = "SHORT Delta + LONG CoinDCX"
        else:
            # Long Delta (+income if negative), Short CoinDCX (+cost if c_rate < 0)
            net_daily_usd = d_daily_usd + c_daily_usd
            action = "LONG Delta + SHORT CoinDCX"
            
        net_24h_profit = net_daily_usd - entry_fee
        daily_return_pct = (net_24h_profit / 20.0) * 100.0
        
        raw_diff = abs(d_rate - c_rate)

        results.append({
            'coin': coin,
            'delta_sym': d['sym'],
            'delta_rate': d_rate,
            'delta_h': d_h,
            'cdcx_sym': c['sym'],
            'cdcx_rate': c_rate,
            'cdcx_h': c_h,
            'raw_diff': raw_diff,
            'net_daily_usd': net_daily_usd,
            'net_24h_profit': net_24h_profit,
            'daily_return_pct': daily_return_pct,
            'action': action
        })

results.sort(key=lambda x: x['net_24h_profit'], reverse=True)

print("\n" + "=" * 130)
print("   TOP FUNDING ARBITRAGE OPPORTUNITIES ($20 CAPITAL @ 20x LEVERAGE = $200 POSITION EACH)")
print("   Sorted by NET 24-HOUR PROFIT (After $0.20 Total Trading Fees Paid)")
print("=" * 110)
print(f"{'Rank':<5} {'Coin':<10} {'Delta Rate/Pay':>18} {'CoinDCX Rate/Pay':>18} {'Raw Spread':>13} {'Net 24H Profit':>16} {'Daily Net Return%':>18}")
print("-" * 130)

for rank, r in enumerate(results[:15], 1):
    d_str = f"{r['delta_rate']:>+7.4f}% ({r['delta_h']:.0f}H)"
    c_str = f"{r['cdcx_rate']:>+7.4f}% ({r['cdcx_h']:.0f}H)"
    
    print(f"{rank:<5} {r['coin']:<10} {d_str:>18} {c_str:>18} {r['raw_diff']:>12.4f}% ${r['net_24h_profit']:>+15.4f} {r['daily_return_pct']:>+17.1f}% [PASS]")

print("=" * 130)
