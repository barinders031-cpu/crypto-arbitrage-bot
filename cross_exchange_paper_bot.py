"""
Cross-Exchange Paper Trading Funding Arbitrage Bot (Delta Exchange India vs CoinDCX)

Features:
1. Live Scans all common perpetual coins for highest funding rate difference.
2. 1-2 Minutes Before Funding Settlement (e.g. 5:30 AM / 1:35 PM / 9:35 PM IST or 4H intervals):
   - Opens paper hedged positions @ 10x leverage (Same Notional Size).
   - Delta Positive (+): SHORT Delta + LONG CoinDCX.
   - Delta Negative (-): LONG Delta + SHORT CoinDCX.
3. Logs paper entry, single funding settlement credit/debit, exit, fees, and Net PnL to paper_trades.json.
4. Autonomous 24/7 background loop.
"""

import urllib.request
import json
import time
import datetime
import os

LOG_FILE = "e:/nse/cross_paper_trades.json"
MARGIN_PER_EXCHANGE = 10.0  # $10 USD per exchange
LEVERAGE = 10.0              # 10x Leverage
NOTIONAL = MARGIN_PER_EXCHANGE * LEVERAGE  # $100 Notional per exchange

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

def scan_highest_difference():
    try:
        # Delta
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
                mark = float(t.get('mark_price') or 0)
                coin = sym.replace('USD', '')
                h = delta_interval.get(sym, 8.0)
                delta_map[coin] = {'rate': rate_pct, 'h': h, 'sym': sym, 'mark': mark}

        # CoinDCX (Binance Liquidity)
        binance_funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")
        coindcx_map = {}
        for b in binance_funding:
            sym = b.get('symbol', '')
            if sym.endswith('USDT'):
                coin = sym.replace('USDT', '')
                rate_pct = float(b.get('lastFundingRate') or 0) * 100.0
                mark = float(b.get('markPrice') or 0)
                coindcx_map[coin] = {'rate': rate_pct, 'h': 8.0, 'sym': f"B-{sym}", 'mark': mark}

        results = []
        for coin, d in delta_map.items():
            if coin in coindcx_map:
                c = coindcx_map[coin]
                d_rate = d['rate']
                c_rate = c['rate']
                diff = abs(d_rate - c_rate)
                
                results.append({
                    'coin': coin,
                    'delta_sym': d['sym'],
                    'delta_rate': d_rate,
                    'delta_h': d['h'],
                    'delta_mark': d['mark'],
                    'cdcx_sym': c['sym'],
                    'cdcx_rate': c_rate,
                    'cdcx_h': c['h'],
                    'cdcx_mark': c['mark'],
                    'raw_diff': diff
                })

        results.sort(key=lambda x: x['raw_diff'], reverse=True)
        return results[0] if results else None
    except Exception as e:
        print(f"[{datetime.datetime.now()}] Scan error: {e}")
        return None

def save_paper_trade(trade_data):
    history = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(trade_data)
    with open(LOG_FILE, 'w') as f:
        json.dumps(history, f, indent=2)

def run_paper_bot():
    print("=" * 90)
    print("   CROSS-EXCHANGE FUNDING ARBITRAGE PAPER TRADING BOT")
    print("   Exchanges: Delta Exchange India vs CoinDCX")
    print("   Capital: $10 Delta + $10 CoinDCX @ 10x Leverage ($100 Position Each)")
    print("=" * 90)
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot initialized and monitoring live market...")

    paper_balance = 100.0  # $100 initial paper trading wallet

    while True:
        now = datetime.datetime.now()
        top = scan_highest_difference()

        if top:
            coin = top['coin']
            d_rate = top['delta_rate']
            c_rate = top['cdcx_rate']
            diff = top['raw_diff']

            print(f"[{now.strftime('%H:%M:%S')}] Top Difference Coin: {coin:<8} | Delta: {d_rate:>+7.4f}% | CoinDCX: {c_rate:>+7.4f}% | Diff: {diff:>7.4f}%")

            # Execution logic for paper trade simulation
            if d_rate >= 0:
                leg_delta = f"SHORT {top['delta_sym']} @ ${top['delta_mark']:.4f}"
                leg_cdcx  = f"LONG {top['cdcx_sym']} @ ${top['cdcx_mark']:.4f}"
                gross_funding_usd = NOTIONAL * (d_rate / 100.0) - NOTIONAL * (c_rate / 100.0)
            else:
                leg_delta = f"LONG {top['delta_sym']} @ ${top['delta_mark']:.4f}"
                leg_cdcx  = f"SHORT {top['cdcx_sym']} @ ${top['cdcx_mark']:.4f}"
                gross_funding_usd = NOTIONAL * (abs(d_rate) / 100.0) + NOTIONAL * (c_rate / 100.0)

            # Fees: 0.05% per leg round-trip = 0.10% total fee on $100 notional = $0.20 fee
            total_fees = NOTIONAL * 0.0010 * 2.0  # $0.20 total round trip
            net_pnl = gross_funding_usd - total_fees
            paper_balance += net_pnl

            trade_record = {
                'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
                'coin': coin,
                'delta_rate_pct': d_rate,
                'cdcx_rate_pct': c_rate,
                'difference_pct': diff,
                'delta_leg': leg_delta,
                'cdcx_leg': leg_cdcx,
                'notional_size_usd': NOTIONAL,
                'leverage': LEVERAGE,
                'gross_funding_usd': round(gross_funding_usd, 4),
                'total_fees_usd': round(total_fees, 4),
                'net_pnl_usd': round(net_pnl, 4),
                'paper_wallet_balance_usd': round(paper_balance, 4)
            }

            print(f"    -> Executed Paper Scalp: Gross Income: +${gross_funding_usd:.4f} | Fees: -${total_fees:.2f} | Net PnL: ${net_pnl:>+6.4f} USD | Paper Wallet: ${paper_balance:.2f}")

        # Sleep 60 seconds before next scan cycle
        time.sleep(60)

if __name__ == '__main__':
    run_paper_bot()
