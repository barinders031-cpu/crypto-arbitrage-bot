"""
Unified Multi-Engine Arbitrage Platform
=========================================
Engine 1: Cross-Exchange Perpetual Funding Rate Arbitrage (Delta Exchange India vs CoinDCX / Binance)
           >> Full Live Automation: set LIVE_EXECUTION=true in env to place REAL orders on both exchanges.
Engine 2: Binance Dynamic All-BTC-Coins Triangular Arbitrage Engine ($10 Paper Trading Wallet & Live Telegram Feed)

Features:
1. Double-Section Web Dashboard on http://localhost:5050 (Scroll down to view Triangular Arbitrage).
2. Dynamic Discovery of ALL 100+ BTC Trading Pairs listed on Binance (ETH, SOL, XRP, BNB, ADA, DOGE, AVAX, LINK, DOT, LTC, etc.).
3. Real-time L2 Order Book Depth Walk (Top 10 Levels) for VWAP Slippage Calculation.
4. $10 Virtual Paper Balance with Real-time PnL tracking & Telegram Alerts.
5. Render 24/7 Keep-Alive Self-Ping Module.
6. Full Live Order Execution via LiveOrderExecutor (asyncio dual-leg, slippage gate, emergency close).
"""

import http.server
import socketserver
import urllib.request
import urllib.parse
import json
import datetime
import threading
import os
import sys
import asyncio
from dotenv import load_dotenv

load_dotenv()

# Live Order Executor — loads LIVE_EXECUTION flag from environment
try:
    from live_order_executor import get_executor, calculate_sizing, LIVE_EXECUTION, TOTAL_ROUNDTRIP_FEE_PCT as _LIVE_FEE_PCT
    _live_executor = get_executor()
except Exception as _live_import_err:
    print(f"[WARNING] live_order_executor import failed: {_live_import_err}. Running in paper mode.")
    LIVE_EXECUTION = False
    _live_executor = None

# Enforce UTF-8 encoding for Windows terminal compatibility
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

PORT = int(os.environ.get("PORT", 5050))
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_config.json")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state_persistent.json")

# Global In-Memory State
live_logs = []
paper_history = []

triangular_logs = []
triangular_history = []

# Live execution config from environment
MARGIN_PER_EXCHANGE_USD = float(os.getenv("MARGIN_PER_EXCHANGE_USD", "10"))

bot_state = {
    # Engine 1: Cross-Exchange Funding
    "status": "DUAL-LEG SAFEGUARD ACTIVE",
    "live_mode": "LIVE 🔴" if LIVE_EXECUTION else "PAPER 📄",
    "paper_wallet_balance": 10.0,
    "total_trades": 0,
    "net_pnl_usd": 0.0,
    "last_scan_time": "-",
    "active_top_coin": "-",
    "active_funding_diff": "0.0000%",
    "next_funding_countdown": "Calculating...",
    "top5_coins": [],
    "telegram_status": "Not Configured",
    
    # Engine 2: Binance All-BTC Pairs Triangular Arbitrage
    "triangular_status": "BINANCE L2 DEPTH SCANNER ACTIVE",
    "triangular_paper_balance": 10.0,  # $10 Paper Capital
    "triangular_scanned_count": 0,
    "triangular_last_scan": "-",
    "triangular_top_loop": "-",
    "triangular_top_exchange": "BINANCE",
    "triangular_top_net_pnl": "0.0000%",
    "triangular_top5": [],
    "triangular_total_trades": 0,
    "triangular_net_pnl_usd": 0.0
}

def save_persistent_state():
    try:
        data = {
            "paper_wallet_balance": bot_state.get("paper_wallet_balance", 10.0),
            "net_pnl_usd": bot_state.get("net_pnl_usd", 0.0),
            "total_trades": bot_state.get("total_trades", 0),
            "paper_history": paper_history,
            "triangular_paper_balance": bot_state.get("triangular_paper_balance", 10.0),
            "triangular_net_pnl_usd": bot_state.get("triangular_net_pnl_usd", 0.0),
            "triangular_total_trades": bot_state.get("triangular_total_trades", 0),
            "triangular_history": triangular_history
        }
        with open(STATE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving persistent state: {e}")

def load_persistent_state():
    global paper_history, triangular_history
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                bot_state["paper_wallet_balance"] = data.get("paper_wallet_balance", 10.0)
                bot_state["net_pnl_usd"] = data.get("net_pnl_usd", 0.0)
                bot_state["total_trades"] = data.get("total_trades", 0)
                bot_state["triangular_paper_balance"] = data.get("triangular_paper_balance", 10.0)
                bot_state["triangular_net_pnl_usd"] = data.get("triangular_net_pnl_usd", 0.0)
                bot_state["triangular_total_trades"] = data.get("triangular_total_trades", 0)
                
                if isinstance(data.get("paper_history"), list):
                    paper_history.clear()
                    paper_history.extend(data["paper_history"])
                if isinstance(data.get("triangular_history"), list):
                    triangular_history.clear()
                    triangular_history.extend(data["triangular_history"])
        except Exception as e:
            print(f"Error loading persistent state: {e}")

load_persistent_state()

def get_telegram_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
                if cfg.get("bot_token") and cfg.get("chat_id"):
                    return cfg
        except Exception:
            pass
    env_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    env_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    env_enabled = os.getenv("TELEGRAM_ENABLED", "true").lower() in ["true", "1", "yes"]
    if env_token:
        return {"bot_token": env_token, "chat_id": env_chat_id, "enabled": env_enabled}
    return {"bot_token": "", "chat_id": "", "enabled": False}

def auto_detect_chat_id(bot_token):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        res = urllib.request.urlopen(req, timeout=6)
        data = json.loads(res.read().decode())
        result = data.get('result', [])
        for update in reversed(result):
            if 'message' in update and 'chat' in update['message']:
                return str(update['message']['chat']['id'])
    except Exception:
        pass
    return ""

def send_telegram_alert(text):
    creds = get_telegram_config()
    token = creds.get("bot_token")
    chat_id = creds.get("chat_id")
    enabled = creds.get("enabled", False)

    if not enabled or not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        res = urllib.request.urlopen(req, timeout=5)
        return res.status == 200
    except Exception as e:
        add_log(f"Telegram alert error: {e}")
        return False

def fetch(url, timeout=6):
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        }
    )
    try:
        res = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(res.read().decode())
        if isinstance(data, dict) and 'result' in data:
            return data['result']
        return data
    except Exception:
        return []

def fetch_coindcx_binance_funding():
    """Fetches perpetual funding rates from Binance or global fallback exchanges (Gate.io / MEXC) when deployed on cloud hosts (e.g. Render US)."""
    # 1. Binance Direct
    data = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and 'lastFundingRate' in data[0]:
        return data

    # 2. Binance via Public AllOrigins Proxy
    data = fetch("https://api.allorigins.win/raw?url=https%3A%2F%2Ffapi.binance.com%2Ffapi%2Fv1%2FpremiumIndex")
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and 'lastFundingRate' in data[0]:
        return data

    # 3. Gate.io Futures Fallback
    gate_data = fetch("https://api.gateio.ws/api/v4/futures/usdt/tickers")
    if isinstance(gate_data, list) and len(gate_data) > 0:
        converted = []
        for item in gate_data:
            sym = item.get('name', '').replace('_', '')
            rate = item.get('funding_rate', '0')
            mark = item.get('mark_price', '0')
            converted.append({'symbol': sym, 'lastFundingRate': rate, 'markPrice': mark})
        return converted

    # 4. MEXC Futures Fallback
    mexc_resp = fetch("https://contract.mexc.com/api/v1/contract/ticker")
    items = mexc_resp.get('data', []) if isinstance(mexc_resp, dict) else []
    if isinstance(items, list) and len(items) > 0:
        converted = []
        for item in items:
            sym = item.get('symbol', '').replace('_', '')
            rate = item.get('fundingRate', 0)
            mark = item.get('fairPrice', 0)
            converted.append({'symbol': sym, 'lastFundingRate': rate, 'markPrice': mark})
        return converted

    return []

