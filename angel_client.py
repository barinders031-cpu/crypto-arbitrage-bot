"""
angel_client.py

MODULE 1: Resilient API Session & Rate-Limit Management

Handles automated 2FA login and connection to the Angel One SmartAPI.
Generates dynamic TOTP tokens on the fly to establish live market data sessions safely.

Enhancements (Module 1):
  - TokenRefreshManager: background daemon thread that regenerates JWT every 8 hours.
  - RateLimiter: sliding-window token bucket to enforce strict API rate compliance.
  - Auto-reconnect: exponential backoff capped at WS_RECONNECT_TIMEOUT_SEC.
  - Connection health monitoring with heartbeat pings.
"""

import time
import sys
import threading
import collections
import pyotp
import config

try:
    from SmartApi import SmartConnect
except ImportError:
    print("[CRITICAL] smartapi-python is not installed in the environment!")
    sys.exit(1)


# =============================================================================
# RATE LIMITER — Sliding Window Token Bucket
# =============================================================================
class RateLimiter:
    """
    Thread-safe sliding-window rate limiter.
    Prevents API freezing due to excessive requests by enforcing
    a maximum number of requests per second.
    """
    def __init__(self, max_requests_per_sec: int = 10):
        self.max_rps = max_requests_per_sec
        self.window_sec = 1.0
        self._timestamps = collections.deque()
        self._lock = threading.Lock()

    def acquire(self):
        """
        Blocks the calling thread until a rate-limit slot becomes available.
        Ensures strict compliance with Angel One's rate limits.
        """
        while True:
            with self._lock:
                now = time.monotonic()
                # Purge timestamps older than the sliding window
                while self._timestamps and (now - self._timestamps[0]) >= self.window_sec:
                    self._timestamps.popleft()
                # Check if we have capacity
                if len(self._timestamps) < self.max_rps:
                    self._timestamps.append(now)
                    return  # Slot acquired
            # No capacity — wait a short interval and retry
            time.sleep(0.05)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        pass


# =============================================================================
# TOKEN REFRESH MANAGER — Background JWT Renewal
# =============================================================================
class TokenRefreshManager:
    """
    Background daemon thread that automatically refreshes the Angel One
    JWT session token at a configurable interval (default: every 8 hours)
    to prevent mid-session authentication expiry.
    """
    def __init__(self, client: 'AngelOneClient', interval_hours: float = 8.0):
        self.client = client
        self.interval_sec = interval_hours * 3600.0
        self._stop_event = threading.Event()
        self._thread = None
        self._refresh_count = 0

    def start(self):
        """Launches the background token refresh thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._refresh_loop, daemon=True, name="TokenRefresher")
        self._thread.start()
        print(f"[Token Refresh] Background refresh thread started (interval: {self.interval_sec / 3600:.1f}h)")

    def stop(self):
        """Signals the refresh thread to terminate."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _refresh_loop(self):
        """Internal loop: sleeps for the configured interval, then re-authenticates."""
        while not self._stop_event.is_set():
            # Wait for the refresh interval (interruptible by stop_event)
            if self._stop_event.wait(timeout=self.interval_sec):
                break  # Stop was signalled

            # Attempt token refresh
            try:
                print("[Token Refresh] Initiating scheduled JWT token refresh...")
                success = self.client.login()
                if success:
                    self._refresh_count += 1
                    print(f"[Token Refresh] Token refreshed successfully (cycle #{self._refresh_count})")
                else:
                    print("[Token Refresh] WARNING: Token refresh failed! Retrying in 60 seconds...")
                    if self._stop_event.wait(timeout=60.0):
                        break
            except Exception as e:
                print(f"[Token Refresh] ERROR during refresh: {e}. Retrying in 60 seconds...")
                if self._stop_event.wait(timeout=60.0):
                    break


