"""
Delta Exchange India - Authenticated API Client
"""

import requests
import hmac
import hashlib
import json
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

BASE_URL = "https://api.india.delta.exchange"


class DeltaClient:
    """Authenticated Delta Exchange India client."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        self.session.headers.update({
            'X-API-KEY': api_key,
            'Content-Type': 'application/json'
        })

    def _sign(self, method: str, path: str, body: str = '') -> tuple:
        """Generate HMAC-SHA256 signature."""
        timestamp = str(int(datetime.now().timestamp()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        return timestamp, signature

    def _request(self, method: str, path: str, data: Optional[Dict] = None) -> Dict:
        """Make authenticated request."""
        url = BASE_URL + path
        body = json.dumps(data) if data else ''

        headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }

        timestamp, signature = self._sign(method, path, body)
        headers['X-API-TIMESTAMP'] = timestamp
        headers['X-API-SIGNATURE'] = signature

        try:
            if method.upper() == 'GET':
                resp = self.session.get(url, headers=headers, timeout=10)
            else:
                resp = self.session.post(url, headers=headers, data=body, timeout=10)

            return resp.json() if resp.status_code == 200 else {'error': resp.text, 'status': resp.status_code}
        except Exception as e:
            return {'error': str(e), 'status': 0}

    def get_balances(self) -> Dict:
        """Get wallet balances."""
        return self._request('GET', '/v2/wallet/balances')

    def get_positions(self) -> Dict:
        """Get open positions."""
        return self._request('GET', '/v2/positions')

    def get_orders(self, status: str = 'open') -> Dict:
        """Get orders."""
        return self._request('GET', f'/v2/orders?status={status}')

    def place_order(self, symbol: str, side: str, size: float,
                    price: float = 0, order_type: str = 'market') -> Dict:
        """Place order.

        Args:
            symbol: Option symbol like 'C-BTC-64000-240726'
            side: 'buy' or 'sell'
            size: Number of contracts
            price: Limit price (0 for market)
            order_type: 'market' or 'limit'
        """
        data = {
            'symbol': symbol,
            'side': side,
            'size': str(size),
            'order_type': order_type,
            'time_in_force': 'gtc'
        }
        if price > 0 and order_type == 'limit':
            data['limit_price'] = str(price)

        return self._request('POST', '/v2/orders', data)

    def cancel_order(self, order_id: str) -> Dict:
        """Cancel order."""
        return self._request('POST', f'/v2/orders/{order_id}/cancel')

    def get_ticker(self, symbol: str = 'BTCUSD') -> Dict:
        """Get ticker (public)."""
        try:
            r = requests.get(f"{BASE_URL}/v2/tickers/{symbol}", timeout=5)
            return r.json() if r.status_code == 200 else {'error': r.text}
        except Exception as e:
            return {'error': str(e)}

    def get_orderbook(self, symbol: str = 'BTCUSD') -> Dict:
        """Get order book (public)."""
        try:
            r = requests.get(f"{BASE_URL}/v2/l2orderbook/{symbol}", timeout=5)
            return r.json() if r.status_code == 200 else {'error': r.text}
        except Exception as e:
            return {'error': str(e)}

    def get_klines(self, symbol: str, resolution: str = '5m', limit: int = 100) -> pd.DataFrame:
        """Get candles (public)."""
        import pandas as pd
        try:
            end_time = int(datetime.now().timestamp())
            start_time = end_time - (limit * 300)
            params = f"?symbol={symbol}&resolution={resolution}&start={start_time}&end={end_time}"
            r = requests.get(f"{BASE_URL}/v2/history/candles{params}", timeout=10)
            if r.status_code == 200:
                candles = r.json().get('result', [])
                df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['close'] = df['close'].astype(float)
                return df
        except:
            pass
        return pd.DataFrame()

    def get_options_chain(self, expiry_days: int = 2) -> List[Dict]:
        """Get BTC options expiring within N days."""
        try:
            r = requests.get(f"{BASE_URL}/v2/products", timeout=10)
            if r.status_code != 200:
                return []

            products = r.json().get('result', [])
            today = datetime.now().date()

            options = []
            for p in products:
                if p.get('underlying_asset', {}).get('symbol') != 'BTC':
                    continue
                if p.get('contract_type') not in ['call_options', 'put_options']:
                    continue

                expiry_str = p.get('settlement_time', '')
                if not expiry_str:
                    continue

                try:
                    expiry = datetime.strptime(expiry_str.split('T')[0], '%Y-%m-%d').date()
                    days = (expiry - today).days
                    if 0 <= days <= expiry_days:
                        options.append(p)
                except:
                    continue

            return options
        except:
            return []
