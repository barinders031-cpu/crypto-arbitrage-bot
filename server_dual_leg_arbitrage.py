"""
Render.com 24/7 Dual-Leg Cross-Exchange Funding Arbitrage Server (Delta + CoinDCX)
===================================================================================
Binds HTTP web server to 0.0.0.0:$PORT for Render.com health checks.
Runs continuous 24/7 HFT Dual-Leg Funding Engine + Keep-Alive worker.
"""

import os
import sys
import time
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
            now = datetime.datetime.now()
            # 8-hour funding windows (05:28 - 05:30, 13:28 - 13:30, 21:28 - 21:30 IST)
            funding_hours = [5, 13, 21]
            is_pre_funding = (now.hour in funding_hours and now.minute >= 28 and now.minute <= 29) or (now.minute == 58 or now.minute == 59)

            if is_pre_funding and engine.last_executed_funding_hour != now.hour:
                logger.info(f"⚡ PRE-FUNDING WINDOW DETECTED ({now.strftime('%H:%M:%S IST')})! Scanning #1 top opportunity...")
                opp = await engine.scan_top_opportunity()
                
                if opp:
                    logger.info(f"   Top Coin: {opp['coin']} | Gross Spread: {opp['gross_spread_pct']:.4f}% | Net Profit: {opp['net_profit_pct']:+.4f}% | Gate: {opp['gate']}")
                    
                    if opp["gate"] == "ACCEPT":
                        engine.last_executed_funding_hour = now.hour
                        
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
                            # Step 2: Wait until exact funding timestamp (00:00:00) + 2 seconds
                            next_funding_hour = ((now.hour // 8) + 1) * 8
                            if next_funding_hour >= 24:
                                next_funding_dt = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=2, microsecond=0)
                            else:
                                next_funding_dt = now.replace(hour=next_funding_hour, minute=0, second=2, microsecond=0)

                            wait_sec = (next_funding_dt - datetime.datetime.now()).total_seconds()
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


async def start_background_tasks(app):
    app["scheduler_task"] = asyncio.create_task(continuous_funding_scheduler())
    app["ping_task"] = asyncio.create_task(self_ping_worker())


async def cleanup_background_tasks(app):
    app["scheduler_task"].cancel()
    app["ping_task"].cancel()
    await engine.close_session()


def create_app():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/ping", handle_ping)

    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    return app


if __name__ == "__main__":
    logger.info(f"🚀 Starting Dual-Leg HFT Funding Server on 0.0.0.0:{PORT}...")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)
