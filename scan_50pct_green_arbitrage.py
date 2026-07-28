"""
Delta Exchange India - ALL EXPIRIES Green Arbitrage Scanner
Finds Conversion & Reversal Arbitrage with >= 50% Net Profit Retention!
"""
import urllib.request
import json

BASE = "https://api.india.delta.exchange"

def fetch(path):
    req = urllib.request.Request(BASE + path, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode()).get('result', [])

print("[+] Fetching all active products from Delta Exchange India...")
products = fetch('/v2/products')
tickers = fetch('/v2/tickers')
ticker_map = {t['symbol']: t for t in tickers}

# Filter Futures & Options
futures = [p for p in products if p.get('contract_type') in ['perpetual_futures', 'futures']]
options = [p for p in products if p.get('contract_type') in ['call_options', 'put_options']]

print(f"    Futures: {len(futures)} | Options: {len(options)}")

# Group Options by (underlying, expiry, strike)
options_by_exp = {}
for o in options:
    sym = o.get('symbol', '')
    asset = 'BTC' if 'BTC' in sym else ('ETH' if 'ETH' in sym else None)
    if not asset:
        continue
        
    parts = sym.split('-')
    if len(parts) >= 4:
        opt_type = parts[0]  # C or P
        strike = float(parts[2])
        expiry = parts[3]
        
        t = ticker_map.get(sym, {})
        quotes = t.get('quotes', {}) or {}
        
        bid = float(quotes.get('best_bid') or 0)
        ask = float(quotes.get('best_ask') or 0)
        mark = float(t.get('mark_price') or 0)
        
        key = (asset, expiry, strike)
        if key not in options_by_exp:
            options_by_exp[key] = {}
        options_by_exp[key][opt_type] = {
            'symbol': sym,
            'bid': bid,
            'ask': ask,
            'mark': mark
        }

# Get Futures Prices
fut_prices = {}
for f in futures:
    sym = f.get('symbol', '')
    t = ticker_map.get(sym, {})
    mark = float(t.get('mark_price') or 0)
    if sym == 'BTCUSD':
        fut_prices['BTC'] = mark
    elif sym == 'ETHUSD':
        fut_prices['ETH'] = mark

print(f"    BTC Futures Price: ${fut_prices.get('BTC', 0):,.2f}")
print(f"    ETH Futures Price: ${fut_prices.get('ETH', 0):,.2f}")

# Sizing & Fee Benchmarks for 10 Lots
# 10 Lots ETH = 0.1 ETH | Fee = $0.15 USD | Min Gross Profit = $0.30 USD
# 10 Lots BTC = 0.01 BTC | Fee = $0.50 USD | Min Gross Profit = $1.00 USD

results = []

for (asset, expiry, strike), opts in options_by_exp.items():
    if 'C' in opts and 'P' in opts:
        f_price = fut_prices.get(asset, 0)
        if f_price <= 0:
            continue
            
        c = opts['C']
        p = opts['P']
        
        # Prices
        c_bid = c['bid'] if c['bid'] > 0 else c['mark']
        c_ask = c['ask'] if c['ask'] > 0 else c['mark']
        
        p_bid = p['bid'] if p['bid'] > 0 else p['mark']
        p_ask = p['ask'] if p['ask'] > 0 else p['mark']

        # 1. Conversion Arbitrage: BUY Futures + SELL Call + BUY Put
        conv_gross_1lot = (strike + c_bid - p_ask) - f_price
        
        # 2. Reversal Arbitrage: SELL Futures + BUY Call + SELL Put
        rev_gross_1lot = f_price - (strike + c_ask - p_bid)

        # 10 Lots Sizing
        multiplier = 0.1 if asset == 'ETH' else 0.01
        fee_10lots = 0.15 if asset == 'ETH' else 0.50
        min_gross_required = fee_10lots * 2.0  # 50% Rule

        conv_10lots = conv_gross_1lot * multiplier
        conv_net_10lots = conv_10lots - fee_10lots
        
        rev_10lots = rev_gross_1lot * multiplier
        rev_net_10lots = rev_10lots - fee_10lots

        # Pass 50% retention filter?
        if conv_10lots >= min_gross_required:
            retention = (conv_net_10lots / conv_10lots) * 100.0
            results.append({
                'asset': asset,
                'type': 'CONVERSION (BUY Fut + SELL Call + BUY Put)',
                'expiry': expiry,
                'strike': strike,
                'f_price': f_price,
                'gross_10lots': conv_10lots,
                'net_10lots': conv_net_10lots,
                'fee': fee_10lots,
                'retention': retention,
                'c_sym': c['symbol'],
                'p_sym': p['symbol'],
            })

        if rev_10lots >= min_gross_required:
            retention = (rev_net_10lots / rev_10lots) * 100.0
            results.append({
                'asset': asset,
                'type': 'REVERSAL (SELL Fut + BUY Call + SELL Put)',
                'expiry': expiry,
                'strike': strike,
                'f_price': f_price,
                'gross_10lots': rev_10lots,
                'net_10lots': rev_net_10lots,
                'fee': fee_10lots,
                'retention': retention,
                'c_sym': c['symbol'],
                'p_sym': p['symbol'],
            })

results.sort(key=lambda x: x['net_10lots'], reverse=True)

print("\n" + "=" * 115)
print("   DELTA EXCHANGE INDIA - 50%+ PROFIT RETENTION GREEN ARBITRAGE SETUPS")
print("   Rule: Gross Profit >= 2x Entry Fee | Net Profit Retention >= 50%")
print("=" * 115)
print(f"{'Asset':<6} {'Expiry':<8} {'Strike':<9} {'Strategy Type':<40} {'Gross(10L)':>11} {'Net Profit':>12} {'Retention%':>12}")
print("-" * 115)

if not results:
    print("    No current market strikes pass the >= 50% net retention filter at this instant.")
else:
    for r in results[:20]:
        print(f"{r['asset']:<6} {r['expiry']:<8} ${r['strike']:<8,.0f} {r['type']:<40} ${r['gross_10lots']:>+10.4f} ${r['net_10lots']:>+11.4f} {r['retention']:>11.1f}% [PASS]")

print("=" * 115)
