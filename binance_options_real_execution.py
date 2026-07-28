"""
Binance Options Arbitrage Real Execution Calculator (Sep 25 Expiry)
Uses real Orderbook Bids & Asks + Trading Fees for exact Net Locked Profit.
"""
import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode())

options_tickers = fetch("https://eapi.binance.com/eapi/v1/ticker")
fapi_prices = fetch("https://fapi.binance.com/fapi/v1/ticker/price")

fut_sep_price = 0.0
for f in fapi_prices:
    if f['symbol'] == 'BTCUSDT_260925':
        fut_sep_price = float(f['price'])
        break

print("=" * 100)
print(f"   BINANCE OPTIONS REAL EXECUTION SCANNER (Sep 25 Expiry - 61 Days Left)")
print(f"   Quarterly Futures Price: ${fut_sep_price:,.2f} | 0% Funding Rate!")
print("=" * 100)

sep_opts = {}
for o in options_tickers:
    sym = o['symbol']
    if 'BTC-260925-' in sym:
        parts = sym.split('-')
        if len(parts) == 4:
            strike = float(parts[2])
            opt_type = parts[3]
            bid = float(o.get('bidPrice') or 0)
            ask = float(o.get('askPrice') or 0)
            
            if strike not in sep_opts:
                sep_opts[strike] = {}
            sep_opts[strike][opt_type] = {'sym': sym, 'bid': bid, 'ask': ask}

results = []
for strike, opts in sep_opts.items():
    if 'C' in opts and 'P' in opts:
        c = opts['C']
        p = opts['P']
        
        # 1. Conversion Execution: BUY Fut (@ fut_sep_price) + SELL Call (@ c_bid) + BUY Put (@ p_ask)
        if c['bid'] > 0 and p['ask'] > 0:
            conv_gross = (strike + c['bid'] - p['ask']) - fut_sep_price
            conv_fees = (fut_sep_price * 0.0004) + (c['bid'] * 0.0003) + (p['ask'] * 0.0003)
            conv_net = conv_gross - conv_fees
        else:
            conv_net = -99999.0
            
        # 2. Reversal Execution: SELL Fut (@ fut_sep_price) + BUY Call (@ c_ask) + SELL Put (@ p_bid)
        if c['ask'] > 0 and p['bid'] > 0:
            rev_gross = fut_sep_price - (strike + c['ask'] - p['bid'])
            rev_fees = (fut_sep_price * 0.0004) + (c['ask'] * 0.0003) + (p['bid'] * 0.0003)
            rev_net = rev_gross - rev_fees
        else:
            rev_net = -99999.0
            
        results.append({
            'strike': strike,
            'c_bid': c['bid'],
            'c_ask': c['ask'],
            'p_bid': p['bid'],
            'p_ask': p['ask'],
            'conv_net': conv_net,
            'rev_net': rev_net,
            'conv_pct': (conv_net / fut_sep_price) * 100.0,
            'rev_pct': (rev_net / fut_sep_price) * 100.0,
        })

# Sort by Best Reversal / Conversion Net Profit
results.sort(key=lambda x: max(x['conv_net'], x['rev_net']), reverse=True)

print(f"\n{'Strike':<10} {'Call Bid/Ask':<18} {'Put Bid/Ask':<18} {'Conv Net($)':>14} {'Rev Net($)':>14} {'Best Strategy':>20}")
print("-" * 100)

for r in results[:15]:
    c_str = f"${r['c_bid']:.0f} / ${r['c_ask']:.0f}"
    p_str = f"${r['p_bid']:.0f} / ${r['p_ask']:.0f}"
    
    if r['conv_net'] > r['rev_net'] and r['conv_net'] > 0:
        best = f"CONVERSION (+${r['conv_net']:.2f})"
    elif r['rev_net'] > r['conv_net'] and r['rev_net'] > 0:
        best = f"REVERSAL (+${r['rev_net']:.2f})"
    else:
        best = f"Near Fair (${max(r['conv_net'], r['rev_net']):+.2f})"
        
    print(f"${r['strike']:<9,.0f} {c_str:<18} {p_str:<18} ${r['conv_net']:>+13.2f} ${r['rev_net']:>+13.2f} {best:>20}")

print("=" * 100)