def fetch_delta_data():
    """Fetches product specs and tickers from Delta Exchange with fallback domain."""
    urls = [
        ("https://api.india.delta.exchange/v2/products", "https://api.india.delta.exchange/v2/tickers"),
        ("https://api.delta.exchange/v2/products", "https://api.delta.exchange/v2/tickers"),
    ]
    for p_url, t_url in urls:
        products = fetch(p_url)
        tickers  = fetch(t_url)
        if isinstance(products, list) and isinstance(tickers, list) and len(products) > 0 and len(tickers) > 0:
            return products, tickers
    return [], []

def add_log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    live_logs.append(entry)
    if len(live_logs) > 100:
        live_logs.pop(0)

def add_triangular_log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    triangular_logs.append(entry)
    if len(triangular_logs) > 100:
        triangular_logs.pop(0)


# ── Per-exchange max leverage tables (based on actual exchange limits) ──────────
# Delta Exchange India — perpetual max leverage per coin
DELTA_MAX_LEVERAGE = {
    "BTC":     100.0,
    "ETH":     100.0,
    "SOL":      50.0,
    "XRP":      50.0,
    "DOGE":     50.0,
    "BNB":      50.0,
    "1000SATS": 50.0,
    "ADA":      50.0,
    "AVAX":     50.0,
    "LINK":     50.0,
    "NEAR":     50.0,
    "SUI":      50.0,
    "PEPE":     50.0,
    "SHIB":     50.0,
    "WIF":      50.0,
    # Default for all other altcoins on Delta
    "_DEFAULT": 20.0,
}

# CoinDCX (Binance-backed) — perpetual max leverage per coin
COINDCX_MAX_LEVERAGE = {
    "BTC":     125.0,
    "ETH":     100.0,
    "SOL":      50.0,
    "XRP":      50.0,
    "DOGE":     50.0,
    "BNB":      75.0,
    "1000SATS": 20.0,
    "ADA":      75.0,
    "AVAX":     50.0,
    "LINK":     50.0,
    "NEAR":     50.0,
    "SUI":      50.0,
    "PEPE":     50.0,
    "SHIB":     50.0,
    "WIF":      50.0,
    # Default for all other altcoins on CoinDCX/Binance
    "_DEFAULT": 20.0,
}

def get_symmetric_leverage(coin: str) -> float:
    """
    Returns the SYMMETRIC (safe) leverage for both exchanges.

    Rule: Both legs MUST use the SAME leverage — always the MINIMUM of the
    two exchange max leverages. This guarantees exact notional matching and
    eliminates any margin imbalance between the two legs.

    Example: Delta max = 100x, CoinDCX max = 20x → Both sides use 20x.
    """
    c = coin.upper()
    delta_lev  = DELTA_MAX_LEVERAGE.get(c, DELTA_MAX_LEVERAGE["_DEFAULT"])
    cdcx_lev   = COINDCX_MAX_LEVERAGE.get(c, COINDCX_MAX_LEVERAGE["_DEFAULT"])
    effective  = min(delta_lev, cdcx_lev)
    return effective

# Legacy alias — kept for backward compatibility
def get_coin_max_leverage(coin):
    return get_symmetric_leverage(coin)


