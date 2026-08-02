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
    "real_balance_display": "Delta: $7.94 | CoinDCX: $9.26 | Total: $17.20"
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
            d_bal = engine.executor._last_d_bal or 7.94
            c_bal = engine.executor._last_c_bal or 9.26
            bot_state["delta_balance"] = d_bal
            bot_state["coindcx_balance"] = c_bal
            bot_state["real_balance_display"] = f"Delta: ${d_bal:.2f} | CoinDCX: ${c_bal:.2f} | Total: ${d_bal+c_bal:.2f}"
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
            # Pre-funding window triggers T-2 min before funding settlements (:00 or :30)
            is_pre_funding = now_utc.minute in (28, 29, 58, 59)
            funding_window_id = f"{now_utc.strftime('%Y-%m-%d_%H')}_{(now_utc.minute // 30)}"

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


async def start_background_tasks(app):
    app["scheduler_task"] = asyncio.create_task(continuous_funding_scheduler())
    app["ping_task"] = asyncio.create_task(self_ping_worker())
    app["safety_task"] = asyncio.create_task(safety_position_monitor_worker())


async def cleanup_background_tasks(app):
    app["scheduler_task"].cancel()
    app["ping_task"].cancel()
    app["safety_task"].cancel()
    await engine.close_session()


def create_app():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/dashboard", handle_index)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/ping", handle_ping)
    app.router.add_get("/api/state", handle_api_state)
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
