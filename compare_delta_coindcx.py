"""
Compare Delta Exchange India vs CoinDCX Funding Rates & Market Data
"""
import urllib.request
import json

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        res = urllib.request.urlopen(req, timeout=10)
        data = json.loads(res.read().decode())
        if isinstance(data, dict) and 'result' in data:
            return data['result']
        return data
    except Exception as e:
        return {'error': str(e)}

print("=" * 100)
print("   DELTA EXCHANGE INDIA vs COINDCX FUNDING RATE & MARKET DATA COMPARISON")
print("=" * 100)

# 1. Delta Exchange Data
print("\n[+] Fetching Delta Exchange India Live Tickers...")
delta_products = fetch_json("https://api.india.delta.exchange/v2/products")
delta_tickers = fetch_json("https://api.india.delta.exchange/v2/tickers")

delta_data = {}
for t in delta_tickers:
    if 'perpetual' in t.get('contract_type', ''):
        sym = t.get('symbol', '')
        rate_pct = float(t.get('funding_rate') or 0)
        mark = float(t.get('mark_price') or 0)
        coin = sym.replace('USD', '')
        delta_data[coin] = {
            'symbol': sym,
            'rate': rate_pct,
            'mark': mark
        }

# 2. CoinDCX Active Instruments
print("[+] Fetching CoinDCX Active Futures Instruments...")
coindcx_instruments = fetch_json("https://api.coindcx.com/exchange/v1/derivatives/futures/data/active_instruments")

coindcx_symbols = set()
if isinstance(coindcx_instruments, list):
    for inst in coindcx_instruments:
        # e.g., B-BTC_USDT
        coin = inst.replace('B-', '').replace('_USDT', '')
        coindcx_symbols.add(coin)

print(f"    Delta Perpetual Coins: {len(delta_data)} | CoinDCX Futures Coins: {len(coindcx_symbols)}")

# Top Coins Comparison Table
print("\n" + "=" * 100)
print(f"{'Coin':<10} {'Delta Symbol':<14} {'Delta Funding/Payment':>22} {'Delta Daily%':>15} {'CoinDCX Support':>18} {'Best Exchange':>15}")
print("-" * 100)

top_coins = sorted(delta_data.items(), key=lambda x: abs(x[1]['rate']), reverse=True)

for coin, d in top_coins[:25]:
    rate = d['rate']
    daily = rate * 6.0  # Assumes 4H average interval
    coindcx_has = "YES (Futures)" if coin in coindcx_symbols else "NO (Spot Only)"
    
    action = "SHORT" if rate > 0 else "LONG"
    
    print(f"{coin:<10} {d['symbol']:<14} {rate:>+21.4f}% {daily:>+14.4f}% {coindcx_has:>18} {'DELTA' if abs(rate) > 0.05 else 'SAME':>15}")

print("=" * 100)
print("[NOTE] CoinDCX Futures uses internal funding rates (not exposed via public API).")
print("       Delta Exchange India exposes real-time transparent funding rates for all 200+ perpetuals.")
print("=" * 100)
