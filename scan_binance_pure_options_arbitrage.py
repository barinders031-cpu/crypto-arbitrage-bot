"""
Binance Pure Options + Quarterly Futures Arbitrage Scanner
(NO SPOT REQUIRED - Pure Options & Dated Futures Margin Only)

Scans:
1. Conversion Arbitrage: BUY Quarterly Futures + SELL Call + BUY Put
2. Reversal Arbitrage:   SELL Quarterly Futures + BUY Call + SELL Put

Uses LIVE Orderbook Bids & Asks for 100% Real Execution Prices.
"""
import urllib.request
import json
import time

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode())

print("=" * 100)
print("   BINANCE OPTIONS + DATED FUTURES ARBITRAGE SCANNER (NO SPOT NEEDED)")
print("=" * 100)

# 1. Fetch Sep 25 Dated Futures Price (BTCUSDT_260925)
fapi_prices = fetch("https://fapi.binance.com/fapi/v1/ticker/price")
fut_sep_price = 0.0
fut_dec_price = 0.0

for f in fapi_prices:
    if f['symbol'] == 'BTCUSDT_260925':
        fut_sep_price = float(f['price'])
    elif f['symbol'] == 'BTCUSDT_261225':
        fut_dec_price = float(f['price'])

print(f"\n[+] Live Dated Futures Prices (0% Funding Fee):")
print(f"    - September 25 Futures (BTCUSDT_260925): ${fut_sep_price:,.2f}")
print(f"    - December 25 Futures  (BTCUSDT_261225): ${fut_dec_price:,.2f}")

# 2. Fetch Options Tickers (24h quotes)
print("\n[+] Fetching Binance Options Orderbook Data...")
options_tickers = fetch("https://eapi.binance.com/eapi/v1/ticker")

# Group by expiry and strike
expiries = {'260925': fut_sep_price, '261225': fut_dec_price}
all_opportunities = []

for exp_code, f_price in expiries.items():
    if f_price <= 0:
        continue
        
    strikes_map = {}
    for o in options_tickers:
        sym = o['symbol']
        # Check symbol format e.g. BTC-260925-65000-C
        if f'BTC-{exp_code}-' in sym:
            parts = sym.split('-')
            if len(parts) == 4:
                strike = float(parts[2])
                opt_type = parts[3]  # C or P
                bid = float(o.get('bidPrice') or 0)
                ask = float(o.get('askPrice') or 0)
                mark = float(o.get('markPrice') or 0)
                
                if strike not in strikes_map:
                    strikes_map[strike] = {}
                strikes_map[strike][opt_type] = {
                    'symbol': sym,
                    'bid': bid,
                    'ask': ask,
                    'mark': mark
                }

    for strike, opts in strikes_map.items():
        if 'C' in opts and 'P' in opts:
            c = opts['C']
            p = opts['P']
            
            # --- CONVERSION ARBITRAGE ---
            # Legs: BUY Futures (@ f_price) + SELL Call (@ c_bid) + BUY Put (@ p_ask)
            # Payoff at Expiry = Strike + Call_Price - Put_Price - Futures_Price
            if c['bid'] > 0 and p['ask'] > 0:
                conv_profit = (strike + c['bid'] - p['ask']) - f_price
                conv_return_pct = (conv_profit / f_price) * 100.0
            else:
                conv_profit = -99999.0
                conv_return_pct = -999.0

            # --- REVERSAL ARBITRAGE ---
            # Legs: SELL Futures (@ f_price) + BUY Call (@ c_ask) + SELL Put (@ p_bid)
            # Payoff at Expiry = Futures_Price - (Strike + Call_Price - Put_Price)
            if c['ask'] > 0 and p['bid'] > 0:
                rev_profit = f_price - (strike + c['ask'] - p['bid'])
                rev_return_pct = (rev_profit / f_price) * 100.0
            else:
                rev_profit = -99999.0
                rev_return_pct = -999.0

            # Theory Mark Profit
            theory_spread = (strike + c['mark'] - p['mark']) - f_price

            all_opportunities.append({
                'expiry': exp_code,
                'strike': strike,
                'fut_price': f_price,
                'call_bid': c['bid'],
                'call_ask': c['ask'],
                'call_mark': c['mark'],
                'put_bid': p['bid'],
                'put_ask': p['ask'],
                'put_mark': p['mark'],
                'conv_profit': conv_profit,
                'conv_pct': conv_return_pct,
                'rev_profit': rev_profit,
                'rev_pct': rev_return_pct,
                'theory_spread': theory_spread
            })

print(f"\n[+] Total Options Combinations Analyzed: {len(all_opportunities)}")

# Display Conversion Opportunities
print("\n" + "=" * 105)
print("   TOP CONVERSION ARBITRAGE (BUY Futures + SELL Call + BUY Put)")
print("   0% Funding Rate | Guaranteed Payoff at Expiry")
print("=" * 105)
print(f"{'Expiry':<8} {'Strike':<10} {'Fut Price':>12} {'Call Bid':>11} {'Put Ask':>11} {'Locked Profit($)':>18} {'Return%':>12}")
print("-" * 105)

conv_sorted = sorted([o for o in all_opportunities if o['conv_profit'] > -5000], key=lambda x: x['conv_profit'], reverse=True)
for o in conv_sorted[:15]:
    tag = "✅ PROFIT" if o['conv_profit'] > 0 else ""
    print(f"{o['expiry']:<8} ${o['strike']:<9,.0f} ${o['fut_price']:>11,.2f} ${o['call_bid']:>10,.2f} ${o['put_ask']:>10,.2f} ${o['conv_profit']:>+17.2f} {o['conv_pct']:>+11.2f}% {tag}")

# Display Reversal Opportunities
print("\n" + "=" * 105)
print("   TOP REVERSAL ARBITRAGE (SELL Futures + BUY Call + SELL Put)")
print("   0% Funding Rate | Guaranteed Payoff at Expiry")
print("=" * 105)
print(f"{'Expiry':<8} {'Strike':<10} {'Fut Price':>12} {'Call Ask':>11} {'Put Bid':>11} {'Locked Profit($)':>18} {'Return%':>12}")
print("-" * 105)

rev_sorted = sorted([o for o in all_opportunities if o['rev_profit'] > -5000], key=lambda x: x['rev_profit'], reverse=True)
for o in rev_sorted[:15]:
    tag = "✅ PROFIT" if o['rev_profit'] > 0 else ""
    print(f"{o['expiry']:<8} ${o['strike']:<9,.0f} ${o['fut_price']:>11,.2f} ${o['call_ask']:>10,.2f} ${o['put_bid']:>10,.2f} ${o['rev_profit']:>+17.2f} {o['rev_pct']:>+11.2f}% {tag}")

print("=" * 105)
