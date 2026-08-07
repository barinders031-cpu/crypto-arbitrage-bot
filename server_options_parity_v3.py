"""
Render.com 24/7 Free Web Service Wrapper for Options Parity Bot v3
===================================================================
Binds HTTP web server to 0.0.0.0:$PORT for Render.com health checks.
Runs OptionsParityBotV3 continuously as a background asyncio task.
Includes keep-alive self-pinger to prevent free tier sleep.
"""

import os
import sys
import time
import asyncio
import logging
from aiohttp import web

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from live_order_executor import LiveOrderExecutor, LIVE_EXECUTION
from options_parity_bot_v3 import OptionsParityBotV3, ts_to_ist, get_today_expiry_ts

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s"
)
logger = logging.getLogger("RenderOptionsParityHost")

PORT = int(os.getenv("PORT", 10000))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")

executor = LiveOrderExecutor()
bot = OptionsParityBotV3(executor)

async def handle_health(request):
    mode = "LIVE 🔴" if LIVE_EXECUTION else "PAPER 📄"
    today_exp = ts_to_ist(get_today_expiry_ts())
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Options Parity Bot v3 — Render Host</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0f172a; color: #f8fafc; padding: 20px; }}
        .card {{ background: #1e293b; padding: 20px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 15px; }}
        .status {{ font-size: 1.2em; font-weight: bold; color: #38bdf8; }}
        .badge {{ background: #0284c7; color: white; padding: 4px 8px; border-radius: 4px; font-size: 0.9em; }}
        .green {{ color: #4ade80; }}
    </style>
</head>
<body>
    <h1>🚀 Delta India Options Parity Bot v3</h1>
    <div class="card">
        <div class="status">Status: <span class="green">ACTIVE (24/7 Web Server)</span></div>
        <p><strong>Execution Mode:</strong> <span class="badge">{mode}</span></p>
        <p><strong>Scans Completed:</strong> {bot.scan_count}</p>
        <p><strong>Trades Executed:</strong> {bot.trade_count}</p>
        <p><strong>Total Locked Profit:</strong> ${bot.total_locked_profit:+.4f} USD</p>
        <p><strong>Today's Daily Expiry:</strong> {today_exp}</p>
        <p><strong>Active Positions:</strong> {len(bot.positions)}</p>
    </div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def keep_alive_task():
    """Pings self URL to keep Render Web Service active."""
    await asyncio.sleep(10)
    while True:
        if RENDER_EXTERNAL_URL:
            try:
                async with bot.session.get(RENDER_EXTERNAL_URL, timeout=10) as r:
                    logger.info(f"[KEEP-ALIVE] Self ping to {RENDER_EXTERNAL_URL} -> HTTP {r.status}")
            except Exception as e:
                logger.warning(f"[KEEP-ALIVE] Ping error: {e}")
        await asyncio.sleep(600)  # Ping every 10 minutes


async def start_background_tasks(app):
    app['bot_task'] = asyncio.create_task(bot.run())
    app['ping_task'] = asyncio.create_task(keep_alive_task())

async def cleanup_background_tasks(app):
    app['bot_task'].cancel()
    app['ping_task'].cancel()
    await bot.close_session()


def main():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)

    logger.info(f"[RENDER HOST] Starting Web Service on 0.0.0.0:{PORT}...")
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
