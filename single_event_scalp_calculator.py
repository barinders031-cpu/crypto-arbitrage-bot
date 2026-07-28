"""
Single Funding Event Scalp Calculator (1-Minute Entry + Exit)
Capital: $10 Margin Delta + $10 Margin CoinDCX @ 20x = $200 Position Each
Calculates: Single Event Gross Funding - Total Entry+Exit Trading Fees ($0.40 Total Fee)
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

# Trade Parameters:
# Capital: $10 Delta + $10 CoinDCX @ 20x = $200 Position Size each
notional = 200.0

# Trading Fees for 1 Single Scalp (Entry + Exit on both exchanges):
# Entry: 0.05% Delta ($0.10) + 0.05% CoinDCX ($0.10) = $0.20
# Exit:  0.05% Delta ($0.10) + 0.05% CoinDCX ($0.10) = $0.20
# Total Round-Trip Entry + Exit Fees = $0.40 USD
total_scalp_fee = 0.40  # $0.40 USD

results = []

for coin, d in delta_map.items():
    if coin in coindcx_map:
        c = coindcx_map[coin]
        d_rate = d['rate']
        c_rate = c['rate']
        
        # Single Event Funding Income / Expense
        # Delta single payment income:
        d_single_usd = notional * (abs(d_rate) / 100.0)
        
        # CoinDCX single payment cost:
        c_single_usd = notional * (abs(c_rate) / 100.0)
        
        # Net Single Event Gross Funding Credit
        if d_rate >= 0:
            # Short Delta (+income), Long CoinDCX (-cost if c_rate > 0)
            gross_single_usd = d_single_usd - (notional * (c_rate / 100.0))
            action = "SHORT Delta + LONG CoinDCX"
        else:
            # Long Delta (+income if negative), Short CoinDCX (+income/cost if c_rate < 0)
            gross_single_usd = d_single_usd + (notional * (abs(c_rate) / 100.0))
            action = "LONG Delta + SHORT CoinDCX"
            
        # Net Scalp Profit after $0.40 fees
        net_scalp_profit = gross_single_usd - total_scalp_fee
        
        results.append({
            'coin': coin,
            'delta_rate': d_rate,
            'delta_h': d['h'],
            'cdcx_rate': c_rate,
            'cdcx_h': c['h'],
            'gross_single_usd': gross_single_usd,
            'total_fee': total_scalp_fee,
            'net_scalp_profit': net_scalp_profit,
            'pass_scalp': net_scalp_profit > 0,
            'action': action
        })

results.sort(key=lambda x: x['net_scalp_profit'], reverse=True)

print("\n" + "=" * 125)
print("   SINGLE FUNDING EVENT SCALP CALCULATOR ($20 CAPITAL @ 20x LEVERAGE = $200 POSITION EACH)")
print("   Entry 1-Min Before Funding -> Receive Single Payment -> Exit 1-Min After")
print("   Total Trading Fees Paid (Entry + Exit on Both Exchanges) = -$0.40 USD")
print("=" * 125)
print(f"{'Rank':<5} {'Coin':<10} {'Delta Rate/Pay':>18} {'CoinDCX Rate/Pay':>18} {'Single Gross Income':>20} {'Total Entry+Exit Fee':>22} {'NET SCALP PROFIT':>18} {'Status':>10}")
print("-" * 125)

for rank, r in enumerate(results[:15], 1):
    d_str = f"{r['delta_rate']:>+7.4f}% ({r['delta_h']:.0f}H)"
    c_str = f"{r['cdcx_rate']:>+7.4f}% ({r['cdcx_h']:.0f}H)"
    status = "[PROFIT]" if r['pass_scalp'] else "[LOSS]"
    
    print(f"{rank:<5} {r['coin']:<10} {d_str:>18} {c_str:>18} ${r['gross_single_usd']:>+19.4f} ${r['total_fee']:>21.2f} ${r['net_scalp_profit']:>+17.4f} {status:>10}")

print("=" * 125)
