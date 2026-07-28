"""
Delta Exchange India - API Client
==================================
Authenticated client for Delta Exchange India API.
"""

import os
import requests
import time
import hmac
import hashlib
import json
from datetime import datetime

BASE_URL = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange")

class DeltaClient:
    def __init__(self, api_key=None, api_secret=None, base_url=None):
        self.api_key = api_key or os.getenv("DELTA_API_KEY", "bZIwAB5Q1FM5nTflbg4CWNmYaDt7pI")
        self.api_secret = api_secret or os.getenv("DELTA_API_SECRET", "v8eGb9IFsW1gR8P4TL5sMnjX7hQvOLTNxKsaUGTnzAGaGMALcwxUYu6K3im0")
        self.base_url = base_url or BASE_URL
        self.session = requests.Session()
    
    def _sign(self, method, path, body=''):
        """Create HMAC signature for Delta Exchange."""
        timestamp = str(int(datetime.now().timestamp()))
        message = method.upper() + timestamp + path + body
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return timestamp, signature
    
    def _request(self, method, path, data=None, signed=True, max_retries=3):
        """Make authenticated request with automatic retry and rate-limit backoff."""
        url = self.base_url + path
        body = json.dumps(data) if data else ''
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        for attempt in range(max_retries):
            if signed:
                timestamp, signature = self._sign(method, path, body)
                headers['api-key'] = self.api_key
                headers['timestamp'] = timestamp
                headers['signature'] = signature
                headers['X-API-KEY'] = self.api_key
                headers['X-API-TIMESTAMP'] = timestamp
                headers['X-API-SIGNATURE'] = signature
            
            try:
                m = method.upper()
                if m == 'GET':
                    resp = self.session.get(url, headers=headers, timeout=10)
                elif m == 'DELETE':
                    resp = self.session.delete(url, headers=headers, data=body, timeout=10)
                elif m == 'PUT':
                    resp = self.session.put(url, headers=headers, data=body, timeout=10)
                else:
                    resp = self.session.post(url, headers=headers, data=body, timeout=10)
                
                # If rate limited (HTTP 429), wait and retry
                if resp.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue

                return resp.status_code, resp.json()
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    print(f"API Connection Error on {path}: {e}")
                    return 0, {'error': str(e), 'success': False}

        return 0, {'error': 'Max retries exceeded', 'success': False}
    
    def get_wallet_balance(self):
        """Get wallet balance."""
        code, data = self._request('GET', '/v2/wallet/balances')
        return data
    
    def get_positions(self, underlying_asset_symbol=None):
        """Get open positions. Demo API requires underlying_asset_symbol or product_id."""
        # Try with BTC filter first (required by demo/testnet API)
        path = '/v2/positions'
        if underlying_asset_symbol:
            path += f'?underlying_asset_symbol={underlying_asset_symbol}'
        code, data = self._request('GET', path)
        
        # If bad_schema error, try with BTC as default (demo API requirement)
        if data.get('error', {}).get('code') == 'bad_schema':
            code, data = self._request('GET', '/v2/positions?underlying_asset_symbol=BTC')
        
        return data

    def get_all_positions(self):
        """Get ALL open positions across all assets (tries multiple calls)."""
        all_positions = []
        for asset in ['BTC', 'ETH', 'SOL']:
            code, data = self._request('GET', f'/v2/positions?underlying_asset_symbol={asset}')
            if data.get('success') and data.get('result'):
                result = data['result']
                if isinstance(result, list):
                    all_positions.extend(result)
                elif isinstance(result, dict):
                    all_positions.append(result)
        # Return in same format as single get_positions
        return {'success': True, 'result': all_positions} if all_positions else {'success': False, 'result': []}
    
    def get_orders(self, status='open'):
        """Get orders."""
        code, data = self._request('GET', f'/v2/orders?status={status}')
        return data
    
    def place_order(self, symbol, side, size, price=None, order_type='limit_order', reduce_only=False):
        """Place an order on Delta Exchange.
        
        Args:
            symbol: e.g., 'C-BTC-64000-240726' or 'BTCUSD'
            side: 'buy' or 'sell'
            size: quantity (int or float)
            price: limit price
            order_type: 'limit_order' or 'market_order'
            reduce_only: boolean flag
        """
        # Map simple type if passed
        otype = 'limit_order' if 'limit' in str(order_type).lower() else 'market_order'

        data = {
            'product_symbol': symbol,
            'side': side,
            'size': int(size),
            'order_type': otype,
            'time_in_force': 'gtc'
        }
        
        if reduce_only:
            data['is_reduce_only'] = True
        
        if price and otype == 'limit_order':
            data['limit_price'] = str(price)
        
        code, resp = self._request('POST', '/v2/orders', data)
        return code, resp

    def cancel_order(self, order_id, product_id):
        """Cancel an open order by ID and product_id."""
        data = {'id': order_id, 'product_id': product_id}
        code, resp = self._request('DELETE', '/v2/orders', data)
        return code, resp

    def edit_order(self, order_id, product_id, new_price, size=None):
        """Edit an open limit order's price or size via PUT /v2/orders."""
        data = {
            'id': int(order_id),
            'product_id': int(product_id),
            'limit_price': str(new_price)
        }
        if size:
            data['size'] = int(size)
        code, resp = self._request('PUT', '/v2/orders', data)
        return code, resp

    def get_order_by_id(self, order_id):
        """Get status of specific order by order_id."""
        code, resp = self._request('GET', f'/v2/orders/{order_id}')
        return code, resp

    def cancel_all_orders(self):
        """Cancel all open orders."""
        orders_resp = self.get_orders(status='open')
        if orders_resp.get('success') and orders_resp.get('result'):
            for o in orders_resp['result']:
                self.cancel_order(o.get('id'), o.get('product_id'))
    
    def close_position(self, symbol, current_size):
        """Close an open position completely.
        
        Args:
            symbol: product symbol
            current_size: signed integer/float (positive for long, negative for short)
        """
        if current_size == 0:
            return 200, {'message': 'No open position to close'}
        
        side = 'sell' if current_size > 0 else 'buy'
        qty = abs(current_size)
        return self.place_order(symbol, side, qty, order_type='market', reduce_only=True)
    
    def get_ticker(self, symbol='BTCUSD'):
        """Get ticker data."""
        code, data = self._request('GET', f'/v2/tickers/{symbol}', signed=False)
        return data
    
    def get_orderbook(self, symbol='BTCUSD'):
        """Get order book."""
        code, data = self._request('GET', f'/v2/l2orderbook/{symbol}', signed=False)
        return data
    
    def get_klines(self, symbol, resolution='5m', limit=100):
        """Get candlestick data."""
        end_time = int(datetime.now().timestamp())
        start_time = end_time - (limit * 300)
        
        params = f"?symbol={symbol}&resolution={resolution}&start={start_time}&end={end_time}"
        code, data = self._request('GET', f'/v2/history/candles{params}', signed=False)
        return data
    
    def get_products(self):
        """Get all products."""
        code, data = self._request('GET', '/v2/products', signed=False)
        return data
    
    def get_product(self, symbol):
        """Get specific product info."""
        code, data = self._request('GET', f'/v2/products/{symbol}', signed=False)
        return data

# Test connection
if __name__ == "__main__":
    client = DeltaClient(
        api_key="DbACPKTPtOnNdnE5bGOycFMJMoCkQU",
        api_secret="bSH9VobunFc43kfdtCnpGegGuNvTH85Phztzy44FMwtoo7xQXDHLi9MIaObE"
    )
    
    print("Testing Delta Exchange India API...")
    
    # Test public endpoint
    ticker = client.get_ticker('BTCUSD')
    print(f"BTCUSD Ticker: {ticker}")
    
    # Test authenticated endpoint
    balance = client.get_wallet_balance()
    print(f"Wallet Balance: {balance}")
