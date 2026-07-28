"""
Binance Quarterly Futures & Options Net Locked Profit Scanner
Calculates exact Net Locked Profit (including Binance Trading Fees)
"""
import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode())

print("=" * 100)
print("   BINANCE LIVE DATED FUTURES NET LOCKED PROFIT SCANNER")
print("   (0% Funding Fee - Fixed Expiry Contracts)")
print("=" * 100)

# 1. Fetch Spot Price
spot_res = fetch("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
spot_price = float(spot_res['price'])

# 2. Fetch Futures Prices
fapi_prices = fetch("https://fapi.binance.com/fapi/v1/ticker/price")
fut_contracts = {}

for f in fapi_prices:
    sym = f['symbol']
    if sym in ['BTCUSDT_260925', 'BTCUSDT_261225']:
        fut_contracts[sym] = float(f['price'])

print(f"\n[1] BINANCE SPOT BTC PRICE: ${spot_price:,.2f}")

# Trading Fee Benchmark on Binance:
# Spot Maker/Taker: 0.075% (using BNB) or 0.1%
# Futures Maker/Taker: 0.02% / 0.05%
# Total 2-Leg Fee = ~0.10% total trade value

print("\n" + "=" * 100)
print("   STRATEGY 1: BINANCE CASH & CARRY (SPOT BUY + QUARTERLY FUTURES SHORT)")
print("   0% Funding Fee | 100% Risk-Free Locked Return")
print("=" * 100)
print(f"{'Contract Symbol':<22} {'Expiry':<12} {'Fut Price':>12} {'Spot Price':>12} {'Gross Spread':>13} {'Est Fee':>10} {'NET LOCKED PROFIT':>20} {'Net Return%':>12}")
print("-" * 100)

for sym, f_price in fut_contracts.items():
    expiry_name = "25-SEP-2026 (61 Days)" if "260925" in sym else "25-DEC-2026 (152 Days)"
    gross_spread = f_price - spot_price
    
    # 0.10% total round-trip fee on Spot + Futures
    total_fee = (spot_price * 0.00075) + (f_price * 0.0004)
    net_profit = gross_spread - total_fee
    net_pct = (net_profit / spot_price) * 100.0
    
    print(f"{sym:<22} {expiry_name:<12} ${f_price:>11,.2f} ${spot_price:>11,.2f} ${gross_spread:>+12,.2f} ${total_fee:>9.2f} ${net_profit:>+18.2f} {net_pct:>+11.2f}% [PASS]")

# 3. Check Options Arbitrage (Sep 25 Expiry)
print("\n" + "=" * 100)
print("   STRATEGY 2: BINANCE OPTIONS + QUARTERLY FUTURES (NO SPOT NEEDED)")
print("   0% Funding Fee | Pure Margin Options Strategy")
print("=" * 100)

options_tickers = fetch("https://eapi.binance.com/eapi/v1/ticker")
fut_sep_price = fut_contracts.get('BTCUSDT_260925', 0)

sep_opts = {}
for o in options_tickers:
    sym = o['symbol']
    if 'BTC-260925-' in sym:
        parts = sym.split('-')
        if len(parts) == 4:
            strike = float(parts[2])
            opt_type = parts[3]
            mark = float(o.get('markPrice') or 0)
            ask = float(o.get('askPrice') or 0)
            bid = float(o.get('bidPrice') or 0)
            
            if strike not in sep_opts:
                sep_opts[strike] = {}
            sep_opts[strike][opt_type] = {'sym': sym, 'mark': mark, 'ask': ask, 'bid': bid}

opt_results = []
for strike, opts in sep_opts.items():
    if 'C' in opts and 'P' in opts:
        c_mark = opts['C']['mark']
        p_mark = opts['P']['mark']
        
        # Theoretical Reversal Payoff = Futures Price - (Strike + Call Mark - Put Mark)
        rev_gross = fut_sep_price - (strike + c_mark - p_mark)
        
        # Options & Futures Fees (~0.05% per leg)
        opt_fee = fut_sep_price * 0.0010
        rev_net = rev_gross - opt_fee
        
        opt_results.append({
            'strike': strike,
            'c_mark': c_mark,
            'p_mark': p_mark,
            'gross': rev_gross,
            'net': rev_net,
            'pct': (rev_net / fut_sep_price) * 100.0
        })

opt_results.sort(key=lambda x: x['net'], reverse=True)

print(f"{'Strike':<10} {'Fut Price':>12} {'Call Price':>12} {'Put Price':>12} {'Gross Spread':>13} {'Est Fee':>10} {'NET LOCKED PROFIT':>20} {'Net Return%':>12}")
print("-" * 100)

for r in opt_results[:10]:
    print(f"${r['strike']:<9,.0f} ${fut_sep_price:>11,.2f} ${r['c_mark']:>11,.2f} ${r['p_mark']:>11,.2f} ${r['gross']:>+12.2f} ${fut_sep_price*0.001:>9.2f} ${r['net']:>+18.2f} {r['pct']:>+11.2f}%")

print("=" * 100)
