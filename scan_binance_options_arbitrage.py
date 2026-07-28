"""
Binance Options + Quarterly Futures (0% Funding) Arbitrage Scanner
Fixing orderbook bid/ask parsing for live option contracts.
"""
import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode())

print("[+] Fetching Binance Sep 25 Options & Quarterly Futures prices...")

# Futures Price (BTCUSDT_260925)
fapi_prices = fetch("https://fapi.binance.com/fapi/v1/ticker/price")
fut_price = 0.0
for f in fapi_prices:
    if f['symbol'] == 'BTCUSDT_260925':
        fut_price = float(f['price'])
        break

print(f"    Quarterly Futures (BTCUSDT_260925) Price: ${fut_price:,.2f}")

# Fetch Option Tickers
options_tickers = fetch("https://eapi.binance.com/eapi/v1/ticker")
sep_opts = {}

for o in options_tickers:
    sym = o['symbol']
    # Match Sep 25 expiry option symbols
    if 'BTC-260925-' in sym:
        parts = sym.split('-')
        if len(parts) == 4:
            strike = float(parts[2])
            option_type = parts[3]  # C or P
            bid = float(o.get('bidPrice') or 0)
            ask = float(o.get('askPrice') or 0)
            mark = float(o.get('markPrice') or 0)
            
            if strike not in sep_opts:
                sep_opts[strike] = {}
            sep_opts[strike][option_type] = {
                'sym': sym,
                'bid': bid,
                'ask': ask,
                'mark': mark
            }

results = []

for strike, opts in sep_opts.items():
    if 'C' in opts and 'P' in opts:
        call_mark = opts['C']['mark']
        put_mark = opts['P']['mark']
        
        call_bid = opts['C']['bid'] if opts['C']['bid'] > 0 else call_mark
        call_ask = opts['C']['ask'] if opts['C']['ask'] > 0 else call_mark
        
        put_bid = opts['P']['bid'] if opts['P']['bid'] > 0 else put_mark
        put_ask = opts['P']['ask'] if opts['P']['ask'] > 0 else put_mark

        # 1. Conversion Arbitrage: BUY Futures + SELL Call + BUY Put
        # Locked Payoff at Expiry = Strike + Call Sell Price - Put Buy Price - Futures Entry Price
        conv_gross = (strike + call_bid - put_ask) - fut_price
        
        # 2. Reversal Arbitrage: SELL Futures + BUY Call + SELL Put
        # Locked Payoff at Expiry = Futures Entry Price - (Strike + Call Buy Price - Put Sell Price)
        rev_gross = fut_price - (strike + call_ask - put_bid)

        # 3. Mark Price Theoretical Spread
        theory_spread = (strike + call_mark - put_mark) - fut_price

        results.append({
            'strike': strike,
            'fut_price': fut_price,
            'call_mark': call_mark,
            'put_mark': put_mark,
            'conv_gross': conv_gross,
            'rev_gross': rev_gross,
            'theory_spread': theory_spread,
            'conv_pct': (conv_gross / fut_price) * 100.0,
            'rev_pct': (rev_gross / fut_price) * 100.0,
        })

results.sort(key=lambda x: abs(x['strike'] - fut_price))

print("\n" + "=" * 110)
print(f"   BINANCE OPTIONS ARBITRAGE (BTC September 25 Expiry - 61 Days Left)")
print("   0% Funding Fee on Quarterly Futures (BTCUSDT_260925)!")
print("=" * 110)
print(f"{'Strike':<10} {'Fut Price':>12} {'Call Price':>12} {'Put Price':>12} {'Conv Profit($)':>15} {'Rev Profit($)':>15} {'Best Strategy':>20}")
print("-" * 110)

for r in results[:20]:
    st = r['strike']
    if r['conv_gross'] > r['rev_gross'] and r['conv_gross'] > 0:
        best = f"CONVERSION (+${r['conv_gross']:.2f})"
    elif r['rev_gross'] > r['conv_gross'] and r['rev_gross'] > 0:
        best = f"REVERSAL (+${r['rev_gross']:.2f})"
    else:
        best = f"Mark Diff: ${r['theory_spread']:+.2f}"
        
    print(f"${st:<9,.0f} ${r['fut_price']:>11,.2f} ${r['call_mark']:>11,.2f} ${r['put_mark']:>11,.2f} ${r['conv_gross']:>+14.2f} ${r['rev_gross']:>+14.2f} {best:>20}")

print("=" * 110)
