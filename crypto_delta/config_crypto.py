"""
Delta Exchange India - Hedging Strategy Configuration
"""

import os
from datetime import datetime

# ============================================================
# API CREDENTIALS
# ============================================================
API_KEY = "DbACPKTPtOnNdnE5bGOycFMJMoCkQU"
API_SECRET = "bSH9VobunFc43kfdtCnpGegGuNvTH85Phztzy44FMwtoo7xQXDHLi9MIaObE"
BASE_URL = "https://api.india.delta.exchange"

# ============================================================
# CAPITAL & RISK
# ============================================================
CAPITAL = 10.0  # $10 per trade
MAX_POSITIONS = 2  # Max 2 hedged positions at once
FEE_TAKER = 0.001  # 0.1%
FEE_MAKER = 0.0005  # 0.05%

# ============================================================
# HEDGING STRATEGY PARAMS
# ============================================================
# Strategy 1: Delta-Neutral Straddle
STRADDLE_DELTA_TOLERANCE = 0.1  # Keep delta between -0.1 and +0.1
STRADDLE_ENTRY_ZONE = 0.05  # Enter when |delta| < 0.05

# Strategy 2: Vertical Spread Hedge
SPREAD_WIDTH = 200  # $200 between strikes
SPREAD_MAX_LOSS = 50  # $50 max loss per spread

# Strategy 3: Dynamic Delta Hedge
HEDGE_REBALANCE_THRESHOLD = 0.15  # Rebalance when delta exceeds this
HEDGE_FREQUENCY = 300  # Check every 5 minutes

# ============================================================
# OPTION SELECTION
# ============================================================
MIN_DAYS_TO_EXPIRY = 0
MAX_DAYS_TO_EXPIRY = 2
MIN_BID_PRICE = 1.0  # Minimum option price
MAX_BID_PRICE = 8.0  # Max $8 per contract (leave room for hedge)

# ============================================================
# POSITION SIZING
# ============================================================
# For $10 capital with hedging:
# - Sell 1 ATM option (~$5-8)
# - Hedge with 1 OTM option (~$2-3) or small spot position
# - Or use 1 vertical spread (~$3-5)
SIZE_CALC_METHOD = "risk_based"  # 'risk_based' or 'fixed'

# ============================================================
# BACKTEST SETTINGS
# ============================================================
BACKTEST_START = "2026-05-01"
BACKTEST_END = "2026-07-20"
WALK_FORWARD_TRAIN = 20  # days
WALK_FORWARD_TEST = 5  # days

# ============================================================
# PATHS
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

for d in [DATA_DIR, RESULTS_DIR, LOGS_DIR]:
    os.makedirs(d, exist_ok=True)

# ============================================================
# LOGGING
# ============================================================
LOG_LEVEL = "INFO"
LOG_FILE = os.path.join(LOGS_DIR, f"crypto_{datetime.now().strftime('%Y%m%d')}.log")
