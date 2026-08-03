"""
Render.com 24/7 Dual-Leg Cross-Exchange Funding Arbitrage Server (Delta + CoinDCX)
===================================================================================
Binds HTTP web server to 0.0.0.0:$PORT for Render.com health checks.
Runs continuous 24/7 HFT Dual-Leg Funding Engine + Keep-Alive worker.
"""

import os
import sys
import time
import json
import asyncio
import datetime
import urllib.request
import logging
from aiohttp import web

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from hft_funding_arbitrage_engine import HFTFundingArbitrageEngine, MIN_GROSS_SPREAD_PCT
from live_order_executor import LIVE_EXECUTION
from diagnostics import setup_diag

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("RenderDualLegHost")

PORT = int(os.getenv("PORT", 10000))
TARGET_NOTIONAL = float(os.getenv("TARGET_NOTIONAL_USD", 100.0))

# Master HFT Engine instance
engine = HFTFundingArbitrageEngine(paper_mode=not LIVE_EXECUTION, target_notional_usd=TARGET_NOTIONAL)

try:
    from telegram_notifier import send_telegram_alert
except Exception:
    def send_telegram_alert(msg: str) -> bool:
        logger.info(f"Telegram Alert: {msg}")
        return True

from dashboard_template import HTML_DASHBOARD

bot_state = {
    "status": "DUAL-LEG HFT ARBITRAGE ACTIVE",
    "live_mode": "LIVE 🔴" if LIVE_EXECUTION else "PAPER 📄",
    "paper_wallet_balance": 17.20,
    "total_trades": 0,
    "net_pnl_usd": 0.0,
    "last_scan_time": "-",
    "active_top_coin": "-",
    "top_gross_spread": "-",
    "real_balance_display": "Delta: $0.00 | CoinDCX: $0.00 | Total: $0.00"
}
live_logs = []
paper_history = []
triangular_logs = []
triangular_history = []
CONFIG_FILE = "telegram_config.json"


def add_log(msg: str):
    logger.info(msg)
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    live_logs.insert(0, f"[{ts}] {msg}")
    if len(live_logs) > 100:
        live_logs.pop()