# ==============================================================================
# ENGINE 1: CROSS-EXCHANGE FUNDING RATE ARBITRAGE LOOP
# ==============================================================================
def bot_background_loop():
    global paper_history, bot_state
    
    margin = MARGIN_PER_EXCHANGE_USD  # Read from env (default $10)
    mode_str = "LIVE REAL-MONEY" if LIVE_EXECUTION else "PAPER VIRTUAL"
    add_log(f"Funding Engine Initialized — Mode: {mode_str} | Margin: ${margin:.2f}/exchange")
    if LIVE_EXECUTION:
        add_log("🔴 LIVE EXECUTION ACTIVE — Real orders will be placed on Delta & CoinDCX!")
    else:
        add_log("📄 Paper mode — set LIVE_EXECUTION=true in env to enable real order placement.")

    executed_windows = set()
    pending_exit = None
    last_valid_results = []
    retry_count = 0

    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
            now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")

            creds = get_telegram_config()
            bot_state["telegram_status"] = "Active 🟢" if creds.get("enabled") and creds.get("bot_token") else "Not Configured ⚪"

            # ── PHASE 1: Scalper Exit Check (T+2s after funding) ──
            if pending_exit:
                pe = pending_exit
                secs_after_funding = (now_utc - pe["funding_ts_utc"]).total_seconds()
                if secs_after_funding >= 2.0:
                    coin    = pe["coin"]
                    top     = pe["top"]
                    lev     = pe["coin_lev"]
                    notl    = pe["coin_notional"]
                    diff    = pe["diff"]

                    # ── Live Exit ──────────────────────────────────────
                    if LIVE_EXECUTION and _live_executor and pe.get("live_entry_success"):
                        try:
                            exit_result = asyncio.run(_live_executor.execute_exit(
                                delta_sym       = pe["delta_sym"],
                                delta_side      = pe["delta_side"],
                                delta_lots      = pe["delta_lots"],
                                coindcx_sym     = pe["coindcx_sym"],
                                coindcx_side    = pe["coindcx_side"],
                                exact_qty       = pe["exact_qty"],
                                leverage        = int(lev),
                                notional_usd    = notl,
                                gross_spread_pct= diff,
                                trigger_reason  = f"Scalper Exit T+{secs_after_funding:.1f}s",
                            ))
                            net   = exit_result.get("net_pnl_usd", pe["net_pnl"])
                            gross = exit_result.get("gross_usd",   pe["gross_funding"])
                            fee   = exit_result.get("fees_usd",    pe["coin_fee"])
                            live_tag = "🔴 LIVE"
                        except Exception as _ex:
                            add_log(f"❌ Live exit error: {_ex} — falling back to paper PnL")
                            net   = pe["net_pnl"]
                            gross = pe["gross_funding"]
                            fee   = pe["coin_fee"]
                            live_tag = "📄 PAPER (exit err)"
                    else:
                        # ── Paper Exit ─────────────────────────────────
                        net   = pe["net_pnl"]
                        gross = pe["gross_funding"]
                        fee   = pe["coin_fee"]
                        live_tag = "📄 PAPER"

                    bot_state["paper_wallet_balance"] += net
                    bot_state["net_pnl_usd"]          += net
                    bot_state["total_trades"]          += 1

                    trade_entry = {
                        "id":         bot_state["total_trades"],
                        "timestamp":  now_str,
                        "coin":       coin,
                        "gross_income": f"+${gross:.4f}",
                        "fees":         f"-${fee:.4f}",
                        "net_pnl":      f"+${net:.4f}",
                        "balance":      f"${bot_state['paper_wallet_balance']:.2f}"
                    }
                    paper_history.insert(0, trade_entry)
                    save_persistent_state()

                    add_log(f"⚡ [{live_tag} EXIT T+{secs_after_funding:.1f}s] {coin} | Gross +${gross:.4f} | Fees -${fee:.4f} | NET +${net:.4f}")

                    tg_msg = (
                        f"🚨 *PRECISION TIMED ARBITRAGE COMPLETE* 🚀\n\n"
                        f"🪙 *Coin:* `{coin}`\n"
                        f"📊 *Strategy:* `{top['action']}`\n"
                        f"⏱️ *Timing:* `Entry T-1min → Snapshot T+0s → Scalper Exit T+{secs_after_funding:.1f}s`\n"
                        f"⚙️ *Margin & Leverage:* `${margin:.2f} @ {lev:.0f}x (${notl:.0f} Notional/leg)`\n"
                        f"⚡ *Spread:* `{diff:.4f}%`\n"
                        f"🏷️ *Mode:* `{live_tag}`\n\n"
                        f"💵 *Gross Funding:* `+${gross:.4f} USD`\n"
                        f"🏷️ *Roundtrip Fees:* `-${fee:.4f} USD`\n"
                        f"📈 *NET CASH PROFIT:* `+${net:.4f} USD`\n"
                        f"💰 *New Balance:* `${bot_state['paper_wallet_balance']:.2f} USD`"
                    )
                    send_telegram_alert(tg_msg)
                    pending_exit = None
                else:
                    add_log(f"🔒 [FUNDING SNAPSHOT LOCKED] Waiting for T+2s scalper exit... ({secs_after_funding:.1f}s elapsed)")
                    time.sleep(0.5)
                    continue

            # ── PHASE 2: Fetch Live Real Account Balances & Rates ──
            if _live_executor:
                try:
                    _d_bal, _c_bal, _tot_bal = asyncio.run(_live_executor.fetch_live_balances())
                    bot_state["real_balance_display"] = f"Delta: ${_d_bal:.2f} | CoinDCX: ${_c_bal:.2f} | Total: ${_tot_bal:.2f}"
                    bot_state["delta_balance"] = _d_bal
                    bot_state["coindcx_balance"] = _c_bal
                    bot_state["paper_wallet_balance"] = _tot_bal
                except Exception as _bal_err:
                    pass

            delta_products, delta_tickers = fetch_delta_data()

            delta_interval = {}
            for p in delta_products:
                sym  = p.get('symbol', '')
                specs = p.get('product_specs') or {}
                rei   = specs.get('rate_exchange_interval')
                delta_interval[sym] = int(rei) / 3600.0 if rei else 8.0

            delta_map = {}
            for t in delta_tickers:
                if 'perpetual' in t.get('contract_type', ''):
                    sym      = t.get('symbol', '')
                    rate_pct = float(t.get('funding_rate') or 0)
                    mark     = float(t.get('mark_price') or 0)
                    if sym.endswith('USDT'):
                        coin = sym[:-4]
                    elif sym.endswith('USD'):
                        coin = sym[:-3]
                    else:
                        coin = sym
                    h        = delta_interval.get(sym, 8.0)
                    delta_map[coin] = {'rate': rate_pct, 'h': h, 'sym': sym, 'mark': mark}

            binance_funding = fetch_coindcx_binance_funding()
            binance_map = {}
            coindcx_map = {}
            for b in binance_funding:
                sym = b.get('symbol', '')
                if sym.endswith('USDT'):
                    coin     = sym[:-4]
                    rate_pct = float(b.get('lastFundingRate') or 0) * 100.0
                    mark     = float(b.get('markPrice') or 0)
                    binance_map[coin] = {'rate': rate_pct, 'sym': sym, 'mark': mark}
                    coindcx_map[coin] = {'rate': rate_pct, 'h': 8.0, 'sym': f"B-{sym}", 'mark': mark}

            results = []
            for coin, d in delta_map.items():
                if coin not in coindcx_map:
                    continue
                c      = coindcx_map[coin]
                b_item = binance_map.get(coin, c)
                r_d, r_c, r_b = d['rate'], c['rate'], b_item['rate']

                pairs = [
                    (abs(r_d - r_c), "Delta vs CoinDCX", f"SHORT Delta + LONG CoinDCX" if r_d >= r_c else "LONG Delta + SHORT CoinDCX"),
                    (abs(r_d - r_b), "Delta vs Binance",  f"SHORT Delta + LONG Binance"  if r_d >= r_b else "LONG Delta + SHORT Binance"),
                    (abs(r_b - r_c), "Binance vs CoinDCX",f"SHORT Binance + LONG CoinDCX" if r_b >= r_c else "LONG Binance + SHORT CoinDCX"),
                ]
                pairs.sort(key=lambda x: x[0], reverse=True)
                best_diff, _, best_action = pairs[0]

                h_coin = d['h']
                h_int  = int(h_coin)
                next_settlement_h_utc = ((now_utc.hour // h_int) + 1) * h_int
                overflow_days = 0
                if next_settlement_h_utc >= 24:
                    next_settlement_h_utc -= 24
                    overflow_days = 1
                funding_ts_utc = now_utc.replace(
                    hour=next_settlement_h_utc, minute=0, second=0, microsecond=0
                ) + datetime.timedelta(days=overflow_days)
                if funding_ts_utc <= now_utc:
                    funding_ts_utc += datetime.timedelta(hours=h_int)

                mins_left = int((funding_ts_utc - now_utc).total_seconds() // 60)
                secs_left = int((funding_ts_utc - now_utc).total_seconds())
                target_ist = funding_ts_utc + datetime.timedelta(hours=5, minutes=30)
                time_label = target_ist.strftime("%H:%M IST")

                if mins_left <= 2:
                    timing_label = f"🔴 NOW! {time_label}"
                elif mins_left <= 10:
                    timing_label = f"🟡 {mins_left}m → {time_label}"
                else:
                    timing_label = f"🟢 {mins_left}m → {time_label}"

                results.append({
                    'coin':        coin,
                    'delta_sym':   d['sym'],
                    'delta_rate':  f"{d['rate']:+.4f}% ({h_coin:.0f}H)",
                    'delta_mark':  d['mark'],
                    'binance_sym': b_item['sym'],
                    'binance_rate':f"{b_item['rate']:+.4f}%",
                    'cdcx_sym':    c['sym'],
                    'cdcx_rate':   f"{c['rate']:+.4f}% ({c['h']:.0f}H)",
                    'cdcx_mark':   c['mark'],
                    'raw_diff_num':best_diff,
                    'diff':        f"{best_diff:.4f}%",
                    'action':      best_action,
                    'next_funding':timing_label,
                    'mins_left':   mins_left,
                    'secs_left':   secs_left,
                    'funding_ts_utc': funding_ts_utc.strftime("%Y-%m-%d %H:%M:%S"),
                    'funding_ts_obj': funding_ts_utc,
                    'h_coin':      h_coin,
                })

            if results:
                last_valid_results = results
                retry_count = 0
            elif last_valid_results:
                results = last_valid_results
                retry_count += 1
                if retry_count % 30 == 1:
                    add_log("ℹ️ Network fallback active: Using cached funding rates while retrying live fetch...")
            else:
                retry_count += 1
                if retry_count % 10 == 1:
                    add_log("⚠️ Scanning exchange funding rates... Retrying...")
                time.sleep(3)
                continue

            results.sort(key=lambda x: x['raw_diff_num'], reverse=True)
            clean_top5 = []
            for r in results[:5]:
                item_copy = dict(r)
                item_copy.pop('funding_ts_obj', None)
                clean_top5.append(item_copy)

            bot_state["top5_coins"] = clean_top5
            bot_state["total_scanned_coins"] = len(results)

            top   = results[0]
            coin  = top['coin']
            diff  = top['raw_diff_num']
            secs  = top['secs_left']
            funding_ts_utc = top['funding_ts_obj']

            coin_lev      = get_coin_max_leverage(coin)
            coin_notional = margin * coin_lev
            coin_fee      = coin_notional * (0.1416 / 100.0)
            gross_funding = coin_notional * (diff / 100.0)
            net_pnl       = gross_funding - coin_fee

            bot_state["last_scan_time"]       = now_str
            bot_state["active_top_coin"]      = coin
            bot_state["active_funding_diff"]  = f"{diff:.4f}%"
            target_ist_str = (funding_ts_utc + datetime.timedelta(hours=5, minutes=30)).strftime("%H:%M IST")
            bot_state["next_funding_countdown"] = f"{top['mins_left']}m {secs % 60}s to funding ({target_ist_str})"

            funding_window_key = f"{coin}_{funding_ts_utc.strftime('%Y%m%d%H%M')}"
            is_entry_window    = 60 <= secs <= 120
            already_executed   = funding_window_key in executed_windows

            cutoff = now_utc - datetime.timedelta(hours=2)
            executed_windows = {k for k in executed_windows
                                if datetime.datetime.strptime(k.split('_')[1], '%Y%m%d%H%M')
                                   .replace(tzinfo=None) > cutoff}

            if is_entry_window and not already_executed:
                if net_pnl > 0:
                    # ── Determine exact lots & quantities via sizing protocol ──
                    delta_sym    = top.get('delta_sym', f"{coin}USD")
                    cdcx_sym     = top.get('cdcx_sym',  f"B-{coin}_USDT")
                    delta_action = top.get('action', '')
                    delta_side   = "sell" if "SHORT Delta" in delta_action else "buy"
                    cdcx_side    = "buy"  if "LONG CoinDCX" in delta_action else "sell"
                    mark_price   = float(top.get('delta_mark') or top.get('cdcx_mark') or 1.0)

                    # Universal Base Asset Quantity Sizing (AGENTS.md Rule 8)
                    from live_order_executor import calculate_sizing as _cs
                    lots, exact_qty, actual_notional = _cs(coin, mark_price, coin_notional)

                    # Log symmetric leverage breakdown
                    _d_lev = DELTA_MAX_LEVERAGE.get(coin.upper(), DELTA_MAX_LEVERAGE["_DEFAULT"])
                    _c_lev = COINDCX_MAX_LEVERAGE.get(coin.upper(), COINDCX_MAX_LEVERAGE["_DEFAULT"])
                    add_log(f"⚡ [ENTRY T-{secs}s] {'🔴 LIVE' if LIVE_EXECUTION else '📄 PAPER'} — {coin} {delta_side.upper()} {lots}Lots | CoinDCX {cdcx_side.upper()} {exact_qty} | ${actual_notional:.2f} notional")
                    add_log(f"   Leverage: Delta_max={_d_lev:.0f}x | CoinDCX_max={_c_lev:.0f}x → Effective SYMMETRIC={coin_lev:.0f}x (both legs)")
                    add_log(f"   Delta: {top['delta_rate']} | CoinDCX: {top['cdcx_rate']} | Spread: {diff:.4f}%")

                    # ── Live Entry ──────────────────────────────────────────
                    live_entry_success = False
                    if LIVE_EXECUTION and _live_executor:
                        try:
                            entry_result = asyncio.run(_live_executor.execute_entry(
                                delta_sym       = delta_sym,
                                delta_side      = delta_side,
                                delta_lots      = lots,
                                coindcx_sym     = cdcx_sym,
                                coindcx_side    = cdcx_side,
                                exact_qty       = exact_qty,
                                leverage        = int(coin_lev),
                                coin            = coin,
                                mark_delta      = mark_price,
                                mark_coindcx    = float(top.get('cdcx_mark') or mark_price),
                                notional_usd    = actual_notional,
                                gross_spread_pct= diff,
                            ))
                            st = entry_result.get("status")
                            if st in ("SUCCESS_LIVE", "PAPER"):
                                live_entry_success = True
                                add_log(f"   ✅ Entry filled: Delta order_id={entry_result.get('delta_order_id')} | CoinDCX order_id={entry_result.get('coindcx_order_id')} | Latency={entry_result.get('latency_ms', 0):.0f}ms")
                            elif st == "ABORTED_SPREAD_GATE":
                                add_log(f"   ⛔ Entry ABORTED — {entry_result.get('reason')}")
                                executed_windows.add(funding_window_key)
                                continue
                            elif st == "ABORTED_FUNDING_COLLAPSE":
                                add_log(f"   ⛔ Entry ABORTED — Funding rate collapsed before T-0s (Current={entry_result.get('current_spread',0):.4f}%)")
                                executed_windows.add(funding_window_key)
                                continue
                            elif st == "ABORTED_HEALTH_CHECK":
                                add_log(f"   ⛔ Entry ABORTED — Pre-flight health check failed ({entry_result.get('reason')})")
                                executed_windows.add(funding_window_key)
                                continue
                            elif st == "DELTA_LIMIT_TIMEOUT_EXPIRED":
                                add_log(f"   ⏱️ SOR Limit Order on Delta did not fill before T-15s. Order cancelled safely with ZERO loss.")
                                executed_windows.add(funding_window_key)
                                continue
                            elif st in ("DELTA_MAKER_FAILED", "DELTA_LIMIT_CANCELLED"):
                                add_log(f"   ⛔ SOR Entry ABORTED — Delta limit order was not placed or cancelled ({entry_result.get('reason', st)})")
                                executed_windows.add(funding_window_key)
                                continue
                            elif st in ("DELTA_FAILED_EMERGENCY_CLOSED", "COINDCX_FAILED_EMERGENCY_CLOSED"):
                                add_log(f"   🚨 EMERGENCY ROLLBACK TRIGGERED — One leg failed to fill, opposite leg closed in <500ms to preserve neutrality.")
                                executed_windows.add(funding_window_key)
                                continue
                            else:
                                add_log(f"   ❌ Entry FAILED: {st}")
                        except Exception as _ex:
                            add_log(f"   ❌ Live entry exception: {_ex}")
                    else:
                        live_entry_success = False  # Paper mode

                    tg_entry = (
                        f"⚡ *ENTRY FIRED — T-{secs}s BEFORE FUNDING*\n\n"
                        f"🪙 *Coin:* `{coin}`\n"
                        f"📊 *Strategy:* `{top['action']}`\n"
                        f"🏷️ *Mode:* `{'🔴 LIVE REAL-MONEY' if LIVE_EXECUTION else '📄 Paper Virtual'}`\n"
                        f"⚙️ *Leverage:* `{coin_lev:.0f}x | ${actual_notional:.0f} Notional/leg`\n"
                        f"📦 *Sizing:* `{lots} Lots Delta | {exact_qty} {coin} CoinDCX`\n"
                        f"⚡ *Spread:* `{diff:.4f}%`\n"
                        f"🕐 *Funding in:* `{secs}s`\n\n"
                        f"💵 *Expected Gross:* `+${gross_funding:.4f}`\n"
                        f"🏷️ *Expected Fees:* `-${coin_fee:.4f}`\n"
                        f"📈 *Expected NET:* `+${net_pnl:.4f} USD`"
                    )
                    send_telegram_alert(tg_entry)
                    executed_windows.add(funding_window_key)

                    pending_exit = {
                        "coin":          coin,
                        "top":           top,
                        "gross_funding": gross_funding,
                        "coin_fee":      coin_fee,
                        "net_pnl":       net_pnl,
                        "coin_lev":      coin_lev,
                        "coin_notional": actual_notional,
                        "diff":          diff,
                        "funding_ts_utc": funding_ts_utc,
                        "entry_time":    now_utc,
                        # Live order metadata
                        "live_entry_success": live_entry_success,
                        "delta_sym":     delta_sym,
                        "cdcx_sym":      cdcx_sym,
                        "coindcx_sym":   cdcx_sym,
                        "delta_side":    delta_side,
                        "coindcx_side":  cdcx_side,
                        "delta_lots":    lots,
                        "exact_qty":     exact_qty,
                    }
                else:
                    add_log(f"⚠️ [{coin} T-{secs}s] SKIP — Net PnL (${net_pnl:.4f}) negative after fees.")
                    executed_windows.add(funding_window_key)

            elif already_executed:
                pass
            else:
                pass

        except Exception as e:
            add_log(f"❌ Error in funding bot loop: {e}")

        time.sleep(1)


# ==============================================================================
# ENGINE 2: BINANCE EXCLUSIVE DYNAMIC ALL-BTC-COINS TRIANGULAR ARBITRAGE
# ==============================================================================

def simulate_orderbook_buy(asks, capital_usdt):
    remaining = capital_usdt
    total_base = 0.0
    weighted_cost = 0.0
    if not asks:
        return 0.0, 0.0, 0.0
    top_price = float(asks[0][0])
    for price_str, qty_str in asks[:10]:
        price, qty = float(price_str), float(qty_str)
        level_val = price * qty
        if remaining <= level_val:
            total_base += (remaining / price)
            weighted_cost += remaining
            remaining = 0.0
            break
        else:
            total_base += qty
            weighted_cost += level_val
            remaining -= level_val
    if total_base == 0:
        return 0.0, 0.0, 0.0
    vwap = weighted_cost / total_base
    ideal_cost = total_base * top_price
    slippage = max(0.0, weighted_cost - ideal_cost)
    return total_base, vwap, slippage

def simulate_orderbook_sell(bids, base_qty):
    remaining = base_qty
    total_quote = 0.0
    if not bids:
        return 0.0, 0.0, 0.0
    top_price = float(bids[0][0])
    for price_str, qty_str in bids[:10]:
        price, qty = float(price_str), float(qty_str)
        if remaining <= qty:
            total_quote += remaining * price
            remaining = 0.0
            break
        else:
            total_quote += qty * price
            remaining -= qty
    if base_qty == 0:
        return 0.0, 0.0, 0.0
    vwap = total_quote / base_qty
    ideal_quote = base_qty * top_price
    slippage = max(0.0, ideal_quote - total_quote)
    return total_quote, vwap, slippage

def discover_binance_btc_triangular_loops():
    """Dynamically fetches all trading symbols from Binance and discovers all valid 3-pair loops involving BTC & USDT."""
    try:
        ex_info = fetch("https://api.binance.com/api/v3/exchangeInfo")
        if not isinstance(ex_info, dict):
            ex_info = {}
        symbols = ex_info.get("symbols", [])
        if not isinstance(symbols, list):
            symbols = []
        
        all_trading_symbols = {s.get("symbol") for s in symbols if isinstance(s, dict) and s.get("status") == "TRADING"}

        # Find all coins X that have both XBTC and XUSDT pairs on Binance
        btc_coins = []
        for s in symbols:
            if not isinstance(s, dict):
                continue
            sym = s.get("symbol", "")
            if sym.endswith("BTC") and s.get("status") == "TRADING":
                coin = sym[:-3]  # Strip "BTC"
                if coin != "USDT" and f"{coin}USDT" in all_trading_symbols:
                    btc_coins.append(coin)

        if btc_coins:
            return sorted(list(set(btc_coins)))
    except Exception as e:
        add_triangular_log(f"⚠️ Error discovering Binance BTC pairs: {e}")

    return ["ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX", "LINK", "DOT", "LTC", "MATIC", "NEAR", "SHIB"]

def evaluate_binance_triangular_loop(coin, capital_usdt=10.0):
    """
    Evaluates both Forward and Reverse Triangular Loops on Binance for a given coin X (e.g. ETH, SOL, XRP):
      Forward:  USDT -> BUY XUSDT -> SELL XBTC for BTC -> SELL BTCUSDT for USDT
      Reverse:  USDT -> BUY BTCUSDT -> BUY XBTC with BTC -> SELL XUSDT for USDT
    """
    try:
        sym_xusdt = f"{coin}USDT"
        sym_xbtc  = f"{coin}BTC"
        sym_btcusdt = "BTCUSDT"

        # Fetch L2 Depth for all 3 pairs
        ob_xusdt = fetch(f"https://api.binance.com/api/v3/depth?symbol={sym_xusdt}&limit=10")
        ob_xbtc  = fetch(f"https://api.binance.com/api/v3/depth?symbol={sym_xbtc}&limit=10")
        ob_btcusdt = fetch(f"https://api.binance.com/api/v3/depth?symbol={sym_btcusdt}&limit=10")

        if not isinstance(ob_xusdt, dict) or not isinstance(ob_xbtc, dict) or not isinstance(ob_btcusdt, dict):
            return None

        asks_xusdt = ob_xusdt.get("asks", [])
        bids_xbtc   = ob_xbtc.get("bids", [])
        asks_xbtc   = ob_xbtc.get("asks", [])
        bids_btcusdt= ob_btcusdt.get("bids", [])
        asks_btcusdt= ob_btcusdt.get("asks", [])

        if not asks_xusdt or not bids_xbtc or not bids_btcusdt or not asks_btcusdt or not asks_xbtc:
            return None

        taker_fee = 0.0010  # 0.10% Binance default taker fee

        # ── OPTION A: FORWARD LOOP (USDT -> COIN -> BTC -> USDT) ──
        # Step 1: BUY COIN on XUSDT
        qty_x, p1_fwd, slip1_fwd = simulate_orderbook_buy(asks_xusdt, capital_usdt)
        if qty_x == 0: return None
        fee1_fwd = capital_usdt * taker_fee
        qty_x_net = qty_x * (1.0 - taker_fee)

        # Step 2: SELL COIN for BTC on XBTC
        qty_btc, p2_fwd, slip2_fwd = simulate_orderbook_sell(bids_xbtc, qty_x_net)
        if qty_btc == 0: return None
        btc_mark_price = float(bids_btcusdt[0][0])
        fee2_fwd = (qty_btc * btc_mark_price) * taker_fee
        qty_btc_net = qty_btc * (1.0 - taker_fee)

        # Step 3: SELL BTC for USDT on BTCUSDT
        final_usdt_fwd, p3_fwd, slip3_fwd = simulate_orderbook_sell(bids_btcusdt, qty_btc_net)
        if final_usdt_fwd == 0: return None
        fee3_fwd = final_usdt_fwd * taker_fee
        final_net_usdt_fwd = final_usdt_fwd * (1.0 - taker_fee)

        total_fees_fwd = fee1_fwd + fee2_fwd + fee3_fwd
        total_slip_fwd = slip1_fwd + slip2_fwd + slip3_fwd
        net_pnl_usd_fwd = final_net_usdt_fwd - capital_usdt
        net_pnl_pct_fwd = (net_pnl_usd_fwd / capital_usdt) * 100.0

        res_fwd = {
            "loop_type": "FORWARD",
            "coin": coin,
            "label": f"USDT → {coin} → BTC → USDT",
            "exchange": "BINANCE",
            "capital": capital_usdt,
            "step1": f"BUY {coin} @ ${p1_fwd:.4f}",
            "step2": f"SELL {coin} on {sym_xbtc} @ {p2_fwd:.8f}",
            "step3": f"SELL BTC @ ${p3_fwd:.2f}",
            "final_usdt": final_net_usdt_fwd,
            "total_fees": total_fees_fwd,
            "total_slip": total_slip_fwd,
            "net_pnl_usd": net_pnl_usd_fwd,
            "net_pnl_pct_num": net_pnl_pct_fwd,
            "net_pnl_pct": f"{net_pnl_pct_fwd:+.3f}%"
        }

        # ── OPTION B: REVERSE LOOP (USDT -> BTC -> COIN -> USDT) ──
        # Step 1: BUY BTC on BTCUSDT
        qty_btc_rev, p1_rev, slip1_rev = simulate_orderbook_buy(asks_btcusdt, capital_usdt)
        if qty_btc_rev == 0: return None
        fee1_rev = capital_usdt * taker_fee
        qty_btc_net_rev = qty_btc_rev * (1.0 - taker_fee)

        # Step 2: BUY COIN using BTC on XBTC
        qty_x_rev, p2_rev, slip2_rev = simulate_orderbook_buy(asks_xbtc, qty_btc_net_rev)
        if qty_x_rev == 0: return None
        fee2_rev = (qty_btc_net_rev * btc_mark_price) * taker_fee
        qty_x_net_rev = qty_x_rev * (1.0 - taker_fee)

        # Step 3: SELL COIN for USDT on XUSDT
        final_usdt_rev, p3_rev, slip3_rev = simulate_orderbook_sell(ob_xusdt.get("bids", []), qty_x_net_rev)
        if final_usdt_rev == 0: return None
        fee3_rev = final_usdt_rev * taker_fee
        final_net_usdt_rev = final_usdt_rev * (1.0 - taker_fee)

        total_fees_rev = fee1_rev + fee2_rev + fee3_rev
        total_slip_rev = slip1_rev + slip2_rev + slip3_rev
        net_pnl_usd_rev = final_net_usdt_rev - capital_usdt
        net_pnl_pct_rev = (net_pnl_usd_rev / capital_usdt) * 100.0

        res_rev = {
            "loop_type": "REVERSE",
            "coin": coin,
            "label": f"USDT → BTC → {coin} → USDT",
            "exchange": "BINANCE",
            "capital": capital_usdt,
            "step1": f"BUY BTC @ ${p1_rev:.2f}",
            "step2": f"BUY {coin} on {sym_xbtc} @ {p2_rev:.8f}",
            "step3": f"SELL {coin} @ ${p3_rev:.4f}",
            "final_usdt": final_net_usdt_rev,
            "total_fees": total_fees_rev,
            "total_slip": total_slip_rev,
            "net_pnl_usd": net_pnl_usd_rev,
            "net_pnl_pct_num": net_pnl_pct_rev,
            "net_pnl_pct": f"{net_pnl_pct_rev:+.3f}%"
        }

        # Return the best loop option (Forward or Reverse)
        return res_fwd if res_fwd["net_pnl_pct_num"] >= res_rev["net_pnl_pct_num"] else res_rev
    except Exception:
        return None


def triangular_background_loop():
    global triangular_history, bot_state
    add_triangular_log("Binance Dynamic All-BTC Pairs Engine Active ($10 Virtual Wallet).")
    
    # Discover all Binance BTC trading coins dynamically on startup
    btc_coins = discover_binance_btc_triangular_loops()
    add_triangular_log(f"🌐 Dynamic Discovery Complete: Found {len(btc_coins)} Active BTC Trading Pairs on Binance!")

    last_discovery_time = time.time()

    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
            now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")

            # Refresh list of active BTC coins every 30 minutes
            if time.time() - last_discovery_time > 1800:
                btc_coins = discover_binance_btc_triangular_loops()
                last_discovery_time = time.time()

            capital = bot_state["triangular_paper_balance"]
            all_results = []

            # Scan all BTC coins on Binance
            for coin in btc_coins:
                res = evaluate_binance_triangular_loop(coin, capital_usdt=capital)
                if res:
                    all_results.append(res)

            all_results.sort(key=lambda x: x["net_pnl_pct_num"], reverse=True)

            bot_state["triangular_scanned_count"] = len(btc_coins)
            bot_state["triangular_last_scan"] = now_str
            bot_state["triangular_top5"] = all_results[:5]

            if all_results:
                top = all_results[0]
                bot_state["triangular_top_loop"] = top["label"]
                bot_state["triangular_top_exchange"] = "BINANCE"
                bot_state["triangular_top_net_pnl"] = top["net_pnl_pct"]

                # Auto execution gate if Net PnL % >= +0.10%
                if top["net_pnl_pct_num"] >= 0.10:
                    net_usd = top["net_pnl_usd"]
                    bot_state["triangular_paper_balance"] += net_usd
                    bot_state["triangular_net_pnl_usd"]    += net_usd
                    bot_state["triangular_total_trades"]    += 1

                    trade_entry = {
                        "id": bot_state["triangular_total_trades"],
                        "timestamp": now_str,
                        "loop": top["label"],
                        "exchange": "BINANCE",
                        "fees": f"-${top['total_fees']:.4f}",
                        "slippage": f"-${top['total_slip']:.4f}",
                        "net_pnl": f"{top['net_pnl_pct']} (${net_usd:+.4f})",
                        "balance": f"${bot_state['triangular_paper_balance']:.4f}"
                    }
                    triangular_history.insert(0, trade_entry)
                    save_persistent_state()

                    add_triangular_log(f"🔺 [BINANCE TRIANGULAR EXECUTION] {top['label']} | NET: {top['net_pnl_pct']} (${net_usd:+.4f}) | New Balance: ${bot_state['triangular_paper_balance']:.4f}")
                    
                    tg_msg = (
                        f"🔺 *BINANCE REAL-TIME TRIANGULAR ARBITRAGE COMPLETE* 🚀\n\n"
                        f"🔄 *Loop:* `{top['label']}`\n"
                        f"🏛️ *Exchange:* `BINANCE SPOT`\n"
                        f"💵 *Trade Capital:* `${capital:.2f} USDT`\n"
                        f"🏷️ *Total Fees Cut:* `-${top['total_fees']:.4f} USD`\n"
                        f"⚡ *Slippage Impact:* `-${top['total_slip']:.4f} USD`\n\n"
                        f"📈 *NET CASH PROFIT:* `{top['net_pnl_pct']} (${net_usd:+.4f} USD)`\n"
                        f"💰 *UPDATED VIRTUAL BALANCE:* `${bot_state['triangular_paper_balance']:.4f} USD`\n"
                        f"📊 *Total Net PnL:* `${bot_state['triangular_net_pnl_usd']:+.4f} USD`"
                    )
                    send_telegram_alert(tg_msg)

        except Exception as e:
            add_triangular_log(f"⚠️ Error in Binance triangular loop: {e}")

        time.sleep(3)

def self_ping_loop():
    time.sleep(30)
    while True:
        external_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SELF_PING_URL")
        if external_url:
            target_url = f"{external_url.rstrip('/')}/ping"
            try:
                req = urllib.request.Request(target_url, headers={'User-Agent': 'Mozilla/5.0 SelfPinger'})
                with urllib.request.urlopen(req, timeout=10) as res:
                    if res.status == 200:
                        add_log("🟢 [24/7 KEEP-ALIVE] Render Self-Ping Successful (Server Awake).")
            except Exception as e:
                add_log(f"⚠️ [24/7 KEEP-ALIVE] Self-Ping check: {e}")
        time.sleep(240)

# Start all background workers
threading.Thread(target=bot_background_loop, daemon=True).start()
threading.Thread(target=triangular_background_loop, daemon=True).start()
threading.Thread(target=self_ping_loop, daemon=True).start()

# ==============================================================================
# WEB DASHBOARD FRONTEND (DUAL ENGINE LAYOUT)
# ==============================================================================
HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <title>Multi-Exchange Arbitrage Terminal</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #090d16;
            --card-bg: rgba(18, 26, 42, 0.75);
            --border: rgba(255, 255, 255, 0.08);
            --accent-blue: #3b82f6;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-yellow: #f59e0b;
            --accent-cyan: #06b6d4;
            --accent-purple: #8b5cf6;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            background-color: var(--bg);
            color: var(--text-main);
            font-family: 'Outfit', sans-serif;
            padding: 20px;
            min-height: 100vh;
            line-height: 1.5;
        }

        .container { max-width: 1450px; margin: 0 auto; }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 25px;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 14px;
            margin-bottom: 20px;
            backdrop-filter: blur(10px);
        }

        .header-title h1 {
            font-size: 22px;
            font-weight: 700;
            background: linear-gradient(135deg, #60a5fa, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .header-title p {
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 2px;
        }

        .telegram-widget {
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(255, 255, 255, 0.03);
            padding: 8px 14px;
            border-radius: 10px;
            border: 1px solid var(--border);
        }

        .telegram-widget input {
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid var(--border);
            color: #fff;
            padding: 6px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-family: 'JetBrains Mono', monospace;
            width: 140px;
        }

        .btn-tg {
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            font-size: 12px;
            transition: all 0.2s;
        }

        .btn-tg:hover { opacity: 0.9; transform: translateY(-1px); }

        .grid-4 {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            padding: 18px;
            border-radius: 12px;
            backdrop-filter: blur(10px);
        }

        .card-label {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }

        .card-val {
            font-size: 24px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }

        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .section-title {
            font-size: 16px;
            font-weight: 600;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .table-container {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 25px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }

        th {
            background: rgba(255, 255, 255, 0.02);
            padding: 12px 16px;
            font-size: 11px;
            text-transform: uppercase;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border);
        }

        td {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
            font-size: 13px;
        }

        tr:last-child td { border-bottom: none; }
        tr:hover td { background: rgba(255, 255, 255, 0.02); }

        .text-green { color: var(--accent-green); }
        .text-red { color: var(--accent-red); }
        .text-yellow { color: var(--accent-yellow); }
        .text-cyan { color: var(--accent-cyan); }
        .text-purple { color: var(--accent-purple); }

        .badge-action {
            background: rgba(16, 185, 129, 0.15);
            color: var(--accent-green);
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        .badge-ex {
            background: rgba(59, 130, 246, 0.15);
            color: var(--accent-blue);
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
        }

        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 25px;
        }

        .log-box {
            background: rgba(5, 8, 15, 0.9);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 15px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            height: 250px;
            overflow-y: auto;
            color: #d1d5db;
        }

        .log-entry { margin-bottom: 5px; line-height: 1.4; border-bottom: 1px solid rgba(255,255,255,0.02); padding-bottom: 3px; }

        .section-divider {
            border: 0;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(59, 130, 246, 0.5), transparent);
            margin: 35px 0;
        }

        .engine-tag {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
            margin-left: 8px;
        }

        .tag-funding { background: rgba(16, 185, 129, 0.2); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); }
        .tag-triangular { background: rgba(139, 92, 246, 0.2); color: var(--accent-purple); border: 1px solid rgba(139, 92, 246, 0.3); }
    </style>
