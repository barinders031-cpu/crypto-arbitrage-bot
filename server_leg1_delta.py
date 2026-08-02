"""
Render.com 24/7 Host & Web Server for Delta Leg 1 Funding Engine
================================================================
Binds HTTP server to 0.0.0.0:$PORT for Render health checks and hosting.
Runs 24/7 continuous Leg 1 funding engine loop + keep-alive self-ping worker.
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

from delta_leg1_funding_engine import DeltaLeg1Engine, LIVE_EXECUTION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("RenderLeg1Host")

PORT = int(os.getenv("PORT", 10000))
engine = DeltaLeg1Engine(target_notional_usd=float(os.getenv("TARGET_NOTIONAL_USD", 100.0)))


async def handle_health(request):
    """Health check endpoint for Render.com."""
    return web.json_response({
        "status": "ok",
        "service": "Delta Leg 1 Funding Engine",
        "live_execution": engine.live,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    })


async def handle_status(request):
    """Detailed status endpoint returning live funding opportunities and position state."""
    try:
        opps = await engine.scan_delta_funding_rates()
        bal = await engine.fetch_delta_wallet_balance() if engine.live else 100.0
        return web.json_response({
            "status": "active",
            "available_usd_balance": bal,
            "live_mode": engine.live,
            "active_position": engine.active_position,
            "last_funding_hour_executed": engine.last_funding_hour_executed,
            "top_opportunities": opps[:5] if opps else []
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_ping(request):
    """Keep-alive ping endpoint."""
    return web.Response(text="PONG", status=200)


async def self_ping_worker():
    """Background worker that self-pings the server every 5 minutes to prevent Render sleep."""
    await asyncio.sleep(15)  # Wait for web app startup
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

        await asyncio.sleep(240)  # Ping every 4 minutes


async def start_background_tasks(app):
    """Starts background engine loop and self-ping worker on app startup."""
    app["engine_task"] = asyncio.create_task(engine.run_continuous_loop())
    app["ping_task"] = asyncio.create_task(self_ping_worker())


async def cleanup_background_tasks(app):
    """Cleanly closes background tasks on shutdown."""
    app["engine_task"].cancel()
    app["ping_task"].cancel()
    await engine.close()


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
    logger.info(f"🚀 Starting Render.com Web Server for Delta Leg 1 Engine on 0.0.0.0:{PORT}...")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)
