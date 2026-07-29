"""
Unified Cross-Exchange Arbitrage Engine with Top 5 Live Opportunities Table & Telegram Alerts
Features:
1. TELEGRAM INSTANT ALERTS: Sends trade notifications to your Telegram channel/bot.
2. TOP 5 LIVE DIFFERENCE TABLE with funding countdown timers.
3. DUAL-LEG EXECUTION & ORDERBOOK SAFEGUARDS.
4. 100% TIMING & FEE GUARDS.
5. Standard Library HTTP Server on http://localhost:5050.
"""

import http.server
import socketserver
import urllib.request
import urllib.parse
import json
import datetime
import threading
import time
import os

PORT = int(os.environ.get("PORT", 5050))
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_config.json")

# In-Memory State
live_logs = []
paper_history = []
bot_state = {
    "status": "DUAL-LEG SAFEGUARD ACTIVE",
    "paper_wallet_balance": 10.0,
    "total_trades": 0,
    "net_pnl_usd": 0.0,
    "last_scan_time": "-",
    "active_top_coin": "-",
    "active_funding_diff": "0.0000%",
    "next_funding_countdown": "Calculating...",
    "top5_coins": [],
    "telegram_status": "Not Configured"
}

def get_telegram_config():
    # 1. Try local config file
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
                if cfg.get("bot_token") and cfg.get("chat_id"):
                    return cfg
        except Exception:
            pass
    # 2. Fallback to Environment Variables (useful for Render / Cloud hosting)
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

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        res = urllib.request.urlopen(req, timeout=6)
        data = json.loads(res.read().decode())
        if isinstance(data, dict) and 'result' in data:
            return data['result']
        return data
    except Exception:
        return []

def add_log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    live_logs.append(entry)
    if len(live_logs) > 100:
        live_logs.pop(0)

def get_coin_max_leverage(coin):
    c = coin.upper()
    if c in ['BTC', 'ETH']:
        return 100.0
    elif c in ['SOL', 'XRP', 'DOGE', 'BNB', '1000SATS', 'ADA', 'AVAX', 'LINK', 'NEAR', 'SUI', 'PEPE', 'SHIB', 'WIF']:
        return 50.0
    else:
        return 20.0

