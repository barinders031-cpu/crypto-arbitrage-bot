import asyncio
import json
import logging
import math
from datetime import datetime, timedelta
import pandas as pd
import pyotp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import threading
import time

# --- Configuration (Angel One) ---
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # Using existing config for credentials

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SMCDashboard")

app = FastAPI()

# --- Global State ---
market_data = {
    "NIFTY": {"token": "99926000", "exch": "NSE", "candles": [], "running": None},
    "BANKNIFTY": {"token": "99926009", "exch": "NSE", "candles": [], "running": None},
    "SENSEX": {"token": "99919000", "exch": "BSE", "candles": [], "running": None}
}

token_to_symbol = {v["token"]: k for k, v in market_data.items()}

# Signal state
current_signal = {"status": "NO SIGNAL", "details": ""}
state_lock = threading.Lock()

# FastAPI WebSocket Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send initial historical data immediately on connect
        with state_lock:
            payload = {"type": "history", "data": {k: v["candles"] for k, v in market_data.items()}}
        await websocket.send_json(payload)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

# --- Angel One Connection ---
obj = SmartConnect(api_key=config.ANGEL_API_KEY)
totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
data = obj.generateSession(config.ANGEL_CLIENT_ID, config.ANGEL_PASSWORD, totp)

if not data['status']:
    logger.error("Login failed: " + data['message'])
    sys.exit(1)

feed_token = obj.getfeedToken()

# --- Historical Data Fetch ---
def fetch_history(symbol_name, token, exch):
    logger.info(f"Fetching history for {symbol_name}...")
    to_date = datetime.now()
    from_date = to_date - timedelta(days=15)
    
    historicParam = {
        "exchange": exch,
        "symboltoken": token,
        "interval": "FIVE_MINUTE",
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M")
    }
    
    max_retries = 10
    for attempt in range(max_retries):
        try:
            res = obj.getCandleData(historicParam)
            if res.get("status") and res.get("data"):
                candles = []
                for row in res["data"]:
                    # row: [timestamp, open, high, low, close, volume]
                    dt = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%S%z")
                    candles.append({
                        "time": int(dt.timestamp()),
                        "open": row[1],
                        "high": row[2],
                        "low": row[3],
                        "close": row[4]
                    })
                return candles
        except Exception as e:
            if "exceeding access rate" in str(e) or "Access denied" in str(e):
                sleep_time = 2 + attempt
                logger.warning(f"Rate limit hit for {symbol_name}, attempt {attempt+1}/{max_retries}. Sleeping {sleep_time}s...")
                time.sleep(sleep_time)
            else:
                logger.error(f"Error fetching history for {symbol_name}: {e}")
                time.sleep(2)
                
    logger.error(f"Failed to fetch history for {symbol_name} after {max_retries} retries.")
    return []

for sym, info in market_data.items():
    info["candles"] = fetch_history(sym, info["token"], info["exch"])
    time.sleep(3.0) # Rate Limit Safety (3 seconds)

# --- SMC Logic Evaluator ---
def evaluate_smc_logic():
    global current_signal
    # We need at least 2 completed candles to check Order Block retest
    if len(market_data["NIFTY"]["candles"]) < 2 or len(market_data["SENSEX"]["candles"]) < 2:
        return
    
    nifty = market_data["NIFTY"]["candles"]
    sensex = market_data["SENSEX"]["candles"]
    
    n_prev = nifty[-2]
    n_curr = nifty[-1]  # This is the last COMPLETED candle
    
    s_prev = sensex[-2]
    s_curr = sensex[-1]

    # Check Nifty Order Block
    n_body = n_prev["close"] - n_prev["open"]
    n_range = n_prev["high"] - n_prev["low"]
    
    # 1. Bearish Order Block (Red Candle)
    if n_body < -15 and n_range > 30:
        # Retest condition: Current candle goes up to touch previous open, but closes lower
        if n_curr["high"] >= n_prev["open"] and n_curr["close"] < n_prev["open"]:
            # Dual confirmation from Sensex (Sensex must also be bearish in current candle)
            s_body = s_curr["close"] - s_curr["open"]
            if s_body < 0:
                current_signal = {"status": "SELL ALERT", "details": "SMC: Bearish OB Retest Confirmed"}
                return

    # 2. Bullish Order Block (Green Candle)
    if n_body > 15 and n_range > 30:
        # Retest condition: Current candle goes down to touch previous open, but closes higher
        if n_curr["low"] <= n_prev["open"] and n_curr["close"] > n_prev["open"]:
            # Dual confirmation from Sensex
            s_body = s_curr["close"] - s_curr["open"]
            if s_body > 0:
                current_signal = {"status": "BUY ALERT", "details": "SMC: Bullish OB Retest Confirmed"}
                return
                
    current_signal = {"status": "NO SIGNAL", "details": "Waiting for SMC Pattern..."}


# --- Live Tick Resampling ---
def on_data(wsapp, msg):
    if not isinstance(msg, dict) or "token" not in msg:
        return
        
    token = msg["token"]
    if token not in token_to_symbol:
        return
        
    symbol = token_to_symbol[token]
    ltp = msg.get("last_traded_price", 0) / 100.0
    if ltp <= 0: return
    
    exch_time = msg.get("exchange_timestamp", int(time.time() * 1000))
    ts_seconds = exch_time / 1000.0
    
    # Floor to 5 minute boundary (300 seconds)
    # Add 19800 (IST offset) to ensure boundary aligns with 09:15
    period = 300
    candle_time = int(math.floor((ts_seconds + 19800) / period) * period - 19800)
    
    with state_lock:
        running = market_data[symbol]["running"]
        
        if running is None or running["time"] != candle_time:
            # If there's an existing running candle, push it to history
            if running is not None:
                market_data[symbol]["candles"].append(running)
                # Keep max 500 history
                if len(market_data[symbol]["candles"]) > 500:
                    market_data[symbol]["candles"].pop(0)
                
                # Evaluate SMC when a candle completes
                evaluate_smc_logic()
                
            # Create new running candle
            market_data[symbol]["running"] = {
                "time": candle_time,
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp
            }
        else:
            # Update current running candle
            running["high"] = max(running["high"], ltp)
            running["low"] = min(running["low"], ltp)
            running["close"] = ltp

def on_open(wsapp):
    logger.info("Live WebSocket Connected")
    tokens = [{"exchangeType": 1, "tokens": [t]} for t in token_to_symbol.keys()]
    # Access the global sws object
    if 'sws' in globals():
        sws.subscribe("hello", 1, tokens)

def on_error(wsapp, error):
    logger.error(f"Live WS Error: {error}")

def on_close(wsapp, *args):
    logger.info("Live WS Closed")

def start_angel_ws():
    global sws
    sws = SmartWebSocketV2(data["data"]["jwtToken"], config.ANGEL_API_KEY, config.ANGEL_CLIENT_ID, feed_token)
    sws.on_data = on_data
    sws.on_open = on_open
    sws.on_error = on_error
    sws.on_close = on_close
    sws.connect()

# --- Broadcaster ---
async def broadcast_loop():
    while True:
        await asyncio.sleep(1)
        if len(manager.active_connections) > 0:
            with state_lock:
                payload = {
                    "type": "live",
                    "signal": current_signal,
                    "running_candles": {k: v["running"] for k, v in market_data.items() if v["running"] is not None}
                }
            await manager.broadcast(payload)

@app.get("/")
async def get_dashboard():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.on_event("startup")
async def startup_event():
    threading.Thread(target=start_angel_ws, daemon=True).start()
    asyncio.create_task(broadcast_loop())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
