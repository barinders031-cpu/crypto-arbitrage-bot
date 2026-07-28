"""
Fee-Adjusted Funding Arbitrage Scanner (Retention Filter >= 30% Net Profit)
Exchanges: Delta Exchange India, Binance, Bitget
Calculates Net Profit after subtracting round-trip entry fees on both exchanges.
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
        elif isinstance(data, dict) and 'data' in data:
            return data['data']
        return data
    except Exception as e:
        return []

print("=" * 120)
print("   FEE-ADJUSTED FUNDING ARBITRAGE SCANNER (NET PROFIT RETENTION >= 30%)")
print("   Exchanges: Delta Exchange India | Binance | Bitget")
print("=" * 120)

# Fee Rates (Taker / Maker averages)
FEE_RATES = {
    'Delta India': 0.0005,  # 0.05%
    'Binance':     0.0004,  # 0.04%
    'Bitget':      0.0004,  # 0.04%
}

# 1. Delta Exchange India
delta_products = fetch("https://api.india.delta.exchange/v2/products")
delta_tickers = fetch("https://api.india.delta.exchange/v2/tickers")

delta_interval = {}
for p in delta_products:
    sym = p.get('symbol', '')
    specs = p.get('product_specs') or {}
    rei = specs.get('rate_exchange_interval')
    delta_interval[sym] = int(rei) / 3600.0 if rei else 8.0

delta_map = {}
if isinstance(delta_tickers, list):
    for t in delta_tickers:
        if 'perpetual' in t.get('contract_type', ''):
            sym = t.get('symbol', '')
            rate_pct = float(t.get('funding_rate') or 0)
            coin = sym.replace('USD', '')
            h = delta_interval.get(sym, 8.0)
            delta_map[coin] = {'rate': rate_pct, 'h': h, 'sym': sym}

# 2. Binance
binance_funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")
binance_map = {}
if isinstance(binance_funding, list):
    for b in binance_funding:
        sym = b.get('symbol', '')
        if sym.endswith('USDT'):
            coin = sym.replace('USDT', '')
            rate_pct = float(b.get('lastFundingRate') or 0) * 100.0
            binance_map[coin] = {'rate': rate_pct, 'h': 8.0, 'sym': sym}

# 3. Bitget
bitget_map = {}
try:
    bitget_res = fetch("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES")
    if isinstance(bitget_res, list):
        for b in bitget_res:
            sym = b.get('symbol', '')
            if sym.endswith('USDT'):
                coin = sym.replace('USDT', '')
                rate_pct = float(b.get('fundingRate') or 0) * 100.0
                bitget_map[coin] = {'rate': rate_pct, 'h': 8.0, 'sym': sym}
except Exception as e:
    pass

exchanges = {
    'Delta India': delta_map,
    'Binance': binance_map,
    'Bitget': bitget_map,
}

ex_names = list(exchanges.keys())
all_coins = set(delta_map.keys()) | set(binance_map.keys()) | set(bitget_map.keys())

results = []

for coin in all_coins:
    for i in range(len(ex_names)):
        for j in range(i + 1, len(ex_names)):
            e1, e2 = ex_names[i], ex_names[j]
            m1, m2 = exchanges[e1], exchanges[e2]
            
            if coin in m1 and coin in m2:
                r1_data = m1[coin]
                r2_data = m2[coin]
                
                r1 = r1_data['rate']
                r2 = r2_data['rate']
                
                # Gross Funding Spread (Per Payment)
                gross_spread = abs(r1 - r2)
                
                # Combined Round-Trip Entry Fee % for 2 exchanges
                fee1 = FEE_RATES.get(e1, 0.0005) * 100.0
                fee2 = FEE_RATES.get(e2, 0.0005) * 100.0
                total_entry_fee = fee1 + fee2  # e.g. 0.05% + 0.04% = 0.09%
                
                # Net Funding Profit Per Single Payment
                net_profit_payment = gross_spread - total_entry_fee
                
                # Net Retention Ratio = (Net Profit / Gross Spread) * 100
                if gross_spread > 0:
                    retention_ratio = (net_profit_payment / gross_spread) * 100.0
                else:
                    retention_ratio = -999.0
                
                # Filter for >= 30% Net Retention Ratio
                if retention_ratio >= 30.0 and net_profit_payment > 0:
                    results.append({
                        'coin': coin,
                        'e1': e1, 'r1': r1, 'h1': r1_data['h'],
                        'e2': e2, 'r2': r2, 'h2': r2_data['h'],
                        'gross_spread': gross_spread,
                        'entry_fee': total_entry_fee,
                        'net_profit': net_profit_payment,
                        'retention': retention_ratio,
                        'diff': r1 - r2
                    })

results.sort(key=lambda x: x['net_profit'], reverse=True)

print(f"\n[+] Total Trades Passing the >= 30% Net Profit Retention Filter: {len(results)}")
print("\n" + "=" * 125)
print(f"{'Rank':<5} {'Coin':<10} {'Ex 1':<12} {'Ex 2':<10} {'Gross Spread':>14} {'Total Fee':>11} {'NET PROFIT':>14} {'Retention%':>12} {'Status':>10}")
print("-" * 125)

for rank, r in enumerate(results[:20], 1):
    action = f"LONG {r['e1']}" if r['diff'] < 0 else f"SHORT {r['e1']}"
    print(f"{rank:<5} {r['coin']:<10} {r['e1']:<12} {r['e2']:<10} {r['gross_spread']:>+13.4f}% {r['entry_fee']:>10.4f}% {r['net_profit']:>+13.4f}% {r['retention']:>11.1f}% [PASS]")

print("=" * 125)
