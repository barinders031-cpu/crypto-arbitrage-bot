"""
config.py

This file acts as the 'Single Source of Truth' for all configuration parameters.
Upgraded to support the Multi-Stock CVD Tracker.
"""

import os

# ==============================================================================
# 1. BROKER & CONNECTIVITY SETTINGS
# ==============================================================================
IS_PAPER_TRADING = True

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Angel One SmartAPI Credentials (saved locally on your machine)
ANGEL_CLIENT_ID = os.getenv("ANGEL_CLIENT_ID", "B215426")            # Your Angel One Client Code
ANGEL_PASSWORD = os.getenv("ANGEL_PASSWORD", "5501")              # Your Angel One MPIN/Password
ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "ZedlMOJh")                          # Your Angel One API Key
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "I3QV56LMDOIRRIDUVHCI42QETM")    # Your Angel One TOTP Secret

# Dhan HQ API Credentials (token 24 hours ke liye valid, Dhan dashboard se renew karo)
# ⚠️  SECURITY: Token ko yahan hardcode mat karo — .env file mein rakho!
# .env file mein likho:  DHAN_ACCESS_TOKEN=eyJ0eXAi...
# Dhan Client ID: JWT token se decode hota hai (dhanClientId field)
DHAN_CLIENT_ID    = os.getenv("DHAN_CLIENT_ID", "1112515938")          # Dhan Client ID (from JWT payload)
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")                  # 24hr JWT token — .env se load hoga

# ==============================================================================
# 2. INSTRUMENT & SYMBOL SETTINGS (Nifty Top 15 Heavyweights)
# ==============================================================================
# We use permanent NSE Spot Token IDs which are 100% crash-proof and never expire
HEAVYWEIGHT_STOCKS = {
    "HDFCBANK": "1333",      # HDFC Bank
    "RELIANCE": "2885",      # Reliance Industries
    "ICICIBANK": "4963",     # ICICI Bank
    "INFY": "1594",          # Infosys
    "ITC": "1660",           # ITC Ltd
    "TCS": "11536",          # Tata Consultancy Services
    "LT": "11483",           # Larsen & Toubro
    "AXISBANK": "5900",      # Axis Bank
    "KOTAKBANK": "1922",     # Kotak Mahindra Bank
    "SBIN": "3045",          # State Bank of India
    "BHARTIARTL": "10604",   # Bharti Airtel
    "HUL": "1330",           # Hindustan Unilever
    "BAJFINANCE": "317",     # Bajaj Finance
    "MARUTI": "10999",       # Maruti Suzuki
    "SUNPHARMA": "3351"      # Sun Pharmaceutical
}

# Dynamic institutional weights in Nifty 50 (Total = 66.3% Nifty representation)
HEAVYWEIGHT_WEIGHTS = {
    "HDFCBANK": 11.5,
    "RELIANCE": 9.8,
    "ICICIBANK": 7.6,
    "INFY": 5.8,
    "ITC": 4.4,
    "TCS": 4.0,
    "LT": 3.6,
    "AXISBANK": 3.3,
    "KOTAKBANK": 2.9,
    "SBIN": 2.8,
    "BHARTIARTL": 2.6,
    "HUL": 2.4,
    "BAJFINANCE": 2.1,
    "MARUTI": 1.8,
    "SUNPHARMA": 1.5
}

# ==============================================================================
# 3. CVD & DASHBOARD SETTINGS
# ==============================================================================
DASHBOARD_INTERVAL_SECONDS = 5         # Refresh and print combined dashboard every 5 seconds
TICK_INTERVAL_MS = 100                 # Frequency of tick generator in simulation mode (100ms)
LOG_LEVEL = "INFO"

# ==============================================================================
# 4. OPTIONS TRADING, POSITION SIZING & RISK MANAGEMENT (Momentum Option Buying)
# ==============================================================================
LOT_SIZE = 65                           # Nifty options standard lot size (changed to 65 quantity)
CAPITAL_ALLOCATION = 100000.0          # Initial capital pool: 1 Lakh INR
MAX_RISK_PER_TRADE_PCT = 2.0           # Maximum risk: 2% of capital per trade
STOP_LOSS_PCT = 3.0                    # Options premium Stop Loss (3%) for quick cut
TARGET_PROFIT_PCT = 5.0                # Options premium Target Profit (5%) for fast targets
MAX_QUANTITY_LIMIT = 1500               # Absolute maximum options contracts (20 lots)
MAX_DAILY_LOSS_LIMIT = 5000.0           # Stop trading if realized daily loss hits 5,000 INR

# Trailing Stop-Loss Settings (Optimized for quick momentum trapping)
TRAILING_SL_ENABLED = True
TRAILING_SL_TRIGGER_PCT = 3.0           # Trail SL after premium gains 3%
TRAILING_SL_STEP_PCT = 1.5              # Move SL up in 1.5% step increments

# Time and Theta Protection (Strict fast exit)
TIME_STOP_LOSS_SECONDS = 240            # Theta decay protection: exit after 4 mins sideways (4 * 60)
FORCE_SQUARE_OFF_TIME = "15:15:00"      # Time boundary to avoid overnight holding risk

# AI Model Conviction Settings (Single Source of Truth)
AI_THRESHOLD = 59.0                     # AI success conviction threshold percentage (59.0%)

