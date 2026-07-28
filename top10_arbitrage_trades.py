"""
Detailed 50%+ Net Profit Arbitrage Breakdown (Delta Exchange India)
Scans ALL Expiries & Asset Classes for both Conversion & Reversal
"""
import urllib.request
import json

BASE = "https://api.india.delta.exchange"

def fetch(path):
    req = urllib.request.Request(BASE + path, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode()).get('result', [])

products = fetch('/v2/products')
tickers = fetch('/v2/tickers')
ticker_map = {t['symbol']: t for t in tickers}

futures = [p for p in products if p.get('contract_type') in ['perpetual_futures', 'futures']]
options = [p for p in products if p.get('contract_type') in ['call_options', 'put_options']]

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

fut_prices = {}
for f in futures:
    sym = f.get('symbol', '')
    t = ticker_map.get(sym, {})
    mark = float(t.get('mark_price') or 0)
    if sym == 'BTCUSD':
        fut_prices['BTC'] = mark
    elif sym == 'ETHUSD':
        fut_prices['ETH'] = mark

results = []

for (asset, expiry, strike), opts in options_by_exp.items():
    if 'C' in opts and 'P' in opts:
        f_price = fut_prices.get(asset, 0)
        if f_price <= 0:
            continue
            
        c = opts['C']
        p = opts['P']
        
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

        if conv_10lots >= min_gross_required:
            retention = (conv_net_10lots / conv_10lots) * 100.0
            results.append({
                'asset': asset,
                'type': 'CONVERSION',
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
                'type': 'REVERSAL',
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

print("=" * 115)
print("   TOP 10 BEST PROFIT ARBITRAGE TRADES ON DELTA EXCHANGE INDIA")
print("   Rule: Net Retention >= 50% | Direct Green Payoff")
print("=" * 115)
print(f"{'#':<3} {'Asset':<6} {'Type':<12} {'Expiry':<8} {'Strike':<9} {'Fut Price':>11} {'Gross (10L)':>12} {'Net Profit':>12} {'Retention%':>12}")
print("-" * 115)

for i, r in enumerate(results[:10], 1):
    print(f"{i:<3} {r['asset']:<6} {r['type']:<12} {r['expiry']:<8} ${r['strike']:<8,.0f} ${r['f_price']:>10,.2f} ${r['gross_10lots']:>+11.4f} ${r['net_10lots']:>+11.4f} {r['retention']:>11.1f}% [PASS]")

print("=" * 115)
