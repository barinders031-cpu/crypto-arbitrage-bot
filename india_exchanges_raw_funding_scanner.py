"""
India-Accessible Exchanges Funding Scanner (Delta India, Binance, CoinDCX, Bitget, Bybit)
RAW PER-PAYMENT DIFFERENCE ONLY (No daily yields!)
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

print("=" * 115)
print("   REAL-TIME RAW PER-PAYMENT FUNDING DIFFERENCE SCANNER (INDIA ACCESSIBLE EXCHANGES)")
print("   Exchanges: Delta Exchange India | Binance | CoinDCX | Bitget | Bybit")
print("=" * 115)

# 1. Delta Exchange India
print("\n[+] Fetching Delta Exchange India...")
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
print("[+] Fetching Binance Futures...")
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
print("[+] Fetching Bitget Futures...")
bitget_map = {}
try:
    bitget_res = fetch("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES")
    if isinstance(bitget_res, list):
        for b in bitget_res:
            sym = b.get('symbol', '')  # e.g. BTCUSDT
            if sym.endswith('USDT'):
                coin = sym.replace('USDT', '')
                rate_pct = float(b.get('fundingRate') or 0) * 100.0
                bitget_map[coin] = {'rate': rate_pct, 'h': 8.0, 'sym': sym}
except Exception as e:
    pass

# 4. Bybit
print("[+] Fetching Bybit Futures...")
bybit_map = {}
try:
    bybit_res = fetch("https://api.bybit.com/v5/market/tickers?category=linear")
    if isinstance(bybit_res, dict) and 'list' in bybit_res.get('result', {}):
        for b in bybit_res['result']['list']:
            sym = b.get('symbol', '')
            if sym.endswith('USDT'):
                coin = sym.replace('USDT', '')
                rate_pct = float(b.get('fundingRate') or 0) * 100.0
                bybit_map[coin] = {'rate': rate_pct, 'h': 8.0, 'sym': sym}
except Exception as e:
    pass

exchanges = {
    'Delta India': delta_map,
    'Binance': binance_map,
    'Bitget': bitget_map,
    'Bybit': bybit_map,
}

ex_names = list(exchanges.keys())
all_coins = set(delta_map.keys()) | set(binance_map.keys()) | set(bitget_map.keys()) | set(bybit_map.keys())

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
                
                diff = r1 - r2
                abs_diff = abs(diff)
                
                results.append({
                    'coin': coin,
                    'e1': e1, 'r1': r1, 'h1': r1_data['h'], 'sym1': r1_data['sym'],
                    'e2': e2, 'r2': r2, 'h2': r2_data['h'], 'sym2': r2_data['sym'],
                    'diff': diff,
                    'abs_diff': abs_diff
                })

results.sort(key=lambda x: x['abs_diff'], reverse=True)

print("\n" + "=" * 115)
print("   TOP 20 REAL-TIME FUNDING DIFFERENCES (RAW PER-PAYMENT RATES)")
print("   Sorted Rank-Wise by Largest Absolute Difference")
print("=" * 115)
print(f"{'Rank':<5} {'Coin':<10} {'Exchange 1':<14} {'Raw Rate 1':>16} {'Exchange 2':<14} {'Raw Rate 2':>16} {'Raw Difference':>18}")
print("-" * 115)

for rank, r in enumerate(results[:20], 1):
    str1 = f"{r['r1']:>+8.4f}% ({r['h1']:.0f}H)"
    str2 = f"{r['r2']:>+8.4f}% ({r['h2']:.0f}H)"
    diff_str = f"{r['diff']:>+10.4f}%"
    
    print(f"{rank:<5} {r['coin']:<10} {r['e1']:<14} {str1:>16} {r['e2']:<14} {str2:>16} {diff_str:>18}")

print("=" * 115)
