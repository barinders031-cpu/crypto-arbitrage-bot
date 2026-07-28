"""
dhan_client.py
==============

Dhan HQ API Client — Angel One client ki tarah ka structure.

Features:
  - Token-based auth (24hr JWT token, no TOTP needed)
  - Rate-limited HTTP API calls
  - Intraday candle data (1min, 5min, 15min, 25min, 60min)
  - LTP / Market Quote fetch
  - NFO Options security_id lookup via Dhan scrip master CSV
  - WebSocket live feed (MarketFeed) for real-time ticks
  - Same interface as AngelOneClient — drop-in replacement

Usage in happy_options_live.py:
    from dhan_client import DhanClient
    client = DhanClient()
    # client.login() not needed — token already in config
"""

import os
import io
import time
import csv
import json
import struct
import threading
import collections
import urllib.request
import urllib.parse
import urllib.error
import datetime
import requests

# ── dhanhq library (pip install dhanhq) ─────────────────────
try:
    from dhanhq import dhanhq as DhanHQ
except ImportError:
    DhanHQ = None
    print("[Dhan] WARNING: dhanhq library not installed. Run: pip install dhanhq")

import config


# ==============================================================================
# RATE LIMITER — Same as angel_client (20 req/sec for Dhan)
# ==============================================================================
class RateLimiter:
    """Thread-safe sliding-window rate limiter."""

    def __init__(self, max_requests_per_sec: int = 20):
        self.max_rps = max_requests_per_sec
        self.window_sec = 1.0
        self._timestamps = collections.deque()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                while self._timestamps and (now - self._timestamps[0]) >= self.window_sec:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_rps:
                    self._timestamps.append(now)
                    return
            time.sleep(0.03)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        pass


