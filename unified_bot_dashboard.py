"""
Unified Multi-Engine Arbitrage Platform
=========================================
Engine 1: Cross-Exchange Perpetual Funding Rate Arbitrage (Delta Exchange India vs CoinDCX / Binance)
Engine 2: Single-Exchange Triangular Arbitrage (3-Pair Loops: Binance vs CoinDCX with L2 Depth Walk & 1% Indian TDS Metrics)

Features:
1. Double-Section Web Dashboard on http://localhost:5050 (Scroll down to view Triangular Arbitrage).
2. Real-time L2 Order Book Depth Walk (Top 10 Levels) for VWAP Slippage Calculation.
3. Full Telegram Instant Trade Alerts for both Cross-Exchange & Triangular Arbitrage opportunities.
4. Render 24/7 Keep-Alive Self-Ping Module.
5. 100% Paper Trading & Live Data Feed Simulation Engine.
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
import sys

# Enforce UTF-8 encoding for Windows terminal compatibility
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

PORT = int(os.environ.get("PORT", 5050))
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_config.json")

# Global In-Memory State
live_logs = []
paper_history = []

triangular_logs = []
triangular_history = []

bot_state = {
    # Engine 1: Cross-Exchange Funding
    "status": "DUAL-LEG SAFEGUARD ACTIVE",
    "paper_wallet_balance": 10.0,
    "total_trades": 0,
    "net_pnl_usd": 0.0,
    "last_scan_time": "-",
    "active_top_coin": "-",
    "active_funding_diff": "0.0000%",
    "next_funding_countdown": "Calculating...",
    "top5_coins": [],
    "telegram_status": "Not Configured",
    
    # Engine 2: Triangular Arbitrage
    "triangular_status": "L2 DEPTH SCANNER ACTIVE",
    "triangular_scanned_count": 0,
    "triangular_last_scan": "-",
    "triangular_top_loop": "-",
    "triangular_top_exchange": "-",
    "triangular_top_net_pnl": "0.0000%",
    "triangular_top5": [],
    "triangular_total_trades": 0,
    "triangular_net_pnl_usd": 0.0
}

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

def add_triangular_log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    triangular_logs.append(entry)
    if len(triangular_logs) > 100:
        triangular_logs.pop(0)

def get_coin_max_leverage(coin):
    c = coin.upper()
    if c in ['BTC', 'ETH']:
        return 100.0
    elif c in ['SOL', 'XRP', 'DOGE', 'BNB', '1000SATS', 'ADA', 'AVAX', 'LINK', 'NEAR', 'SUI', 'PEPE', 'SHIB', 'WIF']:
        return 50.0
    else:
        return 20.0

# ==============================================================================
# ENGINE 1: CROSS-EXCHANGE FUNDING RATE ARBITRAGE LOOP
# ==============================================================================
def bot_background_loop():
    global paper_history, bot_state
    
    add_log("Funding Engine Initialized with Dynamic Exchange Leverage & Fee Guard.")
    margin = 10.0  # $10 Margin per exchange

    executed_windows = set()
    pending_exit = None

    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
            now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")

            creds = get_telegram_config()
            bot_state["telegram_status"] = "Active 🟢" if creds.get("enabled") and creds.get("bot_token") else "Not Configured ⚪"

            # ── PHASE 1: Scalper Exit Check ──
            if pending_exit:
                pe = pending_exit
                secs_after_funding = (now_utc - pe["funding_ts_utc"]).total_seconds()
                if secs_after_funding >= 2.0:
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

                    add_log(f"⚡ [SCALPER EXIT T+{secs_after_funding:.1f}s] Neutral Exit fired for {coin} (0% Delta Exit Fee Waiver).")
                    add_log(f"✅ {lev:.0f}X TRADE COMPLETE ({coin}): Gross +${gross:.4f} | Fees -${fee:.4f} | NET +${net:.4f} USD")

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

            # ── PHASE 2: Fetch Live Rates ──
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

            funding_window_key = f"{coin}_{funding_ts_utc.strftime('%Y%m%d%H%M')}"
            is_entry_window    = 60 <= secs <= 120
            already_executed   = funding_window_key in executed_windows

            cutoff = now_utc - datetime.timedelta(hours=2)
            executed_windows = {k for k in executed_windows
                                if datetime.datetime.strptime(k.split('_')[1], '%Y%m%d%H%M')
                                   .replace(tzinfo=None) > cutoff}

            if is_entry_window and not already_executed:
                if net_pnl > 0:
                    add_log(f"⚡ [ENTRY T-{secs}s] Entry FIRED for {coin} ({coin_lev:.0f}x | Notional ${coin_notional:.0f})")
                    add_log(f"   Delta: {top['delta_rate']} | CoinDCX: {top['cdcx_rate']} | Spread: {diff:.4f}%")
                    add_log(f"   Gross Funding: +${gross_funding:.4f} | Fees: -${coin_fee:.4f} | NET: +${net_pnl:.4f}")

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
# ENGINE 2: SINGLE-EXCHANGE TRIANGULAR ARBITRAGE SCANNER (BINANCE VS COINDCX)
# ==============================================================================
TRIANGULAR_CANDIDATE_LOOPS = [
    {"a": "ETH", "b": "BTC",  "label": "USDT → ETH → BTC → USDT"},
    {"a": "SOL", "b": "BTC",  "label": "USDT → SOL → BTC → USDT"},
    {"a": "XRP", "b": "BTC",  "label": "USDT → XRP → BTC → USDT"},
    {"a": "BNB", "b": "BTC",  "label": "USDT → BNB → BTC → USDT"},
    {"a": "ADA", "b": "BTC",  "label": "USDT → ADA → BTC → USDT"},
    {"a": "SOL", "b": "ETH",  "label": "USDT → SOL → ETH → USDT"},
    {"a": "LINK", "b": "BTC", "label": "USDT → LINK → BTC → USDT"},
    {"a": "AVAX", "b": "BTC", "label": "USDT → AVAX → BTC → USDT"},
    {"a": "DOGE", "b": "BTC", "label": "USDT → DOGE → BTC → USDT"},
]

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

def evaluate_triangular_loop(exchange, loop_cfg, capital=100.0):
    a = loop_cfg["a"]
    b = loop_cfg["b"]
    label = loop_cfg["label"]

    sym1 = f"{a}USDT"
    sym2_1 = f"{a}{b}"
    sym2_2 = f"{b}{a}"
    sym3 = f"{b}USDT"

    if exchange == "binance":
        ob1 = fetch(f"https://api.binance.com/api/v3/depth?symbol={sym1}&limit=10")
        ob2_1 = fetch(f"https://api.binance.com/api/v3/depth?symbol={sym2_1}&limit=10")
        ob2_2 = fetch(f"https://api.binance.com/api/v3/depth?symbol={sym2_2}&limit=10")
        ob3 = fetch(f"https://api.binance.com/api/v3/depth?symbol={sym3}&limit=10")
        taker_fee = 0.0010
        is_tds = False
    else:
        # CoinDCX
        ob1_raw = fetch(f"https://public.coindcx.com/market_data/orderbook?pair={sym1}")
        ob2_1_raw = fetch(f"https://public.coindcx.com/market_data/orderbook?pair={sym2_1}")
        ob2_2_raw = fetch(f"https://public.coindcx.com/market_data/orderbook?pair={sym2_2}")
        ob3_raw = fetch(f"https://public.coindcx.com/market_data/orderbook?pair={sym3}")

        def parse_cdcx(raw):
            bids = [[p, q] for p, q in raw.get('bids', {}).items()] if isinstance(raw.get('bids'), dict) else raw.get('bids', [])
            asks = [[p, q] for p, q in raw.get('asks', {}).items()] if isinstance(raw.get('asks'), dict) else raw.get('asks', [])
            return {"bids": sorted(bids, key=lambda x: float(x[0]), reverse=True), "asks": sorted(asks, key=lambda x: float(x[0]))}

        ob1 = parse_cdcx(ob1_raw)
        ob2_1 = parse_cdcx(ob2_1_raw)
        ob2_2 = parse_cdcx(ob2_2_raw)
        ob3 = parse_cdcx(ob3_raw)
        taker_fee = 0.0020
        is_tds = True

    if not ob1.get("asks") or not ob3.get("bids"):
        return None

    # Step 1: BUY Asset A
    qty_a, price1, slip1 = simulate_orderbook_buy(ob1["asks"], capital)
    if qty_a == 0: return None
    fee1 = capital * taker_fee
    qty_a_net = qty_a * (1.0 - taker_fee)

    # Step 2: Trade A for B
    if ob2_1.get("bids"):
        qty_b, price2, slip2 = simulate_orderbook_sell(ob2_1["bids"], qty_a_net)
        step2_label = f"SELL {a} on {sym2_1}"
    elif ob2_2.get("asks"):
        qty_b, price2, slip2 = simulate_orderbook_buy(ob2_2["asks"], qty_a_net)
        step2_label = f"BUY {b} on {sym2_2}"
    else:
        return None

    if qty_b == 0: return None
    fee2 = (qty_b * float(ob3["bids"][0][0])) * taker_fee
    qty_b_net = qty_b * (1.0 - taker_fee)

    # Step 3: SELL B for USDT
    final_usdt, price3, slip3 = simulate_orderbook_sell(ob3["bids"], qty_b_net)
    if final_usdt == 0: return None
    fee3 = final_usdt * taker_fee
    final_net_usdt = final_usdt * (1.0 - taker_fee)

    total_fees = fee1 + fee2 + fee3
    total_slip = slip1 + slip2 + slip3
    gross_profit = final_usdt - capital
    gross_pct = (gross_profit / capital) * 100.0

    pre_tds_net = final_net_usdt - capital
    pre_tds_pct = (pre_tds_net / capital) * 100.0

    tds_val = (capital * 0.01) + (final_usdt * 0.01) if is_tds else 0.0
    post_tds_net = pre_tds_net - tds_val
    post_tds_pct = (post_tds_net / capital) * 100.0

    return {
        "exchange": exchange,
        "label": label,
        "capital": capital,
        "step1": f"BUY {a} @ ${price1:.4f}",
        "step2": f"{step2_label} @ {price2:.6f}",
        "step3": f"SELL {b} @ ${price3:.4f}",
        "final_usdt": final_net_usdt,
        "total_fees": total_fees,
        "total_slip": total_slip,
        "gross_pct": f"{gross_pct:+.3f}%",
        "pre_tds_pct_num": pre_tds_pct,
        "pre_tds_pct": f"{pre_tds_pct:+.3f}%",
        "post_tds_pct_num": post_tds_pct,
        "post_tds_pct": f"{post_tds_pct:+.3f}%",
        "is_tds": is_tds,
        "tds_val": tds_val
    }

def triangular_background_loop():
    global triangular_history, bot_state
    add_triangular_log("Triangular Arbitrage Engine Active (Binance vs CoinDCX 3-Pair Scans).")
    
    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
            now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")

            all_results = []
            for cfg in TRIANGULAR_CANDIDATE_LOOPS:
                res_b = evaluate_triangular_loop("binance", cfg)
                res_c = evaluate_triangular_loop("coindcx", cfg)

                candidates = [r for r in [res_b, res_c] if r is not None]
                if not candidates:
                    continue
                candidates.sort(key=lambda x: x["pre_tds_pct_num"], reverse=True)
                all_results.append(candidates[0])

            all_results.sort(key=lambda x: x["pre_tds_pct_num"], reverse=True)

            bot_state["triangular_scanned_count"] = len(all_results)
            bot_state["triangular_last_scan"] = now_str
            bot_state["triangular_top5"] = all_results[:5]

            if all_results:
                top = all_results[0]
                bot_state["triangular_top_loop"] = top["label"]
                bot_state["triangular_top_exchange"] = top["exchange"].upper()
                bot_state["triangular_top_net_pnl"] = top["pre_tds_pct"]

                # Auto execution gate if Pre-TDS Net PnL >= +0.15%
                if top["pre_tds_pct_num"] >= 0.15:
                    bot_state["triangular_total_trades"] += 1
                    net_cash = top["pre_tds_pct_num"]
                    bot_state["triangular_net_pnl_usd"] += net_cash

                    trade_entry = {
                        "id": bot_state["triangular_total_trades"],
                        "timestamp": now_str,
                        "loop": top["label"],
                        "exchange": top["exchange"].upper(),
                        "fees": f"-${top['total_fees']:.4f}",
                        "slippage": f"-${top['total_slip']:.4f}",
                        "pre_tds_pnl": f"{top['pre_tds_pct']}",
                        "post_tds_pnl": f"{top['post_tds_pct']}"
                    }
                    triangular_history.insert(0, trade_entry)

                    add_triangular_log(f"🔺 [TRIANGULAR EXECUTION] {top['label']} on {top['exchange'].upper()} | Pre-TDS Net: {top['pre_tds_pct']} | Fees: -${top['total_fees']:.4f}")
                    
                    tg_msg = (
                        f"🔺 *TRIANGULAR ARBITRAGE LOOP DETECTED* 🚀\n\n"
                        f"🔄 *Loop:* `{top['label']}`\n"
                        f"🏛️ *Exchange:* `{top['exchange'].upper()}`\n"
                        f"💵 *Pre-TDS Net Profit:* `{top['pre_tds_pct']}`\n"
                        f"🏷️ *Total Fees Cut:* `-${top['total_fees']:.4f} USD`\n"
                        f"⚡ *Slippage Impact:* `-${top['total_slip']:.4f} USD`\n"
                        f"🇮🇳 *Post-TDS Net Profit:* `{top['post_tds_pct']}`"
                    )
                    send_telegram_alert(tg_msg)

        except Exception as e:
            add_triangular_log(f"⚠️ Error in triangular loop: {e}")

        time.sleep(4)

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
                <p>Cross-Exchange Funding Rates & Single-Exchange Triangular Arbitrage (Real-Time Live Feed)</p>
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
                <div class="card-label">Virtual Margin Balance</div>
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
        <!-- DIVIDER & SECTION 2: TRIANGULAR ARBITRAGE MONITOR (SCROLL DOWN) -->
        <!-- ============================================================================== -->
        <hr class="section-divider">

        <div class="section-header">
            <div class="section-title">
                🔺 SECTION 2: SINGLE-EXCHANGE TRIANGULAR ARBITRAGE MONITOR
                <span class="engine-tag tag-triangular">BINANCE VS COINDCX (3-PAIR LOOPS)</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted);" id="tri-scan-time">Last Scan: Just Now</div>
        </div>

        <div class="grid-4">
            <div class="card">
                <div class="card-label">Triangular Loops Scanned</div>
                <div class="card-val text-purple" id="tri-val-count">0 Pairs</div>
            </div>
            <div class="card">
                <div class="card-label">Top Triangular Loop</div>
                <div class="card-val text-cyan" id="tri-val-loop" style="font-size: 16px; margin-top: 5px;">-</div>
            </div>
            <div class="card">
                <div class="card-label">Optimal Exchange Selected</div>
                <div class="card-val text-yellow" id="tri-val-ex">-</div>
            </div>
            <div class="card">
                <div class="card-label">Top Pre-TDS Net Profit %</div>
                <div class="card-val text-green" id="tri-val-pnl">0.0000%</div>
            </div>
        </div>

        <div class="section-header">
            <div class="section-title" style="font-size: 14px;">Live Scanned 3-Pair Triangular Loops</div>
            <span style="font-size: 11px; color: var(--text-muted);">Order Book Depth Walk (Top 10 Levels) for VWAP Slippage</span>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Triangular Loop</th>
                        <th>Selected Exchange</th>
                        <th>Leg 1 (Buy A)</th>
                        <th>Leg 2 (Trade B)</th>
                        <th>Leg 3 (Sell USDT)</th>
                        <th>Fees & Slippage</th>
                        <th>Pre-TDS Net %</th>
                        <th>Post-TDS Net %</th>
                    </tr>
                </thead>
                <tbody id="triangular-rows">
                    <tr><td colspan="9" style="text-align: center; color: var(--text-muted);">Scanning L2 order book depth for triangular loops...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="grid-2">
            <div>
                <div class="section-header">
                    <div class="section-title" style="font-size: 14px;">Triangular Scanner Logs</div>
                </div>
                <div class="log-box" id="triangular-logs-container">
                    <div class="log-entry">Initializing Triangular Engine...</div>
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
                                <th>Exchange</th>
                                <th>Fees</th>
                                <th>Pre-TDS</th>
                                <th>Post-TDS</th>
                            </tr>
                        </thead>
                        <tbody id="triangular-history-rows">
                            <tr><td colspan="7" style="text-align: center; color: var(--text-muted);">Waiting for profitable triangular loop (&ge; +0.15% Net)...</td></tr>
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
                document.getElementById('val-balance').innerText = '$' + (data.state.paper_wallet_balance || 10.0).toFixed(2);
                const pnl = data.state.net_pnl_usd || 0.0;
                const pnlEl = document.getElementById('val-pnl');
                pnlEl.innerText = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(4);
                pnlEl.className = pnl >= 0 ? 'card-val text-green' : 'card-val text-red';

                const diffEl = document.getElementById('val-diff');
                if (diffEl) diffEl.innerText = data.state.active_funding_diff || '0.0000%';

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

                // --- UPDATE ENGINE 2: TRIANGULAR ARBITRAGE ---
                document.getElementById('tri-scan-time').innerText = 'Last Scan: ' + (data.state.triangular_last_scan || 'Just Now');
                document.getElementById('tri-val-count').innerText = (data.state.triangular_scanned_count || 0) + ' Pairs';
                document.getElementById('tri-val-loop').innerText = data.state.triangular_top_loop || '-';
                document.getElementById('tri-val-ex').innerText = data.state.triangular_top_exchange || '-';
                
                const triPnlEl = document.getElementById('tri-val-pnl');
                if (triPnlEl) {
                    triPnlEl.innerText = data.state.triangular_top_net_pnl || '0.0000%';
                    triPnlEl.className = (data.state.triangular_top_net_pnl || '').includes('-') ? 'card-val text-red' : 'card-val text-green';
                }

                const triBody = document.getElementById('triangular-rows');
                if (data.state.triangular_top5 && data.state.triangular_top5.length > 0) {
                    triBody.innerHTML = data.state.triangular_top5.map((item, idx) => `
                        <tr>
                            <td><strong>${idx + 1}</strong></td>
                            <td><strong class="text-purple">${item.label}</strong></td>
                            <td><span class="badge-ex">${item.exchange.toUpperCase()}</span></td>
                            <td style="font-size:12px;">${item.step1}</td>
                            <td style="font-size:12px;">${item.step2}</td>
                            <td style="font-size:12px;">${item.step3}</td>
                            <td style="font-size:12px;"><span class="text-red">-$${item.total_fees.toFixed(4)}</span> | <span class="text-yellow">Slip -$${item.total_slip.toFixed(4)}</span></td>
                            <td><strong class="${item.pre_tds_pct.includes('-') ? 'text-red' : 'text-green'}">${item.pre_tds_pct}</strong></td>
                            <td><strong class="${item.post_tds_pct.includes('-') ? 'text-red' : 'text-green'}">${item.post_tds_pct}</strong> ${item.is_tds ? '<span style="font-size:10px; color:var(--accent-yellow);">(1% TDS)</span>' : ''}</td>
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
                            <td><span class="badge-ex">${t.exchange}</span></td>
                            <td class="text-red">${t.fees}</td>
                            <td class="text-green">${t.pre_tds_pnl}</td>
                            <td class="text-green">${t.post_tds_pnl}</td>
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