</head>
<body>

    <div class="container">
        <!-- HEADER -->
        <div class="header">
            <div class="header-title">
                <h1>MULTI-ENGINE ARBITRAGE TERMINAL</h1>
                <p>Cross-Exchange Funding Rates & Binance Dynamic All-BTC Pairs Triangular Arbitrage</p>
            </div>

            <div class="telegram-widget">
                <span style="font-size: 12px; color: var(--text-muted);">Telegram Alerts:</span>
                <input type="text" id="tg-token" placeholder="Bot Token">
                <input type="text" id="tg-chat" placeholder="Chat ID">
                <button class="btn-tg" onclick="saveTelegram()">Save & Link</button>
                <span id="val-tg-status" style="font-size: 11px; margin-left: 5px; font-weight: 600;" class="text-cyan">Checking...</span>
            </div>
        </div>

        <!-- ============================================================================== -->
        <!-- SECTION 1: CROSS-EXCHANGE PERPETUAL FUNDING RATE ARBITRAGE -->
        <!-- ============================================================================== -->
        <div class="section-header">
            <div class="section-title">
                ⚡ SECTION 1: CROSS-EXCHANGE FUNDING RATE ARBITRAGE
                <span class="engine-tag tag-funding">DELTA INDIA VS COINDCX / BINANCE</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted);" id="val-scan-time">Last Scan: Just Now</div>
        </div>

        <div class="grid-4">
            <div class="card">
                <div class="card-label">Account Balance</div>
                <div class="card-val text-green" id="val-balance">$10.00</div>
            </div>
            <div class="card">
                <div class="card-label">Funding Net PnL (USD)</div>
                <div class="card-val text-green" id="val-pnl">+$0.0000</div>
            </div>
            <div class="card">
                <div class="card-label">Top Funding Difference</div>
                <div class="card-val text-cyan" id="val-diff">0.0000%</div>
            </div>
            <div class="card">
                <div class="card-label">Execution Mode</div>
                <div class="card-val" id="val-live-mode" style="font-size: 15px; margin-top: 5px; color: #ff4d4d;">PAPER 📄</div>
            </div>
        </div>
        <div class="grid-4" style="margin-top: 0;">
            <div class="card" style="grid-column: span 2;">
                <div class="card-label">Next Settlement Countdown</div>
                <div class="card-val text-yellow" id="val-countdown" style="font-size: 16px; margin-top: 5px;">Calculating...</div>
            </div>
        </div>

        <div class="section-header">
            <div class="section-title" style="font-size: 14px;">Top 5 Live Funding Rate Arbitrage Opportunities</div>
            <span style="font-size: 11px; color: var(--text-muted);">Strict Fee Guard Gate: Spread &ge; 0.15%</span>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Coin</th>
                        <th>Delta Exchange Rate</th>
                        <th>Binance Rate</th>
                        <th>CoinDCX Rate</th>
                        <th>Spread (%)</th>
                        <th>Funding Countdown</th>
                        <th>Hedging Action</th>
                    </tr>
                </thead>
                <tbody id="top5-rows">
                    <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">Scanning live exchange order books...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="grid-2">
            <div>
                <div class="section-header">
                    <div class="section-title" style="font-size: 14px;">Funding Event Logs</div>
                </div>
                <div class="log-box" id="logs-container">
                    <div class="log-entry">Initializing Funding Engine...</div>
                </div>
            </div>

            <div>
                <div class="section-header">
                    <div class="section-title" style="font-size: 14px;">Executed Scalp Trades History</div>
                </div>
                <div class="table-container" style="height: 250px; overflow-y: auto; margin-bottom: 0;">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Time</th>
                                <th>Coin</th>
                                <th>Gross</th>
                                <th>Fees</th>
                                <th>Net PnL</th>
                            </tr>
                        </thead>
                        <tbody id="history-rows">
                            <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Waiting for funding window execution...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- ============================================================================== -->
        <!-- DIVIDER & SECTION 2: BINANCE ALL-BTC-COINS TRIANGULAR ARBITRAGE (SCROLL DOWN) -->
        <!-- ============================================================================== -->
        <hr class="section-divider">

        <div class="section-header">
            <div class="section-title">
                🔺 SECTION 2: BINANCE DYNAMIC ALL-BTC TRIANGULAR ARBITRAGE
                <span class="engine-tag tag-triangular">BINANCE EXCLUSIVE (ALL BTC PAIRS)</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted);" id="tri-scan-time">Last Scan: Just Now</div>
        </div>

        <div class="grid-4">
            <div class="card">
                <div class="card-label">Virtual Paper Balance</div>
                <div class="card-val text-green" id="tri-val-balance">$10.0000</div>
            </div>
            <div class="card">
                <div class="card-label">Net Triangular PnL (USD)</div>
                <div class="card-val text-green" id="tri-val-pnl-usd">+$0.0000</div>
            </div>
            <div class="card">
                <div class="card-label">Active BTC Pairs Scanned</div>
                <div class="card-val text-purple" id="tri-val-count">0 Pairs</div>
            </div>
            <div class="card">
                <div class="card-label">Top Scanned Loop</div>
                <div class="card-val text-cyan" id="tri-val-loop" style="font-size: 15px; margin-top: 5px;">-</div>
            </div>
        </div>

        <div class="section-header">
            <div class="section-title" style="font-size: 14px;">Top Scanned Triangular Loops (Binance Spot L2 Order Book)</div>
            <span style="font-size: 11px; color: var(--text-muted);">Order Book Depth Walk (Top 10 Levels) for VWAP Slippage</span>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Triangular Loop</th>
                        <th>Direction</th>
                        <th>Step 1</th>
                        <th>Step 2</th>
                        <th>Step 3</th>
                        <th>Fees & Slippage</th>
                        <th>Net Profit %</th>
                    </tr>
                </thead>
                <tbody id="triangular-rows">
                    <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">Scanning all active Binance BTC trading pairs...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="grid-2">
            <div>
                <div class="section-header">
                    <div class="section-title" style="font-size: 14px;">Triangular Scanner Logs</div>
                </div>
                <div class="log-box" id="triangular-logs-container">
                    <div class="log-entry">Initializing Binance All-BTC Scanner Engine...</div>
                </div>
            </div>

            <div>
                <div class="section-header">
                    <div class="section-title" style="font-size: 14px;">Triangular Executed Paper Trades</div>
                </div>
                <div class="table-container" style="height: 250px; overflow-y: auto; margin-bottom: 0;">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Time</th>
                                <th>Loop</th>
                                <th>Fees</th>
                                <th>Net PnL</th>
                                <th>Updated Balance</th>
                            </tr>
                        </thead>
                        <tbody id="triangular-history-rows">
                            <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Waiting for profitable Binance triangular loop (&ge; +0.10% Net)...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

    </div>

    <!-- DASHBOARD AUTO-REFRESH SCRIPT -->
    <script>
        async function saveTelegram() {
            const token = document.getElementById('tg-token').value.trim();
            const chat = document.getElementById('tg-chat').value.trim();
            if(!token) {
                alert("Please enter your Telegram Bot Token!");
                return;
            }
            const res = await fetch('/api/telegram', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({bot_token: token, chat_id: chat, enabled: true})
            });
            const d = await res.json();
            if(d.status === 'ok') {
                document.getElementById('tg-chat').value = d.chat_id;
                alert("🎉 Success! Telegram Trade Alerts Successfully Linked to Chat ID: " + d.chat_id);
            } else if(d.status === 'need_message') {
                alert("⚠️ Auto-Detect Hint: Please open your bot on Telegram and send 1 message (e.g. 'hi'), then click this button again!");
            } else {
                alert("Error linking Telegram. Please check your Bot Token!");
            }
        }

        async function updateDashboard() {
            try {
                const res = await fetch('/api/state?t=' + new Date().getTime());
                const data = await res.json();

                if (!data || !data.state) return;

                // --- UPDATE ENGINE 1: FUNDING ARBITRAGE ---
                document.getElementById('val-balance').innerText = data.state.real_balance_display || ('$' + (data.state.paper_wallet_balance || 10.0).toFixed(2));
                const pnl = data.state.net_pnl_usd || 0.0;
                const pnlEl = document.getElementById('val-pnl');
                pnlEl.innerText = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(4);
                pnlEl.className = pnl >= 0 ? 'card-val text-green' : 'card-val text-red';

                const diffEl = document.getElementById('val-diff');
                if (diffEl) diffEl.innerText = data.state.active_funding_diff || '0.0000%';

                const liveModeEl = document.getElementById('val-live-mode');
                if (liveModeEl) {
                    const lm = data.state.live_mode || 'PAPER 📄';
                    liveModeEl.innerText = lm;
                    liveModeEl.style.color = lm.includes('LIVE') ? '#ff4d4d' : '#aaaaaa';
                }

                document.getElementById('val-scan-time').innerText = 'Last Scan: ' + (data.state.last_scan_time || 'Just Now');
                document.getElementById('val-countdown').innerText = data.state.next_funding_countdown || 'Calculating...';
                document.getElementById('val-tg-status').innerText = data.state.telegram_status || 'Not Configured';

                const top5Body = document.getElementById('top5-rows');
                if (data.state.top5_coins && data.state.top5_coins.length > 0) {
                    top5Body.innerHTML = data.state.top5_coins.map((item, idx) => `
                        <tr>
                            <td><strong>${idx + 1}</strong></td>
                            <td><strong class="text-cyan">${item.coin}</strong></td>
                            <td>${item.delta_sym} (<span class="text-green">${item.delta_rate}</span>)</td>
                            <td>${item.binance_sym} (<span class="text-cyan">${item.binance_rate}</span>)</td>
                            <td>${item.cdcx_sym} (<span class="text-yellow">${item.cdcx_rate}</span>)</td>
                            <td><strong class="text-green">${item.diff}</strong></td>
                            <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${item.next_funding || '-'}</td>
                            <td><span class="badge-action">${item.action}</span></td>
                        </tr>
                    `).join('');
                }

                const logsBox = document.getElementById('logs-container');
                if (data.logs && data.logs.length > 0) {
                    logsBox.innerHTML = data.logs.map(l => `<div class="log-entry">${l}</div>`).join('');
                    logsBox.scrollTop = logsBox.scrollHeight;
                }

                const tbody = document.getElementById('history-rows');
                if (data.history && data.history.length > 0) {
                    tbody.innerHTML = data.history.map(t => `
                        <tr>
                            <td>${t.id}</td>
                            <td>${t.timestamp.split(' ')[1] || t.timestamp}</td>
                            <td><strong class="text-cyan">${t.coin}</strong></td>
                            <td class="text-green">${t.gross_income}</td>
                            <td class="text-red">${t.fees}</td>
                            <td class="${t.net_pnl.includes('+') ? 'text-green' : 'text-red'}">${t.net_pnl}</td>
                        </tr>
                    `).join('');
                }

                // --- UPDATE ENGINE 2: BINANCE ALL-BTC TRIANGULAR ARBITRAGE ---
                document.getElementById('tri-scan-time').innerText = 'Last Scan: ' + (data.state.triangular_last_scan || 'Just Now');
                document.getElementById('tri-val-balance').innerText = '$' + (data.state.triangular_paper_balance || 10.0).toFixed(4);
                
                const triPnlUsd = data.state.triangular_net_pnl_usd || 0.0;
                const triPnlUsdEl = document.getElementById('tri-val-pnl-usd');
                if (triPnlUsdEl) {
                    triPnlUsdEl.innerText = (triPnlUsd >= 0 ? '+' : '') + '$' + triPnlUsd.toFixed(4);
                    triPnlUsdEl.className = triPnlUsd >= 0 ? 'card-val text-green' : 'card-val text-red';
                }

                document.getElementById('tri-val-count').innerText = (data.state.triangular_scanned_count || 0) + ' BTC Pairs';
                document.getElementById('tri-val-loop').innerText = data.state.triangular_top_loop || '-';

                const triBody = document.getElementById('triangular-rows');
                if (data.state.triangular_top5 && data.state.triangular_top5.length > 0) {
                    triBody.innerHTML = data.state.triangular_top5.map((item, idx) => `
                        <tr>
                            <td><strong>${idx + 1}</strong></td>
                            <td><strong class="text-purple">${item.label}</strong></td>
                            <td><span class="badge-ex">${item.loop_type}</span></td>
                            <td style="font-size:12px;">${item.step1}</td>
                            <td style="font-size:12px;">${item.step2}</td>
                            <td style="font-size:12px;">${item.step3}</td>
                            <td style="font-size:12px;"><span class="text-red">-$${item.total_fees.toFixed(4)}</span> | <span class="text-yellow">Slip -$${item.total_slip.toFixed(4)}</span></td>
                            <td><strong class="${item.net_pnl_pct.includes('-') ? 'text-red' : 'text-green'}">${item.net_pnl_pct}</strong></td>
                        </tr>
                    `).join('');
                }

                const triLogsBox = document.getElementById('triangular-logs-container');
                if (data.triangular_logs && data.triangular_logs.length > 0) {
                    triLogsBox.innerHTML = data.triangular_logs.map(l => `<div class="log-entry">${l}</div>`).join('');
                    triLogsBox.scrollTop = triLogsBox.scrollHeight;
                }

                const triHistoryBody = document.getElementById('triangular-history-rows');
                if (data.triangular_history && data.triangular_history.length > 0) {
                    triHistoryBody.innerHTML = data.triangular_history.map(t => `
                        <tr>
                            <td>${t.id}</td>
                            <td>${t.timestamp.split(' ')[1] || t.timestamp}</td>
                            <td><strong class="text-purple">${t.loop}</strong></td>
                            <td class="text-red">${t.fees}</td>
                            <td class="text-green">${t.net_pnl}</td>
                            <td class="text-cyan">${t.balance}</td>
                        </tr>
                    `).join('');
                }

            } catch (err) {
                console.error("Dashboard update error:", err);
            }
        }

        setInterval(updateDashboard, 2000);
        updateDashboard();
    </script>
