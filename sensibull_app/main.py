from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import random
import math

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from typing import Optional

@app.get("/api/options_data")
def get_options_data(
    strikes_count: Optional[int] = None, 
    min_strike: Optional[int] = None, 
    max_strike: Optional[int] = None,
    interval: str = 'fullday'
):
    # Simulated Nifty spot price
    spot_price = 23205.20
    # Calculate ATM (nearest 50)
    atm_strike = round(spot_price / 50) * 50
    
    # Determine the range of strikes to generate
    start_strike = atm_strike - (10 * 50)
    end_strike = atm_strike + (10 * 50)
    
    if min_strike is not None and max_strike is not None:
        start_strike = min_strike
        end_strike = max_strike
    elif strikes_count is not None:
        start_strike = atm_strike - (strikes_count * 50)
        end_strike = atm_strike + (strikes_count * 50)
        
    # Scale changes based on interval
    interval_scale = 1.0
    if interval == '5m': interval_scale = 0.05
    elif interval == '10m': interval_scale = 0.1
    elif interval == '15m': interval_scale = 0.15
    elif interval == '30m': interval_scale = 0.3
    elif interval == '1h': interval_scale = 0.5
    elif interval == '2h': interval_scale = 0.7
    elif interval == '3h': interval_scale = 0.85
    
    data = []
    # Generate data within the strict bounds
    current_strike = start_strike
    while current_strike <= end_strike:
        distance = abs(current_strike - atm_strike) / 50
        
        # Max base OI around 1.5 - 2 Crores
        max_oi = 20000000 
        decay_factor = max(0.1, 1 - (distance * 0.05))
        base_multiplier = int(max_oi * decay_factor)
        
        # --- PUT (PE) Logic ---
        pe_base_oi = int(random.uniform(0.3, 1.0) * base_multiplier)
        if current_strike < atm_strike: # OTM for PE
             pe_base_oi = int(pe_base_oi * random.uniform(1.2, 1.8))
             
        # Calculate change and scale it down for smaller intervals
        if random.random() > 0.3:
            raw_change = pe_base_oi * random.uniform(0.05, 0.4)
            pe_current_oi = int(pe_base_oi + (raw_change * interval_scale))
        else:
            raw_change = pe_base_oi * random.uniform(0.05, 0.4)
            pe_current_oi = int(pe_base_oi - (raw_change * interval_scale))
            pe_current_oi = max(0, pe_current_oi) # Prevent negative OI

        # --- CALL (CE) Logic ---
        ce_base_oi = int(random.uniform(0.3, 1.0) * base_multiplier)
        if current_strike > atm_strike: # OTM for CE
             ce_base_oi = int(ce_base_oi * random.uniform(1.2, 1.8))
             
        if random.random() > 0.3:
            raw_change = ce_base_oi * random.uniform(0.05, 0.4)
            ce_current_oi = int(ce_base_oi + (raw_change * interval_scale))
        else:
            raw_change = ce_base_oi * random.uniform(0.05, 0.4)
            ce_current_oi = int(ce_base_oi - (raw_change * interval_scale))
            ce_current_oi = max(0, ce_current_oi)

        data.append({
            "strike": current_strike,
            "pe": {
                "base_oi": pe_base_oi,
                "current_oi": pe_current_oi,
                "change": pe_current_oi - pe_base_oi
            },
            "ce": {
                "base_oi": ce_base_oi,
                "current_oi": ce_current_oi,
                "change": ce_current_oi - ce_base_oi
            }
        })
        current_strike += 50
        
    return {
        "spot_price": spot_price,
        "atm_strike": atm_strike,
        "india_vix": 14.52,
        "pcr": 0.92,
        "timestamp": "12:10 PM",
        "strikes": data
    }

# Mount static folder at the root
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Start the server
    uvicorn.run(app, host="127.0.0.1", port=8000)
