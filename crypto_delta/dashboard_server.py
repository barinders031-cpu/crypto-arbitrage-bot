"""
Delta Exchange India - Hedging Dashboard Server
"""

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crypto_delta.options_scanner import OptionsScanner

app = FastAPI(title="BTC Hedging Terminal")

# Mount static files
static_path = os.path.join(os.path.dirname(__file__), "dashboard")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")

scanner = OptionsScanner()


@app.get("/")
async def dashboard():
    html_path = os.path.join(os.path.dirname(__file__), "dashboard", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/scan")
async def scan():
    """Scan for opportunities."""
    try:
        opportunities = scanner.scan()
        market = scanner.get_market_state()

        return {
            "market": market,
            "opportunities": opportunities,
            "greeks": {
                "delta": 0.0,
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0
            }
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": str(__import__('datetime').datetime.now())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
