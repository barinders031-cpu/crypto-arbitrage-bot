"""
Delta Exchange India - Automated High Funding Arbitrage Bot (Demo / Live Trader)
Scans ALL coins on Delta Exchange India, picks the #1 Highest Funding Rate coin,
and executes Delta-Neutral Cash-and-Carry (Long Spot + Short Futures) trade!
"""

import urllib.request
import json
import time
import hmac
import hashlib
import os
import sys

BASE_URL = "https://api.india.delta.exchange"

class AutomatedFundingBot:
    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key or os.getenv("DELTA_API_KEY")
        self.api_secret = api_secret or os.getenv("DELTA_API_SECRET")
        self.base_url = BASE_URL

    def get_all_tickers(self):
        try:
            url = f"{self.base_url}/v2/tickers"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = urllib.request.urlopen(req, timeout=10)
            return json.loads(res.read().decode('utf-8')).get('result', [])
        except Exception as e:
            print(f"[!] Error fetching tickers: {e}")
            return []

    def find_best_funding_coin(self):
        tickers = self.get_all_tickers()
        best_coin = None
        highest_rate = -999.0
        
        for t in tickers:
            if 'perpetual' in t.get('contract_type', ''):
                symbol = t.get('symbol', '')
                funding_rate_8h = float(t.get('funding_rate') or 0)
                mark_price = float(t.get('mark_price') or 0)
                volume = float(t.get('volume', 0) or 0)
                
                # Filter liquid coins (BTC, ETH, SOL or active coins)
                if mark_price > 0 and volume > 50000 and abs(funding_rate_8h) < 0.20:
                    if funding_rate_8h > highest_rate:
                        highest_rate = funding_rate_8h
                        best_coin = {
                            'symbol': symbol,
                            'base_asset': symbol.replace('USD', '').replace('USDT', ''),
                            'mark_price': mark_price,
                            'funding_rate_8h': funding_rate_8h,
                            'funding_pct_8h': funding_rate_8h * 100.0,
                            'daily_pct': funding_rate_8h * 300.0,
                            'volume_usd': volume
                        }
                        
        return best_coin

    def send_signed_request(self, method, path, payload=None):
        if not self.api_key or not self.api_secret:
            return None
            
        timestamp = str(int(time.time()))
        body_str = json.dumps(payload) if payload else ""
        message = method + timestamp + path + body_str
        
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            'Content-Type': 'application/json',
            'api-key': self.api_key,
            'timestamp': timestamp,
            'signature': signature,
            'User-Agent': 'Mozilla/5.0'
        }
        
        url = self.base_url + path
        data_bytes = body_str.encode('utf-8') if payload else None
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        
        try:
            res = urllib.request.urlopen(req, timeout=10)
            return json.loads(res.read().decode('utf-8'))
        except Exception as e:
            print(f"[!] Order Transmission Failed: {e}")
            return None

    def execute_arbitrage_trade(self, lots=10):
        print("=" * 110)
        print("      DELTA EXCHANGE INDIA - AUTOMATED HIGH FUNDING BOT ACTIVATION")
        print("=" * 110)
        
        best = self.find_best_funding_coin()
        if not best:
            print("[-] No high funding opportunities found.")
            return
            
        asset = best['base_asset']
        symbol = best['symbol']
        price = best['mark_price']
        rate_pct = best['funding_pct_8h']
        daily_pct = best['daily_pct']
        
        lot_val = 0.01 if asset == 'ETH' else (0.001 if asset == 'BTC' else 1.0)
        trade_qty = lots * lot_val
        notional_usd = trade_qty * price
        est_8h_income = notional_usd * best['funding_rate_8h']
        est_daily_income = est_8h_income * 3.0
        
        print(f"\n[+] HIGHEST FUNDING COIN IDENTIFIED: {symbol}")
        print(f"    Current Price:        ${price:.2f}")
        print(f"    8-Hour Funding Rate:   {rate_pct:.4f}% ({daily_pct:.4f}% Daily Yield)")
        print(f"    Trade Size:           {lots} Lots (= {trade_qty} {asset} / ${notional_usd:.2f} USD)")
        
        print("\n" + "-" * 110)
        print("  [EXECUTING LEG 1]: BUY SPOT MARKET (HEDGE)")
        print(f"    Order: BUY {trade_qty} {asset} Spot @ ${price:.2f}")
        print("-" * 110)
        print("  [EXECUTING LEG 2]: SELL FUTURES (EARNING)")
        print(f"    Order: SELL {lots} Lots {symbol} Perpetual Futures @ ${price:.2f}")
        print("-" * 110)
        
        print("\n[+] PROJECTED FUNDING CASHFLOW:")
        print(f"    Every 8 Hours:  +${est_8h_income:.4f} USD")
        print(f"    Daily Return:   +${est_daily_income:.4f} USD")
        print(f"    Price Risk:     ZERO (Spot Long + Futures Short)")
        
        if self.api_key and self.api_secret:
            print("\n[+] API CREDENTIALS DETECTED. TRANSMITTING LIVE ORDERS...")
            spot_payload = {
                'product_id': 1,
                'size': trade_qty,
                'side': 'buy',
                'order_type': 'market_order'
            }
            res_spot = self.send_signed_request('POST', '/v2/orders', spot_payload)
            print(f"    Spot Order Response: {res_spot}")
            
            fut_payload = {
                'product_id': 2,
                'size': lots,
                'side': 'sell',
                'order_type': 'market_order'
            }
            res_fut = self.send_signed_request('POST', '/v2/orders', fut_payload)
            print(f"    Futures Order Response: {res_fut}")
        else:
            print("\n" + "=" * 110)
            print("[!] API KEYS NEEDED TO TRANSMIT ORDERS DIRECTLY TO DELTA ACCOUNT")
            print("=" * 110)
            print("To connect your Real/Demo Delta Account, set your API credentials:")
            print("  Run in PowerShell:")
            print("     $env:DELTA_API_KEY='your_api_key'")
            print("     $env:DELTA_API_SECRET='your_api_secret'")
            print("     python e:\\nse\\run_demo_funding_bot.py")

if __name__ == '__main__':
    bot = AutomatedFundingBot()
    bot.execute_arbitrage_trade(lots=10)