# ==============================================================================
# DHAN SCRIP MASTER — NFO Security ID Resolver
# ==============================================================================
class DhanScripMaster:
    """
    Downloads and caches Dhan's instrument CSV.
    Maps (symbol_name, expiry, strike, CE/PE) -> security_id
    """

    SCRIP_CSV_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
    LOCAL_PATH = os.path.join(os.path.dirname(__file__), "dhan_scrip_master.csv")

    def __init__(self):
        self._data = []        # list of dicts (all rows)
        self._nfo_map = {}     # symbol -> list of rows
        self._loaded = False

    def load(self, force_download: bool = False):
        """Load scrip master. Download only if not present or force_download=True."""
        if not os.path.exists(self.LOCAL_PATH) or force_download:
            print(f"[DhanScrip] Downloading Dhan scrip master CSV...")
            try:
                import requests
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = requests.get(self.SCRIP_CSV_URL, headers=headers, stream=True)
                resp.raise_for_status()
                with open(self.LOCAL_PATH, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"[DhanScrip] Downloaded to {self.LOCAL_PATH}")
            except Exception as e:
                print(f"[DhanScrip] ERROR downloading scrip master: {e}")
                return False

        try:
            with open(self.LOCAL_PATH, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                self._data = list(reader)

            # Index NFO rows by underlying name parsed from SEM_TRADING_SYMBOL
            # Format: "NIFTY-Jul2026-24000-CE" or "BANKNIFTY-Jul2026-..."
            # or BSE format: "SENSEX-Jul2026-..."
            for row in self._data:
                instr = row.get("SEM_INSTRUMENT_NAME", "")
                if instr not in ("OPTIDX", "OPTSTK"):
                    continue
                trading_sym = row.get("SEM_TRADING_SYMBOL", "")
                if not trading_sym:
                    continue
                # Extract underlying from symbol (everything before first '-')
                underlying = trading_sym.split("-")[0].strip()
                if not underlying:
                    continue
                if underlying not in self._nfo_map:
                    self._nfo_map[underlying] = []
                self._nfo_map[underlying].append(row)

            self._loaded = True
            print(f"[DhanScrip] Loaded {len(self._data)} instruments "
                  f"({len(self._nfo_map)} underlying names: {list(self._nfo_map.keys())[:10]})")
            return True
        except Exception as e:
            print(f"[DhanScrip] ERROR loading scrip master: {e}")
            return False

    def get_nfo_options(self, underlying: str = "NIFTY") -> list:
        """Return all NFO option rows for a given underlying (e.g. 'NIFTY')."""
        if not self._loaded:
            self.load()
        return self._nfo_map.get(underlying, [])

    def get_security_id(self, underlying: str, expiry_str: str, strike: float, opt_type: str) -> str:
        """
        Find Dhan security_id for a specific option contract.

        Args:
            underlying:  'NIFTY' or 'BANKNIFTY' or 'SENSEX'
            expiry_str:  'YYYY-MM-DD' format (e.g. '2025-07-10')
            strike:      Strike price as float (e.g. 23500.0)
            opt_type:    'CE' or 'PE'
        """
        if not self._loaded:
            self.load()

        rows = self._nfo_map.get(underlying, [])
        for row in rows:
            try:
                row_strike = float(row.get("SEM_STRIKE_PRICE", 0))
                row_exp    = str(row.get("SEM_EXPIRY_DATE", ""))[:10]
                row_type   = row.get("SEM_OPTION_TYPE", "")
                if (abs(row_strike - strike) < 0.5 and
                        row_exp == expiry_str and
                        row_type == opt_type):
                    return row.get("SEM_SMST_SECURITY_ID", "")
            except Exception:
                continue
        return ""

    def get_nearest_expiry_options(self, underlying: str = "NIFTY") -> dict:
        """
        Returns dict of nearest expiry options grouped by expiry date.
        Format: { expiry_str: [rows...] }
        """
        if not self._loaded:
            self.load()

        today = datetime.date.today()
        rows = self._nfo_map.get(underlying, [])

        by_expiry = {}
        for row in rows:
            exp_str = str(row.get("SEM_EXPIRY_DATE", ""))[:10]
            if not exp_str or exp_str == 'nan':
                continue
            try:
                exp_date = datetime.date.fromisoformat(exp_str)
            except Exception:
                continue
            if exp_date < today:
                continue
            if exp_str not in by_expiry:
                by_expiry[exp_str] = []
            by_expiry[exp_str].append(row)

        return by_expiry

    def get_nifty_spot_security_id(self) -> str:
        """Returns Nifty 50 index security_id for NSE_EQ (for LTP)."""
        for row in self._data:
            if (row.get("SM_SYMBOL_NAME", "") == "NIFTY" and
                    row.get("SEM_EXM_EXCH_ID", "") == "NSE_EQ" and
                    row.get("SEM_INSTRUMENT_NAME", "") == "INDEX"):
                return row.get("SEM_SMST_SECURITY_ID", "")
        return "13"  # Fallback: Nifty 50 security_id on NSE


# ==============================================================================
# MAIN CLIENT — DhanClient
# ==============================================================================
class DhanClient:
    """
    Dhan HQ API Client — same interface as AngelOneClient.

    Drop-in replacement for happy_options_live.py and other scripts.
    No TOTP/2FA needed — just access_token + client_id.
    Token lasts 24 hours (refresh on Dhan dashboard daily).
    """

    BASE_URL = "https://api.dhan.co/v2"

    # Exchange segment constants (Dhan format)
    NSE_EQ  = "NSE_EQ"
    NSE_FNO = "NSE_FNO"
    BSE_EQ  = "BSE_EQ"
    BSE_FNO = "BSE_FNO"
    MCX_COM = "MCX_COMM"

    # Instrument type constants
    OPTIDX  = "OPTIDX"
    EQUITY  = "EQUITY"
    FUTIDX  = "FUTIDX"

    # Candle interval map (Angel One format -> Dhan format)
    INTERVAL_MAP = {
        "ONE_MINUTE":   1,
        "FIVE_MINUTE":  5,
        "FIFTEEN_MINUTE": 15,
        "THIRTY_MINUTE":  25,   # Dhan uses 25 not 30
        "ONE_HOUR":    60,
    }

    def __init__(self):
        print("[Dhan] Initializing Dhan HQ API client...")

        # Load from config
        self.client_id    = getattr(config, "DHAN_CLIENT_ID", "")
        self.access_token = getattr(config, "DHAN_ACCESS_TOKEN", "")

        if not self.client_id or not self.access_token:
            print("[Dhan] WARNING: DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN not set in config.py!")

        # HTTP session with auth headers
        self._session = requests.Session()
        self._session.headers.update({
            "access-token": self.access_token,
            "client-id":    self.client_id,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        })

        # Rate limiter (Dhan allows ~20 req/sec)
        self.rate_limiter = RateLimiter(max_requests_per_sec=20)

        # dhanhq library instance (for MarketFeed WebSocket if needed later)
        self._dhan = None
        if DhanHQ is not None:
            try:
                # Some versions take (client_id, access_token), others might take a dict or single token
                try:
                    self._dhan = DhanHQ(self.client_id, self.access_token)
                except TypeError:
                    pass # We will rely on our direct HTTP implementation anyway
            except Exception as e:
                pass

        # Scrip master
        self.scrip = DhanScripMaster()
        self._scrip_loaded = False

        # Connection state
        self._is_connected = False

        print("[Dhan] Client initialized. Call load_scrip_master() to load instruments.")

    # =========================================================================
    # SESSION / LOGIN (Token-based — no TOTP needed)
    # =========================================================================
    def login(self) -> bool:
        """
        Validates the access token by making a test API call.
        Angel One ki tarah login() call karo, same interface.
        """
        try:
            self.rate_limiter.acquire()
            resp = self._session.get(f"{self.BASE_URL}/fundlimit", timeout=10)
            if resp.status_code == 200:
                self._is_connected = True
                print(f"[Dhan] Token valid! Connected to Dhan API. (Client: {self.client_id})")
                return True
            else:
                print(f"[Dhan] Token validation failed: HTTP {resp.status_code} — {resp.text[:200]}")
                self._is_connected = False
                return False
        except Exception as e:
            print(f"[Dhan] Connection error: {e}")
            self._is_connected = False
            return False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def load_scrip_master(self, force_download: bool = False) -> bool:
        """Load Dhan scrip master CSV (call once at startup)."""
        result = self.scrip.load(force_download=force_download)
        self._scrip_loaded = result
        return result

    # =========================================================================
    # LTP DATA — Angel One get_ltp_data_throttled() equivalent
    # =========================================================================
    def get_ltp_data_throttled(self, exchange: str, tradingsymbol: str, symboltoken: str) -> dict:
        """
        Angel One interface ke compatible — Nifty spot LTP fetch karta hai.

        Args:
            exchange:      'NSE' (ignored, Dhan uses segment internally)
            tradingsymbol: 'NIFTY' (ignored for index, uses security_id)
            symboltoken:   Dhan security_id (e.g. '13' for NIFTY 50)

        Returns:
            { "status": True, "data": { "ltp": 24500.0 } }
        """
        try:
            self.rate_limiter.acquire()

            # Map exchange
            seg = self.NSE_EQ
            if exchange in ("NFO", "NSE_FNO"):
                seg = self.NSE_FNO
            elif exchange in ("BSE", "BSE_EQ"):
                seg = self.BSE_EQ

            payload = {
                "securityId": str(symboltoken),
                "exchangeSegment": seg
            }
            resp = self._session.post(
                f"{self.BASE_URL}/marketfeed/ltp",
                json=payload,
                timeout=5
            )

            if resp.status_code == 200:
                data = resp.json()
                # Dhan returns { data: { <secId>: { last_price: ... } } }
                inner = data.get("data", {})
                ltp_val = None

                # Try different response formats
                if str(symboltoken) in inner:
                    ltp_val = inner[str(symboltoken)].get("last_price", 0)
                elif "last_price" in inner:
                    ltp_val = inner["last_price"]
                elif inner:
                    # First value in response
                    first = list(inner.values())[0]
                    if isinstance(first, dict):
                        ltp_val = first.get("last_price", 0)
                    else:
                        ltp_val = first

                if ltp_val is not None:
                    return {"status": True, "data": {"ltp": float(ltp_val)}}

            # Fallback: try market quote endpoint
            return self._get_market_quote_ltp(str(symboltoken), seg)

        except Exception as e:
            print(f"[Dhan] LTP fetch error: {e}")
            return {"status": False, "message": str(e)}

    def _get_market_quote_ltp(self, security_id: str, exchange_segment: str) -> dict:
        """Fallback: market quote endpoint se LTP lo."""
        try:
            payload = {
                "NSE_EQ": [security_id] if exchange_segment == self.NSE_EQ else [],
                "NSE_FNO": [security_id] if exchange_segment == self.NSE_FNO else [],
            }
            # Remove empty lists
            payload = {k: v for k, v in payload.items() if v}

            resp = self._session.post(
                f"{self.BASE_URL}/marketfeed/quote",
                json={"data": payload},
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                for seg_data in data.values():
                    if security_id in seg_data:
                        ltp = seg_data[security_id].get("last_price", 0)
                        return {"status": True, "data": {"ltp": float(ltp)}}
        except Exception:
            pass
        return {"status": False, "message": "LTP not found"}

    def get_nifty_ltp(self) -> float:
        """Direct Nifty 50 LTP. Returns float price."""
        result = self.get_ltp_data_throttled("NSE", "NIFTY", "13")
        if result.get("status"):
            return float(result["data"]["ltp"])
        return 0.0

    # =========================================================================
    # CANDLE DATA — Angel One get_candle_data_throttled() equivalent
    # =========================================================================
    def get_candle_data_throttled(self, params: dict) -> dict:
        """
        Angel One interface ke compatible candle data fetch.

        params = {
            'exchange':    'NFO' or 'NSE',
            'symboltoken': '<dhan_security_id>',
            'interval':    'FIVE_MINUTE' | 'ONE_MINUTE' | etc.,
            'fromdate':    'YYYY-MM-DD HH:MM',
            'todate':      'YYYY-MM-DD HH:MM'
        }

        Returns:
            { 'status': True, 'data': [(ts, o, h, l, c, vol), ...] }
        """
        try:
            self.rate_limiter.acquire()

            exchange   = params.get("exchange", "NFO")
            sec_id     = str(params.get("symboltoken", ""))
            interval   = params.get("interval", "FIVE_MINUTE")
            from_dt    = params.get("fromdate", "")
            to_dt      = params.get("todate", "")

            # Map Angel One interval to Dhan minutes
            minutes = self.INTERVAL_MAP.get(interval, 5)

            # Exchange segment mapping
            seg = self.NSE_FNO if exchange in ("NFO", "NSE_FNO") else self.NSE_EQ

            # Parse dates
            try:
                from_date = datetime.datetime.strptime(from_dt[:16], "%Y-%m-%d %H:%M")
                to_date   = datetime.datetime.strptime(to_dt[:16],   "%Y-%m-%d %H:%M")
            except Exception:
                from_date = datetime.datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
                to_date   = datetime.datetime.now()

            payload = {
                "securityId":      sec_id,
                "exchangeSegment": seg,
                "instrument":      self.OPTIDX if exchange == "NFO" else self.EQUITY,
                "interval":        str(minutes),
                "fromDate":        from_date.strftime("%Y-%m-%d"),
                "toDate":          to_date.strftime("%Y-%m-%d"),
            }

            resp = self._session.post(
                f"{self.BASE_URL}/charts/intraday",
                json=payload,
                timeout=10
            )

            if resp.status_code == 200:
                data = resp.json()
                candles_raw = data.get("data", data.get("candles", []))
                candles = self._normalize_candles(candles_raw, from_date, to_date)
                return {"status": True, "data": candles}
            else:
                return {"status": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}

        except Exception as e:
            return {"status": False, "message": str(e)}

    def _normalize_candles(self, raw: list, from_dt, to_dt) -> list:
        """
        Normalize Dhan candle format to Angel One format:
        [(timestamp_str, open, high, low, close, volume), ...]
        """
        result = []
        for c in raw:
            try:
                if isinstance(c, (list, tuple)) and len(c) >= 6:
                    # Already in list format [ts, o, h, l, c, v]
                    ts = c[0]
                    if isinstance(ts, (int, float)):
                        ts = datetime.datetime.fromtimestamp(ts / 1000).isoformat()
                    result.append((str(ts), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])))
                elif isinstance(c, dict):
                    ts = c.get("timestamp", c.get("time", ""))
                    if isinstance(ts, (int, float)):
                        ts = datetime.datetime.fromtimestamp(ts / 1000).isoformat()
                    result.append((
                        str(ts),
                        float(c.get("open", 0)),
                        float(c.get("high", 0)),
                        float(c.get("low", 0)),
                        float(c.get("close", c.get("ltp", 0))),
                        float(c.get("volume", 0))
                    ))
            except Exception:
                continue

        # Filter by time range
        if result and from_dt and to_dt:
            filtered = []
            for c in result:
                try:
                    ct = datetime.datetime.fromisoformat(str(c[0])[:19])
                    if from_dt <= ct <= to_dt:
                        filtered.append(c)
                except Exception:
                    filtered.append(c)
            return filtered

        return result

    def get_intraday_candles(self, security_id: str, exchange_segment: str,
                              instrument_type: str, interval_minutes: int = 5,
                              from_date: str = None, to_date: str = None) -> list:
        """
        Direct Dhan API call for intraday candles.

        Args:
            security_id:       Dhan security_id string
            exchange_segment:  'NSE_FNO', 'NSE_EQ', etc.
            instrument_type:   'OPTIDX', 'EQUITY', 'FUTIDX'
            interval_minutes:  1, 5, 15, 25, 60
            from_date:         'YYYY-MM-DD' (default: today)
            to_date:           'YYYY-MM-DD' (default: today)

        Returns:
            List of (timestamp, open, high, low, close, volume) tuples
        """
        today = datetime.date.today().isoformat()
        payload = {
            "securityId":      str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument":      instrument_type,
            "interval":        str(interval_minutes),
            "fromDate":        from_date or today,
            "toDate":          to_date or today,
        }

        try:
            self.rate_limiter.acquire()
            resp = self._session.post(
                f"{self.BASE_URL}/charts/intraday",
                json=payload,
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                raw = data.get("data", data.get("candles", []))
                return self._normalize_candles(raw, None, None)
            else:
                print(f"[Dhan] Candle error for {security_id}: HTTP {resp.status_code}")
                return []
        except Exception as e:
            print(f"[Dhan] Candle exception: {e}")
            return []

    # =========================================================================
    # OPTIONS SCANNING — happy_options_live ke liye
    # =========================================================================
    def get_nfo_options_near_atm(self, underlying: str, atm_strike: float,
                                  strike_range: float = 150.0) -> list:
        """
        Nearest expiry NFO options ATM ±range ke andar return karta hai.
        happy_options_live.py mein Angel One scrip master ki jagah use karo.

        Returns:
            List of dicts: { 'security_id', 'symbol', 'strike', 'opt_type',
                              'expiry_str', 'expiry_date' }
        """
        if not self._scrip_loaded:
            self.load_scrip_master()

        by_expiry = self.scrip.get_nearest_expiry_options(underlying)
        if not by_expiry:
            print(f"[Dhan] No options found for {underlying}")
            return []

        # Pick nearest future expiry
        nearest_exp = sorted(by_expiry.keys())[0]
        candidates = []

        for row in by_expiry[nearest_exp]:
            try:
                strike     = float(row.get("SEM_STRIKE_PRICE", 0))
                opt_type   = row.get("SEM_OPTION_TYPE", "")
                security_id = row.get("SEM_SMST_SECURITY_ID", "")
                symbol     = row.get("SEM_TRADING_SYMBOL", "")

                if abs(strike - atm_strike) <= strike_range and opt_type in ("CE", "PE"):
                    candidates.append({
                        "security_id": security_id,
                        "symbol":      symbol,
                        "strike":      strike,
                        "opt_type":    opt_type,
                        "expiry_str":  nearest_exp,
                        "expiry_date": datetime.date.fromisoformat(nearest_exp),
                    })
            except Exception:
                continue

        return candidates

    # =========================================================================
    # SHUTDOWN
    # =========================================================================
    def shutdown(self):
        """Gracefully close connections."""
        print("[Dhan] Shutting down client...")
        self._is_connected = False
        try:
            self._session.close()
        except Exception:
            pass


# ==============================================================================
# QUICK TEST
# ==============================================================================
if __name__ == "__main__":
    print("=" * 55)
    print("   DHAN CLIENT — Quick Test")
    print("=" * 55)

    client = DhanClient()

    # Test 1: Login / token validation
    ok = client.login()
    print(f"\n[Test 1] Login: {'PASS' if ok else 'FAIL'}")

    if ok:
        # Test 2: Nifty LTP
        ltp = client.get_nifty_ltp()
        print(f"[Test 2] Nifty LTP: {ltp}")

        # Test 3: Load scrip master
        client.load_scrip_master()

        # Test 4: Get ATM options
        if ltp > 0:
            atm = round(ltp / 50.0) * 50.0
            opts = client.get_nfo_options_near_atm("NIFTY", atm, strike_range=100.0)
            print(f"[Test 4] ATM options found: {len(opts)}")
            for o in opts[:4]:
                print(f"  {o['opt_type']} {o['strike']:.0f} | ID: {o['security_id']} | Exp: {o['expiry_str']}")