# ==============================================================================
# 5. EXPERT STRATEGY FILTERS & BOUNDARIES (Nitin Sir Strategy)
# ==============================================================================
TIME_FILTER_START = "11:00:00"         # Morning volatility standard boundary
GAP_DAY_THRESHOLD_PCT = 0.8            # Gap Day trigger threshold (0.8%)
YESTERDAY_CLOSE = 22500.0              # Yesterday Nifty Close reference for gap detection
PCR_BULL_TRIGGER = 1.25                # Institutional put-writing bullish trigger (CE Buy)
PCR_BEAR_TRIGGER = 0.75                # Institutional call-writing bearish trigger (PE Buy)

KNOWN_EVENTS_MODE = False              # Known planned events mode (boosts accuracy / overrides triggers)
UNKNOWN_EVENT_LOCK = False             # Safety lock for surprise headline events

# ==============================================================================
# 6. INDEX SELECTION & OPTION CHAIN SETTINGS
# ==============================================================================
SELECTED_INDEX = "NIFTY"               # "NIFTY" or "SENSEX"

INDEX_CONFIG = {
    "NIFTY": {
        "nse_symbol": "NIFTY",
        "exchange": "NFO",
        "spot_token": "99926000",       # NSE Index token for Nifty 50
        "lot_size": 75,
        "strike_gap": 50,              # Strike interval in points
        "grid_offset": 200,            # Ghost Grid ± offset in points
        "name": "NIFTY 50",
    },
    "SENSEX": {
        "nse_symbol": "SENSEX",
        "exchange": "BFO",
        "spot_token": "99919000",       # BSE Index token for Sensex
        "lot_size": 10,
        "strike_gap": 100,
        "grid_offset": 650,            # Proportionally scaled (~3.3x Nifty)
        "name": "BSE SENSEX",
    }
}

# Number of strikes above and below ATM to track
OPTION_CHAIN_STRIKE_RANGE = 10

# PCR Mood Classification Thresholds
PCR_STRONG_BULLISH_THRESHOLD = 1.15
PCR_STRONG_BEARISH_THRESHOLD = 0.80

# ==============================================================================
# 7. MODULE 1: RESILIENT API SESSION & RATE-LIMIT MANAGEMENT
# ==============================================================================
WS_RECONNECT_TIMEOUT_SEC = 5           # Max seconds before WebSocket auto-reconnect
WS_RECONNECT_MAX_RETRIES = 50          # Max consecutive reconnect attempts before hard stop
API_RATE_LIMIT_PER_SECOND = 10         # SmartAPI rate limit (requests/second)
TOKEN_REFRESH_INTERVAL_HOURS = 8       # JWT token refresh cycle
SESSION_HEARTBEAT_INTERVAL_SEC = 60    # Heartbeat ping to keep session alive

# ==============================================================================
# 8. MODULE 3: GHOST TRADE PRO GRID
# ==============================================================================
GHOST_GRID_CANDLE_COMPONENT = "close"  # "open", "high", "low", "close"
GHOST_GRID_CAPTURE_TIME = "09:20:00"   # IST time to lock the first 5-min candle
GHOST_GRID_FIB_RATIOS = (0.618, 0.382) # Fibonacci multipliers for sub-zone calculation
GHOST_GRID_FIB_SCALE = 0.2             # Scaling factor for Fibonacci band width

# ==============================================================================
# 9. MODULE 4: OI VELOCITY & MOMENTUM CONFLUENCE
# ==============================================================================
OI_VELOCITY_WINDOWS_MIN = [1, 3, 5]    # Rolling windows for OI delta (minutes)
OI_FETCH_INTERVAL_SEC = 30             # OI snapshot fetch interval (NSE rate-limit safe)
MOMENTUM_SUPPRESSION_MODE = "until_reversal"  # "until_reversal" or "fixed_duration"
MOMENTUM_SUPPRESSION_FIXED_MIN = 10    # Fixed suppression duration if mode is fixed_duration
CANDLE_INTERVAL_SEC = 300              # 5-minute candle aggregation interval
EMA_SHORT_PERIOD = 20                  # 20 EMA period (candles)
EMA_LONG_PERIOD = 50                   # 50 EMA period (candles)

# ==============================================================================
# 10. MODULE 5: NEWS SCRAPER & SECURITY HALT
# ==============================================================================
NEWS_SCRAPE_INTERVAL_SEC = 60          # News fetch cycle (seconds)
NEWS_HALT_DURATION_MIN = 15            # Trade generation pause after high-impact news (minutes)
NEWS_KEYWORD_MATRIX = [
    "RBI", "Interest Rate", "War", "Geopolitical",
    "Scam", "Crash", "Default", "Circuit Breaker",
    "Emergency", "Sanctions", "Nuclear", "Terror"
]
NEWS_RSS_SOURCES = [
    {"name": "NSE Announcements", "url": "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=&to_date="},
    {"name": "BSE Announcements", "url": "https://www.bseindia.com/XML/RSSFeeds/CorpAnn.xml"},
    {"name": "MoneyControl Markets", "url": "https://www.moneycontrol.com/rss/marketreports.xml"},
]

# ==============================================================================
# 11. MODULE 6: SIGNAL LOGGING
# ==============================================================================
SIGNAL_LOG_DIR = "logs"
SIGNAL_LOG_FLUSH_TIME = "15:30:00"     # IST time to auto-flush daily CSV
SIGNAL_CSV_COLUMNS = [
    "timestamp", "signal_type", "spot_price", "pcr", "pcr_mood",
    "vwap", "ema20", "ema50", "ghost_zone", "oi_velocity_ce",
    "oi_velocity_pe", "momentum_alert", "news_alert",
    "max_favorable_move", "max_adverse_move"
]