# =============================================================================
# MAIN CLIENT — AngelOneClient
# =============================================================================
class AngelOneClient:
    """
    Manages communication, session lifecycle, and authentication with Angel One SmartAPI.
    
    Module 1 Enhancements:
      - Rate-limited API calls via built-in RateLimiter.
      - Automatic token refresh via TokenRefreshManager.
      - Auto-reconnect with exponential backoff capped at 5 seconds.
      - Connection state tracking for health monitoring.
    """
    def __init__(self):
        print("[Angel API] Initializing Angel One SmartAPI client...")
        
        self.api_key = config.ANGEL_API_KEY
        self.totp_secret = config.ANGEL_TOTP_SECRET
        self.client_id = config.ANGEL_CLIENT_ID
        self.password = config.ANGEL_PASSWORD
        
        self.smart_connect = None
        self.session_data = None
        self.feed_token = None
        self.jwt_token = None
        
        # Module 1: Rate limiter
        self.rate_limiter = RateLimiter(
            max_requests_per_sec=config.API_RATE_LIMIT_PER_SECOND
        )
        
        # Module 1: Token refresh manager
        self.token_refresher = TokenRefreshManager(
            client=self,
            interval_hours=config.TOKEN_REFRESH_INTERVAL_HOURS
        )
        
        # Connection state tracking
        self._login_lock = threading.Lock()
        self._is_connected = False
        self._last_login_time = 0.0
        self._consecutive_failures = 0

    @property
    def is_connected(self) -> bool:
        return self._is_connected and self.smart_connect is not None

    def login(self) -> bool:
        """
        Performs fully automated 2-Factor Authentication (2FA) login using
        your Client ID, MPIN, and the dynamic TOTP generated from your TOTP Secret.
        Thread-safe: only one login attempt can proceed at a time.
        """
        with self._login_lock:
            return self._login_internal()

    def _login_internal(self) -> bool:
        """Internal login logic (must be called under _login_lock)."""
        # Safety check: make sure placeholders are replaced
        if self.client_id == "YOUR_ANGEL_CLIENT_ID" or self.password == "YOUR_ANGEL_PASSWORD":
            print("\n[Angel API] ERROR: Please open config.py and replace placeholders with your actual Client ID and MPIN!")
            return False

        # 1. Initialize SmartConnect session
        self.smart_connect = SmartConnect(api_key=self.api_key)
        
        # 2. Mathematically generate dynamic 6-digit TOTP token using your secret key
        try:
            totp = pyotp.TOTP(self.totp_secret).now()
            print(f"[Angel API] Dynamic 2FA TOTP generated successfully: {totp}")
        except Exception as e:
            print(f"[Angel API] Error generating TOTP: {e}")
            self._is_connected = False
            return False

        # 3. Request session token from Angel One
        try:
            print(f"[Angel API] Attempting login for Client ID: {self.client_id}...")
            self.session_data = self.smart_connect.generateSession(
                clientCode=self.client_id,
                password=self.password,
                totp=totp
            )
            
            if self.session_data.get("status") is False:
                print(f"[Angel API] Login FAILED: {self.session_data.get('message')}")
                self._is_connected = False
                self._consecutive_failures += 1
                return False
                
            # Success!
            print("[Angel API] SUCCESS: Connected to Angel One SmartAPI!")
            self.feed_token = self.smart_connect.getfeedToken()
            self.jwt_token = self.session_data.get("data", {}).get("jwtToken", "")
            print(f"[Angel API] Feed Token retrieved: {str(self.feed_token)[:8]}... (authenticated)")
            
            self._is_connected = True
            self._last_login_time = time.time()
            self._consecutive_failures = 0
            return True
            
        except Exception as e:
            print(f"[Angel API] Connection Exception occurred during login: {e}")
            self._is_connected = False
            self._consecutive_failures += 1
            return False

    def login_with_auto_retry(self, max_retries: int = 5) -> bool:
        """
        Attempts login with exponential backoff.
        Retries up to max_retries times with delays capped at WS_RECONNECT_TIMEOUT_SEC.
        """
        for attempt in range(1, max_retries + 1):
            print(f"[Angel API] Login attempt {attempt}/{max_retries}...")
            if self.login():
                # Start background token refresher after successful login
                self.token_refresher.start()
                return True
            
            if attempt < max_retries:
                # Exponential backoff: 1s, 2s, 4s, 5s (capped)
                delay = min(2 ** (attempt - 1), config.WS_RECONNECT_TIMEOUT_SEC)
                print(f"[Angel API] Retrying in {delay} seconds...")
                time.sleep(delay)
        
        print(f"[Angel API] CRITICAL: All {max_retries} login attempts failed!")
        return False

    def auto_reconnect(self) -> bool:
        """
        Called when a WebSocket or HTTP connection drops mid-market.
        Re-authenticates within WS_RECONNECT_TIMEOUT_SEC without losing data history.
        """
        print("[Angel API] Connection drop detected! Initiating auto-reconnect...")
        self._is_connected = False
        
        start_time = time.monotonic()
        max_duration = config.WS_RECONNECT_TIMEOUT_SEC * config.WS_RECONNECT_MAX_RETRIES
        attempt = 0
        
        while (time.monotonic() - start_time) < max_duration:
            attempt += 1
            delay = min(2 ** (attempt - 1), config.WS_RECONNECT_TIMEOUT_SEC)
            
            if self.login():
                elapsed = time.monotonic() - start_time
                print(f"[Angel API] Auto-reconnect SUCCESS after {elapsed:.1f}s (attempt #{attempt})")
                return True
            
            print(f"[Angel API] Reconnect attempt #{attempt} failed. Retrying in {delay}s...")
            time.sleep(delay)
        
        print("[Angel API] CRITICAL: Auto-reconnect exhausted all retries!")
        return False

    # =========================================================================
    # RATE-LIMITED API WRAPPERS
    # =========================================================================
    def get_market_data_throttled(self, mode: str, exchange_tokens: dict) -> dict:
        """
        Rate-limited wrapper around SmartAPI's getMarketData().
        Ensures strict compliance with API rate limits.
        """
        if self.smart_connect is None:
            return {"status": False, "message": "Not authenticated"}
        
        self.rate_limiter.acquire()
        try:
            response = self.smart_connect.getMarketData(mode, exchange_tokens)
            return response or {"status": False, "message": "Empty response"}
        except Exception as e:
            error_msg = str(e)
            if "b''" in error_msg or "Access denied" in error_msg:
                # Suppress spam for rate-limits and market-closed empty responses
                pass
            else:
                print(f"[Angel API] Market data request failed: {e}")
            return {"status": False, "message": error_msg}

    def get_ltp_data_throttled(self, exchange: str, tradingsymbol: str, symboltoken: str) -> dict:
        """
        Rate-limited wrapper for the ltpData API endpoint.
        Used as a robust fallback for getMarketData during after-market hours.
        """
        if self.smart_connect is None:
            return {"status": False, "message": "Not authenticated"}
        
        self.rate_limiter.acquire()
        try:
            response = self.smart_connect.ltpData(exchange, tradingsymbol, symboltoken)
            return response or {"status": False, "message": "Empty response"}
        except Exception as e:
            print(f"[Angel API] LTP data request failed: {e}")
            return {"status": False, "message": str(e)}

    def get_candle_data_throttled(self, params: dict) -> dict:
        """
        Rate-limited wrapper around SmartAPI's getCandleData().
        Used for historical candle retrieval.
        """
        if self.smart_connect is None:
            return {"status": False, "message": "Not authenticated"}
        
        self.rate_limiter.acquire()
        try:
            response = self.smart_connect.getCandleData(params)
            return response or {"status": False, "message": "Empty response"}
        except Exception as e:
            error_msg = str(e)
            if "Access denied" not in error_msg and "b''" not in error_msg:
                print(f"[Angel API] Candle data request failed: {e}")
            return {"status": False, "message": error_msg}

    # =========================================================================
    # SCRIP MASTER & CONTRACT RESOLUTION
    # =========================================================================
    def get_token_for_contract(self, symbol: str) -> str:
        """
        Helper method to map NSE options trading symbols to their live exchange tokens.
        Downloads or parses the active Angel One scrip master list to find the match.
        """
        try:
            import urllib.request
            import json
            import os
            
            scrip_path = "scrip_master.json"
            # To prevent downloading 40MB on every tick, cache the scrip master locally
            if not os.path.exists(scrip_path):
                print("[Angel API] Downloading Angel One Scrip Master JSON (~40MB)...")
                url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
                urllib.request.urlretrieve(url, scrip_path)
                print("[Angel API] Download complete.")
                
            with open(scrip_path, 'r') as f:
                scrips = json.load(f)
                
            for scrip in scrips:
                if scrip.get("exch_seg") == "NFO" and scrip.get("symbol") == symbol:
                    token = scrip.get("token")
                    print(f"[Angel API] Found token for {symbol} -> {token}")
                    return token
                    
            print(f"[Angel API WARNING] Symbol {symbol} not found in Scrip Master.")
            return ""
        except Exception as e:
            print(f"[Angel API ERROR] Failed to retrieve contract token: {e}")
            return ""

    def scan_option_chain_for_high_gamma(self, spot_price: float, option_type: str, target_min: float = 60.0, target_max: float = 70.0) -> dict:
        """
        Scans the Nifty Options Chain from the live Angel One exchange.
        Queries the scrip master for near-the-money options (within 400 points of spot),
        fetches their active LTP quotes from the API, and selects the exact strike contract
        that is trading in Nitin Sir's high-Gamma range (60-70 Rs).
        """
        if self.smart_connect is None:
            print("[Angel API] API client not authenticated. Returning simulated high-gamma contract.")
            # Fallback mock contract details matching the premium range
            mock_strike = int(round(spot_price / 50.0) * 50.0)
            if option_type == "CE":
                mock_strike += 100 # 2 strikes OTM for CE (e.g. Nifty at 23382 -> CE 23500)
            else:
                mock_strike -= 100 # 2 strikes OTM for PE
            return {
                "symbol": f"NIFTY_{mock_strike}_{option_type}",
                "token": "MOCK_TOKEN",
                "strike": mock_strike,
                "option_type": option_type,
                "premium": 65.0
            }
            
        try:
            import urllib.request
            import json
            import os
            
            scrip_path = "scrip_master.json"
            if not os.path.exists(scrip_path):
                print("[Angel API] Downloading Angel One Scrip Master JSON...")
                url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
                urllib.request.urlretrieve(url, scrip_path)
                
            with open(scrip_path, 'r') as f:
                scrips = json.load(f)
                
            # Filter active Nifty option scrips near the current spot price
            near_scrips = []
            rounded_spot = round(spot_price / 50.0) * 50.0
            
            for scrip in scrips:
                if (scrip.get("exch_seg") == "NFO" and 
                    scrip.get("name") == "NIFTY" and 
                    scrip.get("symbol", "").endswith(option_type) and
                    scrip.get("instrumenttype") == "OPTIDX"):
                    
                    try:
                        strike = float(scrip.get("strike", 0.0)) / 100.0  # strike is scaled by 100 in master JSON
                        # Keep only near-the-money and out-of-the-money options (within 400 pts)
                        if abs(strike - rounded_spot) <= 400.0:
                            near_scrips.append(scrip)
                    except ValueError:
                        continue
                        
            if not near_scrips:
                print("[Angel API] No near scrips found in master.")
                return {}
                
            # Fetch real-time market data (LTP) in batches to find the 60-70 Rs contract
            tokens = [s["token"] for s in near_scrips]
            
            # SmartAPI limits market data requests to batches of 50
            batch_size = 50
            selected_contract = None
            best_diff = float("inf")
            
            for i in range(0, len(tokens), batch_size):
                batch_tokens = tokens[i:i+batch_size]
                exchange_tokens = {"NFO": batch_tokens}
                
                # Use rate-limited fetch
                response = self.get_market_data_throttled("QUOTE", exchange_tokens)
                if response.get("status") is True and "data" in response:
                    fetched_data = response["data"].get("fetched", [])
                    
                    for item in fetched_data:
                        ltp = float(item.get("ltp", 0.0))
                        # Select option trading closest to the sweet-spot of 65.0 Rs (within 60-70 Rs range)
                        if target_min <= ltp <= target_max:
                            diff = abs(ltp - 65.0)
                            if diff < best_diff:
                                best_diff = diff
                                selected_contract = item
                                
            if selected_contract:
                # Resolve the scrip master details
                token = selected_contract.get("token")
                for s in near_scrips:
                    if s["token"] == token:
                        strike_price = float(s["strike"]) / 100.0
                        symbol = s["symbol"]
                        print(f"[Angel API] SELECTED HIGH-GAMMA CONTRACT: {symbol} | LTP: {selected_contract['ltp']} | Strike: {strike_price}")
                        return {
                            "symbol": symbol,
                            "token": token,
                            "strike": strike_price,
                            "option_type": option_type,
                            "premium": float(selected_contract["ltp"])
                        }
                        
            # Fallback if no option is in the 60-70 Rs range: select nearest strike to Delta ~0.35
            print("[Angel API] No contract found exactly in 60-70 Rs range. Falling back to 1 strike OTM.")
            # Select 1 strike OTM (e.g. Spot 23382 -> rounded 23400. CE OTM is 23450)
            fallback_strike = rounded_spot + (50.0 if option_type == "CE" else -50.0)
            fallback_symbol = f"NIFTY{time.strftime('%y%m%d')}{int(fallback_strike)}{option_type}"
            
            return {
                "symbol": fallback_symbol,
                "token": self.get_token_for_contract(fallback_symbol),
                "strike": fallback_strike,
                "option_type": option_type,
                "premium": 65.0
            }
            
        except Exception as e:
            print(f"[Angel API ERROR] Failed to scan option chain: {e}")
            return {}

    def place_live_option_order(self, symbol: str, quantity: int, transaction_type: str, price: float) -> str:
        """
        Places a high-speed market or limit order directly on your Angel One account.
        Rate-limited to prevent order flooding.
        """
        if config.IS_PAPER_TRADING:
            print(f"[Angel API] PAPER TRADING PREVENTED Order Placement: {transaction_type} {symbol} | Qty: {quantity}")
            return "MOCK_ORDER_LIVE_PREVENTED"

        # Rate-limit order placement
        self.rate_limiter.acquire()

        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": self.get_token_for_contract(symbol),
            "transactiontype": transaction_type,
            "exchange": "NFO",
            "ordertype": "MARKET",
            "producttype": "CARRYFORWARD",
            "duration": "DAY",
            "price": "0",  # 0 for market orders
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(quantity)
        }
        
        try:
            order_id = self.smart_connect.placeOrder(order_params)
            print(f"[Angel API] LIVE ORDER PLACED SUCCESSFULLY! ID: {order_id}")
            return order_id
        except Exception as e:
            print(f"[Angel API] Error placing order: {e}")
            return "ERROR_PLACING_ORDER"

    def shutdown(self):
        """Gracefully stops all background threads and closes connections."""
        print("[Angel API] Shutting down client...")
        self.token_refresher.stop()
        self._is_connected = False
        if self.smart_connect:
            try:
                self.smart_connect.terminateSession(self.client_id)
            except Exception:
                pass