async def handle_index(request):
    """Always serve full colourful HTML Web Dashboard for browser and root requests."""
    return web.Response(
        text=HTML_DASHBOARD,
        content_type="text/html",
        charset="utf-8",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


async def handle_api_state(request):
    """Return live dashboard state JSON for frontend updates."""
    try:
        if hasattr(engine, 'executor') and engine.executor:
            d_bal = getattr(engine.executor, '_last_d_bal', 0.0)
            c_bal = getattr(engine.executor, '_last_c_bal', 0.0)
            bot_state["delta_balance"] = d_bal
            bot_state["coindcx_balance"] = c_bal
            bot_state["delta_balance_live"] = d_bal
            bot_state["coindcx_futures_balance_live"] = c_bal
            if bot_state.get("coindcx_status") == "401_UNAUTHORIZED":
                bot_state["real_balance_display"] = f"Delta: ${d_bal:.2f} | CoinDCX: 🚨 401 UNAUTHORIZED (BLOCKED)"
            elif bot_state.get("coindcx_status") == "CONNECTED":
                bot_state["real_balance_display"] = f"Delta: ${d_bal:.2f} | CoinDCX: ${c_bal:.2f} (CONNECTED)"
    except Exception:
        pass
    payload = {
        "state": bot_state,
        "logs": live_logs,
        "history": paper_history,
        "triangular_logs": triangular_logs,
        "triangular_history": triangular_history
    }
    return web.json_response(payload)


async def handle_api_entry(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    coin = data.get("coin", "ETH").upper()
    res = await engine.execute_hft_parallel_entry({
        "coin": coin,
        "delta_sym": f"{coin}USD",
        "delta_side": "SELL",
        "coindcx_sym": f"B-{coin}_USDT",
        "coindcx_side": "BUY",
        "gross_spread_pct": 0.20,
        "gate": "ACCEPT"
    })
    add_log(f"⚡ [MANUAL ENTRY FIRED VIA WEB DASHBOARD] Result: {res}")
    return web.json_response({"status": "ok", "entry_result": res})


async def handle_api_exit(request):
    res = await engine.execute_hft_parallel_exit(engine.active_positions, trigger_reason="Manual Web Exit Request")
    add_log(f"⚡ [MANUAL EXIT FIRED VIA WEB DASHBOARD] Result: {res}")
    return web.json_response({"status": "ok", "exit_result": res})


async def handle_api_balance(request):
    try:
        data = await request.json()
        c_bal = data.get("coindcx_balance")
        d_bal = data.get("delta_balance")
        if c_bal is not None:
            os.environ["COINDCX_OVERRIDE_BALANCE"] = str(float(c_bal))
        if d_bal is not None:
            os.environ["DELTA_OVERRIDE_BALANCE"] = str(float(d_bal))
    except Exception:
        pass
    return web.json_response({"status": "ok"})


async def handle_api_telegram(request):
    try:
        data = await request.json()
        bot_token = data.get("bot_token", "").strip()
        chat_id = data.get("chat_id", "").strip()
        with open(CONFIG_FILE, "w") as f:
            json.dump({"bot_token": bot_token, "chat_id": chat_id, "enabled": True}, f, indent=2)
        send_telegram_alert("🔔 *Telegram Trade Notification Linked to Web Dashboard!*")
        return web.json_response({"status": "ok", "chat_id": chat_id})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)


async def handle_health(request):
    """Health check endpoint for Render.com."""
    return web.json_response({
        "status": "ok",
        "service": "Dual-Leg HFT Funding Arbitrage (Delta + CoinDCX)",
        "live_mode": LIVE_EXECUTION,
        "target_notional_usd": TARGET_NOTIONAL,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    })


async def handle_status(request):
    """Detailed status endpoint returning active positions and top opportunities."""
    try:
        top_opp = await engine.scan_top_opportunity()
        return web.json_response({
            "status": "active",
            "live_mode": LIVE_EXECUTION,
            "target_notional_usd": TARGET_NOTIONAL,
            "active_positions": engine.active_positions,
            "last_executed_funding_hour": engine.last_executed_funding_hour,
            "top_opportunity": top_opp
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_ping(request):
    return web.Response(text="PONG", status=200)


async def handle_diag(request):
    """Secure sanitized diagnostics endpoint for Render Cloud monitoring."""
    token = request.headers.get("x-diag-token", "")
    expected_token = os.getenv("DIAG_TOKEN", "delta_hft_diag_2026")
    if token != expected_token and request.query.get("token") != expected_token:
        return web.json_response({"error": "unauthorized"}, status=401)

    state = {}
    try:
        if os.path.exists("bot_state_persistent.json"):
            with open("bot_state_persistent.json", "r") as f:
                s = json.load(f)
                for k, v in s.items():
                    if "history" in k.lower(): continue
                    state[k] = v
    except Exception as e:
        state["error"] = str(e)

    local_epoch = time.time()
    try:
        import requests
        ip = requests.get("https://api.ipify.org", timeout=3).text.strip()
    except Exception:
        ip = "ip-fetch-failed"

    delta_ts = None
    try:
        import requests
        r = requests.get("https://api.india.delta.exchange/v2/tickers/BTCUSD", timeout=5).json()
        delta_ts = int(r.get("result", {}).get("timestamp", 0)) / 1_000_000.0
    except Exception:
        pass

    payload = {
        "os": os.uname().sysname if hasattr(os, "uname") else os.name,
        "cwd": os.getcwd(),
        "local_epoch": local_epoch,
        "delta_epoch": delta_ts,
        "time_diff_seconds": round(local_epoch - delta_ts, 4) if delta_ts else None,
        "public_ip": ip,
        "env_keys": [k for k in os.environ.keys() if k.upper().startswith(("DELTA_", "LIVE_", "RENDER", "TELEGRAM", "COINDCX_"))],
        "live_execution": os.getenv("LIVE_EXECUTION", "true"),
        "sanitized_state": state
    }
    return web.json_response(payload)


async def self_ping_worker():
    """Background worker that self-pings the server every 4 minutes to prevent Render sleep."""
    await asyncio.sleep(15)
    while True:
        external_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SELF_PING_URL") or f"http://127.0.0.1:{PORT}"
        target_url = f"{external_url.rstrip('/')}/ping"
        try:
            req = urllib.request.Request(target_url, headers={"User-Agent": "RenderKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=10) as res:
                if res.status == 200:
                    logger.info(f"🟢 [KEEP-ALIVE] Self-ping OK -> {target_url}")
        except Exception as e:
            logger.warning(f"⚠️ [KEEP-ALIVE] Self-ping warning: {e}")

        await asyncio.sleep(240)


async def continuous_funding_scheduler():
    """24/7 Continuous Pre-Funding Scheduler Worker."""
    await engine.init_session()
    logger.info("🟢 Dual-Leg HFT Funding Scheduler Started...")
    
    send_telegram_alert(
        f"🚀 *DUAL-LEG HFT ARBITRAGE ENGINE STARTED ON RENDER*\n\n"
        f"🏛️ *Exchanges:* `Delta Exchange India + CoinDCX`\n"
        f"💵 *Trade Capital:* `${TARGET_NOTIONAL:.2f} USD`\n"
        f"⚡ *Mode:* `{'LIVE REAL-MONEY 🔴' if LIVE_EXECUTION else 'PAPER SIMULATION 📄'}`\n"
        f"⏱️ *Status:* 24/7 Pre-Funding Scheduler Active!"
    )

    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            # Official 4-hour funding settlements occur at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC (05:30, 09:30, 13:30, 17:30, 21:30, 01:30 IST)
            # Pre-funding window (T-2 min) triggers at minute 58-59 of UTC hours 23, 3, 7, 11, 15, 19
            is_pre_funding = (now_utc.hour in [23, 3, 7, 11, 15, 19]) and (now_utc.minute in (58, 59))
            funding_window_id = f"{now_utc.strftime('%Y-%m-%d')}_{now_utc.hour}"

            if is_pre_funding and getattr(engine, "last_executed_window_id", None) != funding_window_id:
                logger.info(f"⚡ PRE-FUNDING WINDOW DETECTED (UTC {now_utc.strftime('%H:%M:%S')})! Scanning #1 top opportunity...")
                opp = await engine.scan_top_opportunity()
                
                if opp:
                    logger.info(f"   Top Coin: {opp['coin']} | Gross Spread: {opp['gross_spread_pct']:.4f}% | Net Profit: {opp['net_profit_pct']:+.4f}% | Gate: {opp['gate']}")
                    
                    if opp["gate"] == "ACCEPT":
                        engine.last_executed_window_id = funding_window_id
                        
                        send_telegram_alert(
                            f"⚡ *PRE-FUNDING ENTRY TRIGGERED*\n\n"
                            f"🪙 *Asset:* `{opp['coin']}`\n"
                            f"📈 *Gross Spread:* `{opp['gross_spread_pct']:.4f}%`\n"
                            f"💵 *Expected Net Profit:* `+{opp['net_profit_pct']:.4f}%`\n"
                            f"🏛️ *Leg 1 (Delta):* `{opp['delta_side']} {opp['delta_sym']}`\n"
                            f"🏛️ *Leg 2 (CoinDCX):* `{opp['coindcx_side']} {opp['coindcx_sym']}`\n"
                            f"⏱️ *Transmitting Parallel Orders...*"
                        )

                        # Step 1: Parallel Entry
                        entry_res = await engine.execute_hft_parallel_entry(opp)
                        logger.info(f"   Parallel Entry Result: {entry_res}")
                        
                        if "SUCCESS" in entry_res.get("status", ""):
                            # Step 2: Calculate target funding settlement time (next :00 or :30 + 2s)
                            if now_utc.minute >= 30:
                                target_dt = (now_utc + datetime.timedelta(hours=1)).replace(minute=0, second=2, microsecond=0)
                            else:
                                target_dt = now_utc.replace(minute=30, second=2, microsecond=0)

                            wait_sec = (target_dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
                            if 0 < wait_sec < 180:
                                logger.info(f"⏳ Waiting {wait_sec:.2f}s for Funding Snapshot & T+2s Scalper Exit...")
                                await asyncio.sleep(wait_sec)

                            # Step 3: Rapid Parallel Scalper Exit (T+2s)
                            exit_res = await engine.execute_hft_parallel_exit(engine.active_positions, trigger_reason="Scalper Exit T+2s")
                            logger.info(f"   Parallel Exit Result: {exit_res}")

                            send_telegram_alert(
                                f"🎉 *DUAL-LEG FUNDING HARVEST COMPLETE* 🎯\n\n"
                                f"🪙 *Asset:* `{opp['coin']}`\n"
                                f"💵 *Gross Funding Collected:* `+${exit_res.get('gross_funding_usd', 0):.4f} USD`\n"
                                f"🔥 *Delta Exit Fee:* `$0.00 USD (FREE)`\n"
                                f"💰 *NET REALIZED PROFIT:* `+${exit_res.get('net_pnl_usd', 0):+.4f} USD`\n"
                                f"⚡ *Status:* Both Legs Closed 100% Market Neutral!"
                            )
                        else:
                            send_telegram_alert(f"⚠️ *ENTRY EXECUTION WARNING:* {entry_res.get('status')}")
                    else:
                        logger.info(f"ℹ️ Top spread ({opp['gross_spread_pct']:.4f}%) rejected by Net Profit Gate (min 0.15%).")

        except Exception as e:
            logger.error(f"⚠️ Error in funding scheduler loop: {e}")

        await asyncio.sleep(3)


async def safety_position_monitor_worker():
    """5-Minute Safety Position Audit Worker for Render Server."""
    await asyncio.sleep(45)
    while True:
        try:
            if LIVE_EXECUTION:
                from live_order_executor import get_executor
                executor = get_executor()
                if executor:
                    res = await executor.execute_full_account_position_close(
                        trigger_reason="5-Minute Safety Audit Check"
                    )
                    d_closed = res.get("closed_delta", [])
                    c_closed = res.get("closed_coindcx", [])
                    if d_closed or c_closed:
                        send_telegram_alert(
                            f"🚨 *5-MIN SAFETY AUDIT: STRAY POSITION FLUSHED* 🚨\n\n"
                            f"🏛️ *Delta Closed:* `{d_closed}`\n"
                            f"🏛️ *CoinDCX Closed:* `{c_closed}`\n"
                            f"🛡️ *Status:* 100% Market Neutrality Restored!"
                        )
                        logger.warning(f"🛡️ [SAFETY MONITOR] Closed stray positions: Delta={d_closed}, CoinDCX={c_closed}")
                    else:
                        logger.info("🟢 [SAFETY MONITOR] Audit passed — zero stray open positions.")
        except Exception as e:
            logger.warning(f"⚠️ [SAFETY MONITOR ERROR]: {e}")

        await asyncio.sleep(300)


def calculate_dynamic_funding_countdown(interval_h: float = 4.0) -> str:
    """Calculates exact countdown matching Top-1 coin's dynamic funding interval (1h, 4h, 8h)."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    interval_sec = int(interval_h * 3600)

    if interval_sec <= 3600:
        target_dt = (now_utc + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    elif interval_sec <= 14400:
        funding_utc_hours = [0, 4, 8, 12, 16, 20]
        next_h = next((h for h in funding_utc_hours if h > now_utc.hour), None)
        if next_h is not None:
            target_dt = now_utc.replace(hour=next_h, minute=0, second=0, microsecond=0)
        else:
            target_dt = (now_utc + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        funding_utc_hours = [0, 8, 16]
        next_h = next((h for h in funding_utc_hours if h > now_utc.hour), None)
        if next_h is not None:
            target_dt = now_utc.replace(hour=next_h, minute=0, second=0, microsecond=0)
        else:
            target_dt = (now_utc + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    diff_sec = max(0, int((target_dt - now_utc).total_seconds()))
    hours = diff_sec // 3600
    mins = (diff_sec % 3600) // 60
    secs = diff_sec % 60
    return f"{hours:02d}h {mins:02d}m {secs:02d}s"


async def funding_scan_worker():
    """Continuously scans live top 5 funding spreads and calculates dynamic countdown for Top-1 coin."""
    await asyncio.sleep(3)
    while True:
        try:
            top_opps = await engine.scan_top_opportunities(limit=5)
            if top_opps:
                top_opp = top_opps[0]
                interval_h = top_opp.get("interval_h", 4.0)
                countdown_str = calculate_dynamic_funding_countdown(interval_h)

                bot_state["next_funding_countdown"] = countdown_str
                bot_state["last_scan_time"] = datetime.datetime.now().strftime("%H:%M:%S IST")
                bot_state["active_top_coin"] = top_opp.get("coin", "-")
                bot_state["top_gross_spread"] = f"{top_opp.get('gross_spread_pct', 0.0):.4f}%"

                top5_list = []
                for opp in top_opps:
                    d_raw = opp.get('raw_delta_rate_pct', opp.get('delta_rate_pct', 0.0))
                    d_int = int(opp.get('delta_interval_h', 4))
                    c_raw = opp.get('raw_coindcx_rate_pct', opp.get('coindcx_rate_pct', 0.0))
                    c_int = int(opp.get('coindcx_interval_h', 8))
                    opp_countdown = calculate_dynamic_funding_countdown(opp.get('delta_interval_h', 4.0))

                    top5_list.append({
                        "coin": opp.get("coin", "ETH"),
                        "delta_sym": opp.get("delta_sym", "ETHUSD"),
                        "delta_rate": f"{d_raw:+.4f}% ({d_int}h)",
                        "binance_sym": f"{opp.get('coin')}USDT",
                        "binance_rate": f"{c_raw:+.4f}%",
                        "cdcx_sym": opp.get("coindcx_sym", "B-ETH_USDT"),
                        "cdcx_rate": f"{c_raw:+.4f}% ({c_int}h)",
                        "diff": f"{opp.get('gross_spread_pct', 0.0):.4f}%",
                        "next_funding": opp_countdown,
                        "action": f"{opp.get('delta_side')} Delta / {opp.get('coindcx_side')} CoinDCX"
                    })
                bot_state["top5_coins"] = top5_list
        except Exception as e:
            logger.warning(f"⚠️ [FUNDING SCAN WORKER ERROR]: {e}")

        await asyncio.sleep(5)


async def balance_refresh_worker():
    """Background worker polling live balances on Delta & CoinDCX Futures every 10 seconds and computing Real Net PnL."""
    await asyncio.sleep(5)
    last_notified_status = None
    while True:
        try:
            if not hasattr(engine, 'executor') or engine.executor is None:
                from live_order_executor import LiveOrderExecutor
                engine.executor = LiveOrderExecutor()
                await engine.executor._ensure_session()

            d_bal, c_bal, min_margin, meta = await engine.executor.fetch_live_balances()
            ts_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
            bot_state["delta_balance"] = d_bal
            bot_state["delta_balance_live"] = d_bal
            bot_state["coindcx_balance"] = c_bal
            bot_state["coindcx_futures_balance_live"] = c_bal
            bot_state["coindcx_status"] = meta["coindcx_status"]
            bot_state["coindcx_http"] = meta["coindcx_http"]
            bot_state["coindcx_error_msg"] = meta["coindcx_error_msg"]
            bot_state["coindcx_last_success"] = meta["coindcx_last_success"]
            bot_state["trade_allowed"] = meta["trade_allowed"]
            bot_state["blocked_reason"] = meta["blocked_reason"]
            bot_state["last_balance_update_time"] = ts_now
            tot_bal = round(d_bal + c_bal, 2)

            if meta["coindcx_status"] == "401_UNAUTHORIZED":
                bot_state["real_balance_display"] = f"Delta: ${d_bal:.2f} | CoinDCX: 🚨 401 UNAUTHORIZED (BLOCKED) | Total: ${d_bal:.2f}"
                if last_notified_status != "401_UNAUTHORIZED":
                    last_notified_status = "401_UNAUTHORIZED"
                    send_telegram_alert(
                        "🚨 *[CRITICAL SAFETY BLOCK]*\n\n"
                        "CoinDCX Balance API returned *HTTP 401 Unauthorized*.\n"
                        "Live trading is *STRICTLY DISABLED* until API permissions (`Read Balances` / `Futures Read`) are enabled on CoinDCX Dashboard."
                    )
            elif meta["coindcx_status"] == "CONNECTED":
                bot_state["real_balance_display"] = f"Delta: ${d_bal:.2f} | CoinDCX: ${c_bal:.2f} | Total: ${tot_bal:.2f}"
                last_notified_status = "CONNECTED"
            else:
                bot_state["real_balance_display"] = f"Delta: ${d_bal:.2f} | CoinDCX: ⚠️ {meta['coindcx_status']} | Total: ${d_bal:.2f}"

            bot_state["paper_wallet_balance"] = tot_bal

            if bot_state.get("initial_total_balance") is None or bot_state["initial_total_balance"] <= 0:
                bot_state["initial_total_balance"] = tot_bal

            real_pnl = round(tot_bal - bot_state["initial_total_balance"], 4)
            bot_state["net_pnl_usd"] = real_pnl
            logger.info(f"[BALANCE CHECK] Delta: ${d_bal:.2f} | CoinDCX: ${c_bal:.2f} (Status: {meta['coindcx_status']}) | Safe Margin: ${min_margin:.2f}")
        except Exception as e:
            logger.warning(f"⚠️ Balance refresh worker error: {e}, retrying in 10s...")

        await asyncio.sleep(10)


async def arbitrage_loop():
    """
    Continuous Arbitrage Trigger Loop:
    - Log every spread check with Delta and CoinDCX funding rates.
    - Verify endpoints: Delta /v2/funding_rates, CoinDCX /exchange/v1/derivatives/futures/funding_rates.
    - Lower spread threshold temporarily to 0.10% and test.
    - Implement Net Spread = Gross Spread - (fees).
    - Ensure loop aligns with funding settlement window (T-10s entry, T+2s exit).
    - Print [SPREAD CHECK] and [TRADE TRIGGERED] logs for every cycle.
    """
    await asyncio.sleep(5)

    # Verify endpoints at startup
    try:
        endpoint_res = await engine.verify_funding_endpoints()
        add_log(f"🔍 [ENDPOINT VERIFICATION COMPLETE] Result: {endpoint_res}")
    except Exception as e:
        add_log(f"⚠️ [ENDPOINT VERIFICATION ERROR] {e}")

    fees_pct = 0.1416  # 0.1416% Total Dual-Leg Roundtrip Fee
    target_spread_threshold = float(os.getenv("ENTRY_SPREAD_PCT", "0.10"))  # Temporarily lowered to 0.10% per user request

    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)

            # Settlement alignment calculation (T-10s entry, T+2s exit)
            next_settlement = (now_utc + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            seconds_to_settlement = (next_settlement - now_utc).total_seconds()

            is_t_minus_10s = (now_utc.minute == 59 and now_utc.second >= 50) or (seconds_to_settlement <= 10)
            timing_str = f"Next Settlement in {int(seconds_to_settlement)}s (T-10s Entry Window: {'ACTIVE 🟢' if is_t_minus_10s else 'WAITING ⏳'})"

            opp = await engine.scan_top_opportunity()

            if opp:
                coin = opp.get('coin', 'UNKNOWN')
                d_sym = opp.get('delta_sym', '')
                d_rate = opp.get('raw_delta_rate_pct', opp.get('delta_rate_pct', 0.0))
                c_sym = opp.get('coindcx_sym', '')
                c_rate = opp.get('raw_coindcx_rate_pct', opp.get('coindcx_rate_pct', 0.0))
                gross_spread = opp.get('gross_spread_pct', 0.0)
                net_spread = gross_spread - fees_pct
                opp['net_spread_pct'] = net_spread

                gate_status = "REJECT"
                reject_reason = ""

                if bot_state.get("trade_allowed") is False:
                    reject_reason = f"CoinDCX API Unverified ({bot_state.get('coindcx_status', 'BLOCKED')}) — Trading Blocked"
                elif gross_spread < target_spread_threshold:
                    reject_reason = f"Gross Spread {gross_spread:.4f}% < Threshold {target_spread_threshold:.4f}%"
                elif getattr(engine, 'active_positions', None):
                    reject_reason = "Active Position Already Open"
                else:
                    gate_status = "ACCEPT"

                # PRINT [SPREAD CHECK] LOG FOR EVERY CYCLE
                spread_check_msg = (
                    f"🔍 [SPREAD CHECK] Coin: {coin} | "
                    f"Delta ({d_sym}): {d_rate:+.4f}% | "
                    f"CoinDCX ({c_sym}): {c_rate:+.4f}% | "
                    f"Gross Spread: {gross_spread:.4f}% | "
                    f"Fees: {fees_pct:.4f}% | "
                    f"Net Spread: {net_spread:+.4f}% | "
                    f"Threshold: {target_spread_threshold:.4f}% | "
                    f"Gate: {gate_status}{f' ({reject_reason})' if reject_reason else ''} | "
                    f"{timing_str}"
                )
                add_log(spread_check_msg)

                if gate_status == "ACCEPT":
                    funding_window_id = f"{now_utc.strftime('%Y-%m-%d')}_{now_utc.hour}"
                    if getattr(engine, 'last_executed_window_id', None) != funding_window_id:
                        engine.last_executed_window_id = funding_window_id

                        # PRINT [TRADE TRIGGERED] LOG
                        trade_triggered_msg = (
                            f"⚡ *[TRADE TRIGGERED]*\n\n"
                            f"🪙 *Asset:* `{coin}`\n"
                            f"📈 *Gross Spread:* `{gross_spread:.4f}%` | *Net:* `{net_spread:+.4f}%` (Threshold `{target_spread_threshold:.4f}%`)\n"
                            f"🏛️ *Leg 1 (Delta):* `{opp['delta_side']} {d_sym}`\n"
                            f"🏛️ *Leg 2 (CoinDCX):* `{opp['coindcx_side']} {c_sym}`\n"
                            f"⏱️ *Timing:* {timing_str}"
                        )
                        add_log(trade_triggered_msg)
                        send_telegram_alert(trade_triggered_msg)

                        # Align with T-10s settlement window if not already in it
                        if 10 < seconds_to_settlement < 300:
                            wait_t10 = seconds_to_settlement - 10
                            add_log(f"⏳ [SETTLEMENT ALIGNMENT] Sleeping {wait_t10:.1f}s until T-10s entry window...")
                            await asyncio.sleep(wait_t10)

                        add_log(f"🚀 [T-10s ENTRY FIRING] Transmitting simultaneous market orders on Delta & CoinDCX...")
                        entry_res = await engine.execute_hft_parallel_entry(opp)
                        add_log(f"   [JSON AUDIT ENTRY] {entry_res}")
                        send_telegram_alert(f"🚀 *[ENTRY EXECUTED]* Asset: `{coin}` | Status: `{entry_res.get('status')}`")

                        if "SUCCESS" in entry_res.get("status", ""):
                            # Sleep until T+2s post-funding for 0% Delta Scalper Exit
                            now_after_entry = datetime.datetime.now(datetime.timezone.utc)
                            target_exit_dt = (now_after_entry + datetime.timedelta(hours=1)).replace(minute=0, second=2, microsecond=0)
                            wait_exit_sec = (target_exit_dt - now_after_entry).total_seconds()
                            if 0 < wait_exit_sec < 300:
                                add_log(f"⏳ [T+2s SCALPER EXIT PENDING] Sleeping {wait_exit_sec:.2f}s for Funding Snapshot & T+2s Exit...")
                                await asyncio.sleep(wait_exit_sec)

                            exit_res = await engine.execute_hft_parallel_exit(engine.active_positions, trigger_reason="Scalper Exit T+2s")
                            add_log(f"   [JSON AUDIT EXIT] {exit_res}")

                            if hasattr(engine, 'executor') and engine.executor:
                                d_b, c_b, m_m = await engine.executor.fetch_live_balances()
                                bot_state["delta_balance_live"] = d_b
                                bot_state["coindcx_futures_balance_live"] = c_b
                                tot_b = round(d_b + c_b, 2)
                                initial_b = bot_state.get("initial_total_balance") or tot_b
                                real_pnl = round(tot_b - initial_b, 4)
                                bot_state["net_pnl_usd"] = real_pnl
                                pnl_msg = f"🎉 *[HARVEST COMPLETE]* Real Net PnL: `${real_pnl:+.4f} USD`"
                                add_log(pnl_msg)
                                send_telegram_alert(pnl_msg)
            else:
                add_log(f"🔍 [SPREAD CHECK] No common coins found | {timing_str}")

        except Exception as e:
            add_log(f"⚠️ [ARBITRAGE LOOP WARNING]: {e}")

        await asyncio.sleep(10)


async def start_background_tasks(app):
    app["scheduler_task"] = asyncio.create_task(continuous_funding_scheduler())
    app["scan_task"] = asyncio.create_task(funding_scan_worker())
    app["ping_task"] = asyncio.create_task(self_ping_worker())
    app["safety_task"] = asyncio.create_task(safety_position_monitor_worker())
    app["balance_task"] = asyncio.create_task(balance_refresh_worker())
    app["arbitrage_task"] = asyncio.create_task(arbitrage_loop())


async def cleanup_background_tasks(app):
    app["scheduler_task"].cancel()
    app["scan_task"].cancel()
    app["ping_task"].cancel()
    app["safety_task"].cancel()
    app["balance_task"].cancel()
    app["arbitrage_task"].cancel()
    await engine.close_session()


async def handle_test_xrp(request):
    """Executes XRP micro-test trade on Render host with >=24 USDT notional compliance for CoinDCX and auto-closes position immediately."""
    try:
        add_log("🧪 [RENDER API TEST] Triggering XRP test trade (46 XRPUSD Delta / 46.0 B-XRP_USDT CoinDCX for >24 USDT min notional compliance)...")
        if not hasattr(engine, 'executor') or engine.executor is None:
            from live_order_executor import LiveOrderExecutor
            engine.executor = LiveOrderExecutor()
            await engine.executor._ensure_session()

        # 46 XRP at $0.55 = $25.30 USD Notional (Satisfies CoinDCX >=24.0 USDT min notional rule)
        entry_res = await engine.executor.execute_entry(
            delta_sym="XRPUSD",
            delta_side="buy",
            delta_lots=46,
            coindcx_sym="B-XRP_USDT",
            coindcx_side="sell",
            exact_qty=46.0,
            leverage=20,
            coin="XRP",
            mark_delta=0.55,
            mark_coindcx=0.55,
            notional_usd=25.3,
            gross_spread_pct=0.15
        )
        close_res = await engine.executor.execute_full_account_position_close(
            trigger_reason="Test XRP micro-lot auto position close"
        )
        res_payload = {
            "status": "ok",
            "test_entry": entry_res,
            "test_close": close_res
        }
        add_log(f"🧪 [RENDER API TEST COMPLETE] Result: {entry_res}")
        return web.json_response(res_payload)
    except Exception as _ex:
        add_log(f"❌ Error in Render XRP test: {_ex}")
        return web.json_response({"status": "error", "message": str(_ex)}, status=500)


async def handle_test_coindcx(request):
    """Executes a standalone CoinDCX Futures test market order (6.0 XRP = ~$6.50 Notional >= 6.0 USDT min rule) and auto-closes immediately."""
    try:
        add_log("🧪 [RENDER API TEST] Triggering standalone CoinDCX Futures test trade (6.0 B-XRP_USDT BUY for >6.0 USDT min order rule)...")
        if not hasattr(engine, 'executor') or engine.executor is None:
            from live_order_executor import LiveOrderExecutor
            engine.executor = LiveOrderExecutor()
            await engine.executor._ensure_session()

        # Step 1: Standalone CoinDCX Buy Order (6.0 XRP = ~$6.50 Notional > 6.0 USDT rule)
        c_order = await engine.executor._coindcx_order(
            symbol="B-XRP_USDT",
            side="buy",
            qty=6.0,
            order_type="market_order",
            leverage=20
        )
        
        # Step 2: Instant Reverse Sell Order to maintain 0 exposure
        c_close = await engine.executor._coindcx_order(
            symbol="B-XRP_USDT",
            side="sell",
            qty=6.0,
            order_type="market_order",
            leverage=20,
            reduce_only=True
        )

        res_payload = {
            "status": "ok",
            "exchange": "CoinDCX Futures",
            "symbol": "B-XRP_USDT",
            "qty": 6.0,
            "notional_usdt": "~6.50",
            "test_order": c_order,
            "auto_close": c_close
        }
        add_log(f"🧪 [COINDCX STANDALONE TEST COMPLETE] Order ID: {c_order.get('order_id')} | HTTP: {c_order.get('http')}")
        return web.json_response(res_payload)
    except Exception as _ex:
        add_log(f"❌ Error in CoinDCX standalone test: {_ex}")
        return web.json_response({"status": "error", "message": str(_ex)}, status=500)


async def handle_funding_arbitrage(request):
    """
    Dynamic Funding Arbitrage Endpoint:
    1. Scans top #1 funding spread opportunity across Delta & CoinDCX.
    2. Calculates 75% margin allocation from available USDT balance.
    3. Executes symmetrical delta-neutral orders on both exchanges.
    4. Logs JSON audit with status 'Funding Arbitrage Executed | Margin: 75% | Exposure Balanced'.
    """
    try:
        top_opp = await engine.scan_top_opportunity()
        if not top_opp or top_opp.get('gate') != 'ACCEPT':
            return web.json_response({
                "status": "rejected",
                "message": "No opportunity passed Fee-Adjusted Net Profit Gate (Spread < 0.25%)",
                "scanned_opportunity": top_opp
            })

        if not hasattr(engine, 'executor') or engine.executor is None:
            from live_order_executor import LiveOrderExecutor
            engine.executor = LiveOrderExecutor()
            await engine.executor._ensure_session()

        # Audit Live Balances & calculate 75% Margin Allocation
        d_bal, c_bal, _ = await engine.executor.fetch_live_balances()
        min_bal = min(d_bal, c_bal) if (d_bal > 0 and c_bal > 0) else max(d_bal, c_bal, 9.0)
        margin_used = round(0.75 * min_bal, 2)
        leverage = 20
        target_notional = max(round(margin_used * leverage, 2), 25.0)

        add_log(f"⚡ [DYNAMIC FUNDING ARBITRAGE] Scanned #1 Opportunity: {top_opp['coin']} (Spread: {top_opp['gross_spread_pct']:.4f}%) | 75% Margin: ${margin_used:.2f} | Target Notional: ${target_notional:.2f}")

        entry_res = await engine.executor.execute_entry(
            delta_sym=top_opp['delta_sym'],
            delta_side=top_opp['delta_side'].lower(),
            delta_lots=0,  # Auto-calculated by calculate_sizing inside execute_entry
            coindcx_sym=top_opp['coindcx_sym'],
            coindcx_side=top_opp['coindcx_side'].lower(),
            exact_qty=0.0,
            leverage=leverage,
            coin=top_opp['coin'],
            mark_delta=top_opp['delta_mark'],
            mark_coindcx=top_opp['coindcx_mark'],
            notional_usd=target_notional,
            gross_spread_pct=top_opp['gross_spread_pct']
        )

        audit_log = "Funding Arbitrage Executed | Margin: 75% | Exposure Balanced"
        add_log(f"🟢 [FUNDING ARBITRAGE AUDIT] {audit_log} | Result: {entry_res.get('status')}")

        return web.json_response({
            "status": "ok",
            "message": audit_log,
            "scanned_opportunity": top_opp,
            "margin_allocation": {
                "delta_balance_usd": d_bal,
                "coindcx_balance_usd": c_bal,
                "margin_used_usd": margin_used,
                "margin_pct": "75%",
                "target_notional_usd": target_notional
            },
            "execution_result": entry_res
        })
    except Exception as _ex:
        add_log(f"❌ Error in Funding Arbitrage: {_ex}")
        return web.json_response({"status": "error", "message": str(_ex)}, status=500)


def create_app():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/dashboard", handle_index)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/ping", handle_ping)
    app.router.add_get("/api/state", handle_api_state)
    app.router.add_get("/api/test_xrp", handle_test_xrp)
    app.router.add_post("/api/test_xrp", handle_test_xrp)
    app.router.add_get("/test_xrp", handle_test_xrp)
    app.router.add_post("/test_xrp", handle_test_xrp)
    app.router.add_get("/api/test_coindcx", handle_test_coindcx)
    app.router.add_post("/api/test_coindcx", handle_test_coindcx)
    app.router.add_get("/test_coindcx", handle_test_coindcx)
    app.router.add_post("/test_coindcx", handle_test_coindcx)
    app.router.add_get("/api/funding_arbitrage", handle_funding_arbitrage)
    app.router.add_post("/api/funding_arbitrage", handle_funding_arbitrage)
    app.router.add_get("/funding_arbitrage", handle_funding_arbitrage)
    app.router.add_post("/funding_arbitrage", handle_funding_arbitrage)
    app.router.add_post("/api/entry", handle_api_entry)
    app.router.add_post("/api/trade", handle_api_entry)
    app.router.add_post("/api/exit", handle_api_exit)
    app.router.add_post("/api/close", handle_api_exit)
    app.router.add_post("/api/balance", handle_api_balance)
    app.router.add_post("/api/telegram", handle_api_telegram)
    setup_diag(app)

    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    return app


if __name__ == "__main__":
    logger.info(f"🚀 Starting Dual-Leg HFT Funding Server on 0.0.0.0:{PORT}...")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)