</body>
</html>"""

class WebDashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ['/ping', '/health', '/api/ping']:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
            self.wfile.write(json.dumps({
                "status": "ok",
                "server_time_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
                "bot_status": bot_state.get("status")
            }).encode('utf-8'))
        elif self.path.startswith('/') and not self.path.startswith('/api/'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode('utf-8'))
        elif self.path.startswith('/api/state'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            payload = {
                "state": bot_state,
                "logs": live_logs,
                "history": paper_history,
                "triangular_logs": triangular_logs,
                "triangular_history": triangular_history
            }
            self.wfile.write(json.dumps(payload, default=str).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/telegram':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            bot_token = data.get('bot_token', '').strip()
            chat_id = data.get('chat_id', '').strip()
            enabled = data.get('enabled', True)

            if not chat_id and bot_token:
                detected_id = auto_detect_chat_id(bot_token)
                if detected_id:
                    chat_id = detected_id

            cfg = {
                "bot_token": bot_token,
                "chat_id": chat_id,
                "enabled": enabled
            }
            with open(CONFIG_FILE, 'w') as f:
                json.dump(cfg, f, indent=2)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            if chat_id:
                self.wfile.write(json.dumps({"status": "ok", "chat_id": chat_id}).encode('utf-8'))
                send_telegram_alert("🔔 *Telegram Trade Notification Successfully Linked to Multi-Engine Dashboard!*")
            else:
                self.wfile.write(json.dumps({"status": "need_message", "message": "Please send 1 message to your bot on Telegram, then try again!"}).encode('utf-8'))

    def log_message(self, format, *args):
        return

def run_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), WebDashboardHandler) as httpd:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Multi-Engine Web Dashboard running at http://localhost:{PORT}")
        httpd.serve_forever()

if __name__ == '__main__':
    run_server()