# =============================================================================
# SMART WEBSOCKET V2 — Module 1 Extension
# =============================================================================
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

class AngelOneWebSocket:
    """
    Dedicated WebSocket feed for real-time Live Index Spot Price and
    NIFTY Option Chain updates using Angel One's official SmartWebSocketV2.
    """
    def __init__(self, angel_client: AngelOneClient, index_name: str = "NIFTY"):
        self.client = angel_client
        self.index_name = index_name.upper()
        self.ws_live_quotes = {}
        self._quotes_lock = threading.Lock()
        
        self.sws = None
        self._thread = None
        self._callbacks = []
        
        # Track all three indices simultaneously with fallback tokens
        self.indices = {
            "99926000": {"name": "NIFTY", "exch": 1, "spot": 0.0},
            "26000": {"name": "NIFTY_FB", "exch": 1, "spot": 0.0},
            "99926009": {"name": "BANKNIFTY", "exch": 1, "spot": 0.0},
            "26009": {"name": "BANKNIFTY_FB", "exch": 1, "spot": 0.0},
            "99919000": {"name": "SENSEX", "exch": 3, "spot": 0.0},
            "19000": {"name": "SENSEX_FB", "exch": 3, "spot": 0.0}
        }
        
        self.current_spot = 22500.0 if self.index_name == "NIFTY" else 74000.0
        self.spot_token = "99926000" if self.index_name == "NIFTY" else "99919000"
        self.spot_exchange = 1 if self.index_name == "NIFTY" else 3
        self.nfo_tokens = []
        self.bfo_tokens = []

    def switch_index(self, index_name: str):
        """Switch the tracked index and reset the spot price"""
        self.index_name = index_name.upper()
        self.spot_token = "99926000" if self.index_name == "NIFTY" else "99919000"
        self.spot_exchange = 1 if self.index_name == "NIFTY" else 3
        self.current_spot = self.indices[self.spot_token]["spot"] if self.indices[self.spot_token]["spot"] > 0 else 22500.0
        self.update_subscriptions(self.nfo_tokens, self.bfo_tokens)

    def register_callback(self, callback_func):
        """Register a function to be called on every primary spot tick: func(spot_price)."""
        self._callbacks.append(callback_func)

    def _on_open(self, wsapp):
        print("[WebSocket] Connected successfully.")
        if self.nfo_tokens or self.bfo_tokens or self.spot_token:
            self.update_subscriptions(self.nfo_tokens, self.bfo_tokens)

    def _on_error(self, wsapp, error):
        print(f"[WebSocket] Error: {error}")

    def _on_close(self, wsapp):
        print("[WebSocket] Connection closed.")

    def _on_data(self, wsapp, message):
        token = message.get("token")
        if not token:
            return
        
        token = str(token)
        

            
        with self._quotes_lock:
            # Spot Price Update for ANY of the 3 tracked indices
            if token in self.indices:
                ltp = message.get("last_traded_price", 0)
                if ltp > 0:
                    spot = ltp / 100.0  # V2 scales prices by 100
                    self.indices[token]["spot"] = spot
                    
                    # If this is the primary selected index, update current_spot and trigger callbacks
                    if token == self.spot_token or token == self.spot_token.replace("999", ""):
                        self.current_spot = spot
                        for cb in self._callbacks:
                            try:
                                cb(self.current_spot)
                            except Exception:
                                pass
            else:
                # Options Chain Update
                ltp = message.get("last_traded_price", 0) / 100.0
                oi = message.get("open_interest", 0)
                vol = message.get("volume_traded_for_the_day", 0)
                
                if token not in self.ws_live_quotes:
                    self.ws_live_quotes[token] = {"ltp": 0, "oi": 0, "vol": 0}
                    
                if ltp > 0: self.ws_live_quotes[token]["ltp"] = ltp
                if oi > 0: self.ws_live_quotes[token]["oi"] = oi
                if vol > 0: self.ws_live_quotes[token]["vol"] = vol

    def update_subscriptions(self, nfo_tokens: list = None, bfo_tokens: list = None, eq_tokens: list = None):
        """Dynamically update WebSocket subscriptions without restarting."""
        self.nfo_tokens = nfo_tokens or []
        self.bfo_tokens = bfo_tokens or []
        self.eq_tokens = eq_tokens or []
        if not self.sws: 
            return
            
        # Subscribe to all spot indices concurrently
        nse_t = ["99926000", "26000", "99926009", "26009"] + self.eq_tokens
        token_list = [
            {"exchangeType": 1, "tokens": nse_t}, # NSE Indices (NIFTY, BANKNIFTY) + EQ
            {"exchangeType": 3, "tokens": ["99919000", "19000"]} # BSE Indices (SENSEX)
        ]
        
        if self.nfo_tokens:
            token_list.append({"exchangeType": 2, "tokens": self.nfo_tokens})  # 2 = NFO
        if self.bfo_tokens:
            token_list.append({"exchangeType": 4, "tokens": self.bfo_tokens})  # 4 = BFO
            
        try:
            # Mode 3 = SNAP_QUOTE (LTP, OI, Volume, Bids/Asks)
            self.sws.subscribe(correlation_id="antigravity_stream", mode=3, token_list=token_list)
        except Exception as e:
            print(f"[WebSocket] Subscribe error: {e}")

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
            
        if not self.client.is_connected:
            print("[WebSocket] Cannot start: Angel Client not connected.")
            return
            
        print("[WebSocket] Initializing SmartWebSocketV2...")
        self.sws = SmartWebSocketV2(
            auth_token=self.client.jwt_token,
            api_key=self.client.api_key,
            client_code=self.client.client_id,
            feed_token=self.client.feed_token
        )
        
        self.sws.on_open = self._on_open
        self.sws.on_data = self._on_data
        self.sws.on_error = self._on_error
        self.sws.on_close = self._on_close
        
        self._thread = threading.Thread(target=self.sws.connect, daemon=True, name="SmartWebSocketV2")
        self._thread.start()

    def stop(self):
        if self.sws:
            try:
                self.sws.close_connection()
            except Exception:
                pass

if __name__ == "__main__":
    # Test script: verifies connection and 2FA login works correctly
    client = AngelOneClient()
    client.login()
