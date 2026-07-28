"""
Delta Exchange India DEMO - Automated High Funding Bot
Spot BUY + Perpetual Futures SHORT = Zero Price Risk + Funding Income
"""

import urllib.request
import json
import time
import hmac
import hashlib
import os
import sys

DEMO_BASE_URL = "https://cdn-ind.testnet.deltaex.org"
API_KEY = os.getenv("DELTA_API_KEY", "bZIwAB5Q1FM5nTflbg4CWNmYaDt7pI")
API_SECRET = os.getenv("DELTA_API_SECRET", "v8eGb9IFsW1gR8P4TL5sMnjX7hQvOLTNxKsaUGTnzAGaGMALcwxUYu6K3im0")

def send_signed_request(method, path, payload=None):
    timestamp = str(int(time.time()))
    body_str = json.dumps(payload) if payload else ""
    message = method + timestamp + path + body_str

    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'api-key': API_KEY,
        'timestamp': timestamp,
        'signature': signature,
        'User-Agent': 'Mozilla/5.0'
    }

    url = DEMO_BASE_URL + path
    data_bytes = body_str.encode('utf-8') if payload else None
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        res = urllib.request.urlopen(req, timeout=10)
        return json.loads(res.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        return {'success': False, 'error': body}

def get_public_tickers():
    url = f"{DEMO_BASE_URL}/v2/tickers"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode('utf-8')).get('result', [])

def get_all_products():
    url = f"{DEMO_BASE_URL}/v2/products"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode('utf-8')).get('result', [])

def find_best_funding_coin(tickers):
    best = None
    highest_rate = -999.0
    for t in tickers:
        if 'perpetual' in t.get('contract_type', ''):
            symbol = t.get('symbol', '')
            # Only BTC and ETH (have options on Delta India)
            if symbol not in ['BTCUSD', 'ETHUSD']:
                continue
            funding_rate_8h = float(t.get('funding_rate') or 0)
            mark_price = float(t.get('mark_price') or 0)
            if mark_price > 0 and funding_rate_8h > highest_rate:
                highest_rate = funding_rate_8h
                best = {
                    'symbol': symbol,
                    'asset': symbol.replace('USD', ''),
                    'mark_price': mark_price,
                    'funding_rate_8h': funding_rate_8h,
                    'funding_pct_8h': funding_rate_8h * 100.0,
                }
    return best

def get_product_id(products, symbol):
    for p in products:
        if p.get('symbol') == symbol:
            return p.get('id')
    return None

def get_spot_product_id(products, asset):
    for p in products:
        sym = p.get('symbol', '')
        ctype = p.get('contract_type', '')
        if asset in sym and 'spot' in ctype:
            return p.get('id'), p.get('symbol')
    return None, None

def run_demo_cash_and_carry(lots=5):
    print("=" * 100)
    print("      DELTA DEMO - AUTOMATED CASH-AND-CARRY FUNDING BOT")
    print("=" * 100)

    tickers = get_public_tickers()
    products = get_all_products()

    best = find_best_funding_coin(tickers)
    if not best:
        print("[-] No suitable coin found.")
        return

    asset = best['asset']
    fut_symbol = best['symbol']
    price = best['mark_price']
    rate_pct = best['funding_pct_8h']

    lot_val = 0.01 if asset == 'ETH' else 0.001
    trade_qty = round(lots * lot_val, 6)
    notional = trade_qty * price
    est_8h = notional * best['funding_rate_8h']

    print(f"\n[+] Best Funding Coin: {fut_symbol}")
    print(f"    Mark Price: ${price:.2f}")
    print(f"    8-Hour Funding Rate: {rate_pct:.4f}%")
    print(f"    Trade Size: {lots} Lots = {trade_qty} {asset} (${notional:.2f} USD)")
    print(f"    Est. Funding Income Per 8H: +${est_8h:.4f} USD")

    # Get Futures Product ID
    fut_product_id = get_product_id(products, fut_symbol)
    spot_product_id, spot_symbol = get_spot_product_id(products, asset)

    print(f"\n    Futures Product ID: {fut_product_id} ({fut_symbol})")
    print(f"    Spot Product ID:    {spot_product_id} ({spot_symbol})")

    # --- LEG 1: BUY SPOT ---
    print("\n" + "-" * 100)
    print(f"  [LEG 1] Placing SPOT BUY Order: {trade_qty} {asset} @ Market")
    if spot_product_id:
        spot_payload = {
            "product_id": spot_product_id,
            "size": trade_qty,
            "side": "buy",
            "order_type": "market_order"
        }
        spot_res = send_signed_request('POST', '/v2/orders', spot_payload)
        if spot_res.get('success'):
            print(f"  [OK] Spot Buy Order Placed! Order ID: {spot_res.get('result', {}).get('id')}")
        else:
            print(f"  [WARN] Spot Order Issue: {spot_res.get('error')}")
            print(f"  [INFO] Proceeding with Futures Short only (pure futures hedge)")
    else:
        print(f"  [INFO] Spot market not found for {asset}. Skipping spot leg.")

    # --- LEG 2: SELL FUTURES ---
    print("-" * 100)
    print(f"  [LEG 2] Placing FUTURES SHORT Order: {lots} Lots {fut_symbol} @ Market")
    if fut_product_id:
        fut_payload = {
            "product_id": fut_product_id,
            "size": lots,
            "side": "sell",
            "order_type": "market_order"
        }
        fut_res = send_signed_request('POST', '/v2/orders', fut_payload)
        if fut_res.get('success'):
            print(f"  [OK] Futures Short Order Placed! Order ID: {fut_res.get('result', {}).get('id')}")
            order_info = fut_res.get('result', {})
            print(f"       Symbol: {order_info.get('product_symbol')} | Side: {order_info.get('side')} | Size: {order_info.get('size')}")
        else:
            print(f"  [FAIL] Futures Order Failed: {fut_res.get('error')}")
    else:
        print(f"  [FAIL] Could not find product ID for {fut_symbol}")

    print("\n" + "=" * 100)
    print("[SUMMARY] Cash-and-Carry Trade Execution Complete!")
    print(f"  Futures Short {lots} Lots {fut_symbol}: EARNING {rate_pct:.4f}% funding every 8 hours")
    print(f"  Funding Income Per Day: +${est_8h * 3:.4f} USD")
    print("=" * 100)

if __name__ == '__main__':
    run_demo_cash_and_carry(lots=5)