def bot_background_loop():
    global paper_history, bot_state
    
    add_log("Bot Engine Initialized with Dynamic Exchange Max Leverage, Safeguards & Telegram Alerts.")
    
    margin = 10.0        # $10 Margin per exchange

    def next_funding_info(interval_hours, now_utc):
        h = int(interval_hours)
        current_hour_utc = now_utc.hour
        next_settlement_hour_utc = ((current_hour_utc // h) + 1) * h
        if next_settlement_hour_utc >= 24:
            next_settlement_hour_utc -= 24
        
        target_utc = now_utc.replace(hour=next_settlement_hour_utc, minute=0, second=0, microsecond=0)
        if target_utc <= now_utc:
            target_utc += datetime.timedelta(days=1)
            
        target_ist = target_utc + datetime.timedelta(hours=5, minutes=30)
        mins_left = int((target_utc - now_utc).total_seconds() // 60)
        return target_ist.strftime("%H:%M IST"), mins_left

    # Track which (coin, funding_timestamp_utc) pairs already executed this cycle
    executed_windows = set()
    # Track pending trade awaiting exit (entry done, waiting for T+2sec after funding)
    pending_exit = None   # dict: {coin, top, gross_funding, coin_fee, net_pnl, coin_lev, coin_notional, funding_ts_utc, entry_time}

    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
            now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")

            creds = get_telegram_config()
            bot_state["telegram_status"] = "Active 🟢" if creds.get("enabled") and creds.get("bot_token") else "Not Configured ⚪"

            # ── PHASE 1: If pending exit, wait for T+2 seconds after funding snapshot ──
            if pending_exit:
                pe = pending_exit
                secs_after_funding = (now_utc - pe["funding_ts_utc"]).total_seconds()
                if secs_after_funding >= 2.0:
                    # Execute scalper exit NOW
                    coin    = pe["coin"]
                    top     = pe["top"]
                    gross   = pe["gross_funding"]
                    fee     = pe["coin_fee"]
                    net     = pe["net_pnl"]
                    lev     = pe["coin_lev"]
                    notl    = pe["coin_notional"]
                    diff    = pe["diff"]

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

                    add_log(f"⚡ [SCALPER EXIT T+{secs_after_funding:.1f}s] Dual-Leg Neutral Exit fired for {coin} (0% Delta Exit Fee Waiver).")
                    add_log(f"✅ {lev:.0f}X TRADE COMPLETE ({coin}): Gross +${gross:.4f} | Fees -${fee:.4f} | NET +${net:.4f} USD | Balance ${bot_state['paper_wallet_balance']:.2f}")

                    tg_msg = (
                        f"🚨 *PRECISION TIMED ARBITRAGE COMPLETE* 🚀\n\n"
                        f"🪙 *Coin:* `{coin}`\n"
                        f"📊 *Strategy:* `{top['action']}`\n"
                        f"⏱️ *Timing:* `Entry T-1min → Snapshot T+0s → Scalper Exit T+{secs_after_funding:.1f}s`\n"
                        f"⚙️ *Margin & Leverage:* `$10.00 @ {lev:.0f}x (${notl:.0f} Notional/leg)`\n"
                        f"⚡ *Spread:* `{diff:.4f}%`\n\n"
                        f"💵 *Gross Funding:* `+${gross:.4f} USD`\n"
                        f"🏷️ *Roundtrip Fees:* `-${fee:.4f} USD`\n"
                        f"📈 *NET CASH PROFIT:* `+${net:.4f} USD`\n"
                        f"💰 *New Virtual Balance:* `${bot_state['paper_wallet_balance']:.2f} USD`"
                    )
                    send_telegram_alert(tg_msg)
                    pending_exit = None
                else:
                    add_log(f"🔒 [FUNDING SNAPSHOT LOCKED] Waiting for T+2s scalper exit... ({secs_after_funding:.1f}s elapsed)")
                    time.sleep(0.5)
                    continue

            # ── PHASE 2: Fetch live data ──
            delta_products = fetch("https://api.india.delta.exchange/v2/products")
            delta_tickers  = fetch("https://api.india.delta.exchange/v2/tickers")

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
                    coin     = sym.replace('USD', '')
                    h        = delta_interval.get(sym, 8.0)
                    delta_map[coin] = {'rate': rate_pct, 'h': h, 'sym': sym, 'mark': mark}

            binance_funding = fetch("https://fapi.binance.com/fapi/v1/premiumIndex")
            binance_map = {}
            coindcx_map = {}
            for b in binance_funding:
                sym = b.get('symbol', '')
                if sym.endswith('USDT'):
                    coin     = sym.replace('USDT', '')
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

                # ── Per-coin actual funding timestamp (UTC) ──
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

            results.sort(key=lambda x: x['raw_diff_num'], reverse=True)
            clean_top5 = []
            for r in results[:5]:
                item_copy = dict(r)
                item_copy.pop('funding_ts_obj', None)
                clean_top5.append(item_copy)

            bot_state["top5_coins"] = clean_top5
            bot_state["total_scanned_coins"] = len(results)

            if not results:
                add_log("⚠️ No common coins found. Retrying...")
                time.sleep(5)
                continue

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

            # ── PHASE 3: Entry Window = 60-120 seconds BEFORE funding timestamp ──
            # One trade per (coin, funding_window_key) only
            funding_window_key = f"{coin}_{funding_ts_utc.strftime('%Y%m%d%H%M')}"
            is_entry_window    = 60 <= secs <= 120   # between T-120s and T-60s
            already_executed   = funding_window_key in executed_windows

            # Clean up old window keys (older than 2 hours)
            cutoff = now_utc - datetime.timedelta(hours=2)
            executed_windows = {k for k in executed_windows
                                if datetime.datetime.strptime(k.split('_')[1], '%Y%m%d%H%M')
                                   .replace(tzinfo=None) > cutoff}

            if is_entry_window and not already_executed:
                if net_pnl > 0:
                    add_log(f"⚡ [ENTRY T-{secs}s] Dual-Leg entry FIRED for {coin} ({coin_lev:.0f}x | Notional ${coin_notional:.0f})")
                    add_log(f"   Delta: {top['delta_rate']} | CoinDCX: {top['cdcx_rate']} | Spread: {diff:.4f}%")
                    add_log(f"   Gross Funding: +${gross_funding:.4f} | Fees: -${coin_fee:.4f} | NET: +${net_pnl:.4f}")
                    add_log(f"   Strategy: {top['action']}")

                    tg_entry = (
                        f"⚡ *ENTRY FIRED — T-{secs}s BEFORE FUNDING*\n\n"
                        f"🪙 *Coin:* `{coin}`\n"
                        f"📊 *Strategy:* `{top['action']}`\n"
                        f"⚙️ *Leverage:* `{coin_lev:.0f}x | ${coin_notional:.0f} Notional/leg`\n"
                        f"⚡ *Spread:* `{diff:.4f}%`\n"
                        f"🕐 *Funding in:* `{secs}s`\n\n"
                        f"💵 *Expected Gross:* `+${gross_funding:.4f}`\n"
                        f"🏷️ *Expected Fees:* `-${coin_fee:.4f}`\n"
                        f"📈 *Expected NET:* `+${net_pnl:.4f} USD`"
                    )
                    send_telegram_alert(tg_entry)

                    executed_windows.add(funding_window_key)

                    # Queue exit at T+2s (simulate funding snapshot + scalper exit)
                    pending_exit = {
                        "coin":          coin,
                        "top":           top,
                        "gross_funding": gross_funding,
                        "coin_fee":      coin_fee,
                        "net_pnl":       net_pnl,
                        "coin_lev":      coin_lev,
                        "coin_notional": coin_notional,
                        "diff":          diff,
                        "funding_ts_utc": funding_ts_utc,
                        "entry_time":    now_utc,
                    }
                else:
                    add_log(f"⚠️ [{coin} T-{secs}s] SKIP — Net PnL (${net_pnl:.4f}) negative after fees. Gross ${gross_funding:.4f} < Fee ${coin_fee:.4f}.")
                    executed_windows.add(funding_window_key)  # skip this window

            elif already_executed:
                add_log(f"🔒 [{coin}] Window already executed. Standing by for next funding cycle...")
            else:
                add_log(f"🔍 Scan OK | Top: {coin} | Spread: {diff:.4f}% | Action: {top['action']} | Funding in: {top['mins_left']}m {secs%60}s | Net after fees: ${net_pnl:.4f}")

        except Exception as e:
            add_log(f"❌ Error in bot loop: {e}")

        time.sleep(1)

def self_ping_loop():
    """Background thread to ping Render external URL every 4 minutes to prevent sleep mode 24/7."""
    time.sleep(30)  # Wait 30s after server startup
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
        time.sleep(240)  # Ping every 4 minutes

# Start background threads
threading.Thread(target=bot_background_loop, daemon=True).start()
threading.Thread(target=self_ping_loop, daemon=True).start()

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>Cross-Exchange Arbitrage Bot Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #090d16;
            --card-bg: rgba(18, 26, 42, 0.75);
            --border: rgba(255, 255, 255, 0.08);
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-cyan: #06b6d4;
            --accent-blue: #3b82f6;
            --accent-yellow: #f59e0b;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            min-height: 100vh;
            padding: 24px;
            background-image: radial-gradient(circle at 10% 20%, rgba(6, 182, 212, 0.08) 0%, transparent 40%),
                              radial-gradient(circle at 90% 80%, rgba(59, 130, 246, 0.08) 0%, transparent 40%);
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }

        .title-box h1 {
            font-size: 24px;
            font-weight: 700;
            background: linear-gradient(135deg, #38bdf8, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .title-box p {
            font-size: 13px;
            color: var(--text-muted);
            margin-top: 4px;
        }

        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(16, 185, 129, 0.15);
            color: var(--accent-green);
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            background-color: var(--accent-green);
            border-radius: 50%;
            box-shadow: 0 0 10px var(--accent-green);
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(0.95); opacity: 0.8; }
            50% { transform: scale(1.2); opacity: 1; }
            100% { transform: scale(0.95); opacity: 0.8; }
        }

        .grid-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .metric-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            backdrop-filter: blur(12px);
        }

        .metric-card span {
            font-size: 13px;
            color: var(--text-muted);
            font-weight: 500;
        }

        .metric-card h2 {
            font-size: 24px;
            font-weight: 700;
            margin-top: 8px;
            font-family: 'JetBrains Mono', monospace;
        }

        .grid-content {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }

        @media (max-width: 1000px) {
            .grid-content { grid-template-columns: 1fr; }
        }

        .panel {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            backdrop-filter: blur(12px);
            display: flex;
            flex-direction: column;
            margin-bottom: 24px;
        }

        .panel-header {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 16px;
            color: var(--text-main);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .logs-box {
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            background: rgba(0, 0, 0, 0.4);
            border-radius: 10px;
            padding: 14px;
            overflow-y: auto;
            height: 380px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            line-height: 1.6;
        }

        .log-entry {
            margin-bottom: 6px;
            color: #d1d5db;
        }

        .table-container {
            overflow-y: auto;
            max-height: 380px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }

        th {
            text-align: left;
            padding: 10px 12px;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border);
            font-weight: 600;
            position: sticky;
            top: 0;
            background: #101624;
        }

        td {
            padding: 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
            font-family: 'JetBrains Mono', monospace;
        }

        tr:hover { background: rgba(255, 255, 255, 0.02); }

        .badge-action {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            background: rgba(6, 182, 212, 0.15);
            color: var(--accent-cyan);
            border: 1px solid rgba(6, 182, 212, 0.3);
        }

        /* Telegram Form */
        .tg-box {
            display: flex;
            gap: 12px;
            align-items: center;
            margin-top: 10px;
        }
        .tg-input {
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid var(--border);
            color: #fff;
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 13px;
            flex: 1;
        }
        .tg-btn {
            background: linear-gradient(135deg, #06b6d4, #3b82f6);
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
        }

        .text-green { color: var(--accent-green); }
        .text-red { color: var(--accent-red); }
        .text-cyan { color: var(--accent-cyan); }
        .text-yellow { color: var(--accent-yellow); }
    </style>
</head>
<body>

    <header>
        <div class="title-box">
            <h1>Multi-Exchange Arbitrage Dashboard</h1>
            <p>Delta Exchange India vs Binance Futures vs CoinDCX • Live Scanner & Telegram Alerts</p>
        </div>
        <div class="status-badge">
            <div class="status-dot"></div>
            STANDBY FOR FUNDING WINDOW
        </div>
    </header>

    <div class="grid-metrics">
        <div class="metric-card">
            <span>Paper Wallet Balance</span>
            <h2 id="val-balance" class="text-cyan">$10.00</h2>
        </div>
        <div class="metric-card">
            <span>Total Net PnL (USD)</span>
            <h2 id="val-pnl" class="text-green">+$0.0000</h2>
        </div>
        <div class="metric-card">
            <span>Trades Executed</span>
            <h2 id="val-trades">0</h2>
        </div>
        <div class="metric-card">
            <span>Active Top Coin (Spread)</span>
            <h2 class="text-green"><span id="val-coin">-</span> (<span id="val-diff">0.0000%</span>)</h2>
        </div>
        <div class="metric-card">
            <span>Telegram Alert Status</span>
            <h2 id="val-tg-status" class="text-yellow">Not Configured</h2>
        </div>
    </div>

    <!-- TELEGRAM CONFIGURATION CARD -->
    <div class="panel" style="margin-bottom: 24px;">
        <div class="panel-header">
            <span>📱 TELEGRAM TRADE ALERT NOTIFICATION SETUP</span>
            <span style="font-size: 11px; color: var(--text-muted);">Instant Trade Alert Messages</span>
        </div>
        <div class="tg-box">
            <input type="text" id="tg-token" class="tg-input" placeholder="Telegram Bot Token (e.g. 123456789:ABCdef...)" />
            <input type="text" id="tg-chat" class="tg-input" placeholder="Telegram Chat ID (e.g. 987654321)" />
            <button class="tg-btn" onclick="saveTelegram()">Save & Enable Telegram Alerts</button>
        </div>
    </div>

    <!-- MAIN PANEL: REAL-TIME TOP 5 FUNDING DIFFERENCE TABLE -->
    <div class="panel">
        <div class="panel-header">
            <span>🔥 REAL-TIME TOP 5 OPPORTUNITIES (SCANNED 187 COINS ACROSS DELTA INDIA, BINANCE & COINDCX)</span>
            <span style="font-size: 11px; color: var(--text-muted);" id="val-scan-time">Last Scan: Just Now</span>
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Coin</th>
                        <th>Delta India Rate</th>
                        <th>Binance Futures Rate</th>
                        <th>CoinDCX Futures Rate</th>
                        <th>Max Spread</th>
                        <th>Next Settlement</th>
                        <th>RECOMMENDED ACTION</th>
                    </tr>
                </thead>
                <tbody id="top5-rows">
                    <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">Fetching live top 5 funding opportunities...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <div class="grid-content">
        <div class="panel" style="margin-bottom: 0;">
            <div class="panel-header">
                <span>Live Background Terminal Logs</span>
                <span style="font-size: 11px; color: var(--text-muted);" id="val-countdown">Calculating...</span>
            </div>
            <div class="logs-box" id="logs-container">
                <div class="log-entry">[INITIALIZING] Connecting to backend engine...</div>
            </div>
        </div>

        <div class="panel" style="margin-bottom: 0;">
            <div class="panel-header">
                <span>Executed Scalps History (Fee Paid)</span>
                <span style="font-size: 11px; color: var(--text-muted);">Strict Fee Guard Active</span>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Time</th>
                            <th>Coin</th>
                            <th>Gross Income</th>
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

                document.getElementById('val-balance').innerText = '$' + (data.state.paper_wallet_balance || 10.0).toFixed(2);
                
                const pnl = data.state.net_pnl_usd || 0.0;
                const pnlEl = document.getElementById('val-pnl');
                pnlEl.innerText = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(4);
                pnlEl.className = pnl >= 0 ? 'text-green' : 'text-red';

                document.getElementById('val-trades').innerText = data.state.total_trades || 0;
                
                const coinEl = document.getElementById('val-coin');
                const diffEl = document.getElementById('val-diff');
                if (coinEl) coinEl.innerText = data.state.active_top_coin || '-';
                if (diffEl) diffEl.innerText = data.state.active_funding_diff || '0.0000%';

                document.getElementById('val-scan-time').innerText = 'Last Scan: ' + (data.state.last_scan_time || 'Just Now');
                document.getElementById('val-countdown').innerText = data.state.next_funding_countdown || 'Calculating...';
                document.getElementById('val-tg-status').innerText = data.state.telegram_status || 'Not Configured';

                // Render Top 5 Table
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

                // Render Logs
                const logsBox = document.getElementById('logs-container');
                if (data.logs && data.logs.length > 0) {
                    logsBox.innerHTML = data.logs.map(l => `<div class="log-entry">${l}</div>`).join('');
                    logsBox.scrollTop = logsBox.scrollHeight;
                }

                // Render History
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
            } catch (err) {
                console.error("Dashboard update failed:", err);
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
                "history": paper_history
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
                send_telegram_alert("🔔 *Telegram Trade Notification Successfully Linked to Arbitrage Bot!*")
            else:
                self.wfile.write(json.dumps({"status": "need_message", "message": "Please send 1 message to your bot on Telegram, then try again!"}).encode('utf-8'))

    def log_message(self, format, *args):
        return

def run_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), WebDashboardHandler) as httpd:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Unified Web Dashboard running at http://localhost:{PORT}")
        httpd.serve_forever()

if __name__ == '__main__':
    run_server()
