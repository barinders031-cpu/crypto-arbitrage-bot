import time
import os
import sys
import json
import datetime
import sqlite3
import pandas as pd
import logging
import queue
import threading
from angel_client import AngelOneClient
import config

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Suppress noisy HTTP error logs from SmartApi package
logging.getLogger("smartConnect").setLevel(logging.CRITICAL)
logging.getLogger("SmartApi").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

OUTPUT_DIR = "live"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# =============================================================================
# 1. ASYNCHRONOUS WORKER DAEMONS (Siren, CSV Queue & SQLite Harvester)
# =============================================================================
siren_queue = queue.Queue()
csv_queue = queue.Queue()
db_queue = queue.Queue()

def siren_worker():
    """Dedicated background daemon thread for playing sound beeps without blocking main loop."""
    while True:
        task = siren_queue.get()
        if task is None:
            break
        freq, duration = task
        if sys.platform.startswith("win"):
            try:
                import winsound
                winsound.Beep(freq, duration)
            except Exception:
                pass
        siren_queue.task_done()

def csv_writer_worker():
    """Dedicated background daemon thread for non-blocking asynchronous CSV Disk I/O."""
    while True:
        task = csv_queue.get()
        if task is None:
            break
        file_path, data = task
        try:
            if isinstance(data, pd.DataFrame):
                df = data
            else:
                df = pd.DataFrame(data)
            file_exists = os.path.exists(file_path)
            df.to_csv(file_path, mode='a', header=not file_exists, index=False)
        except Exception:
            pass
        finally:
            csv_queue.task_done()

def init_sqlite_db():
    """Initializes high-velocity SQLite database schema for macro data harvesting."""
    db_path = os.path.join(OUTPUT_DIR, "nifty_macro_ticks.db")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS macro_ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                nifty_spot REAL,
                nifty_fut REAL,
                nifty_fut_imbalance_pct REAL,
                nifty_fut_bid_qty INTEGER,
                nifty_fut_ask_qty INTEGER,
                hdfc_spot REAL,
                reliance_spot REAL,
                icici_spot REAL,
                infy_spot REAL,
                tcs_spot REAL,
                ce_cum_oi_change INTEGER,
                pe_cum_oi_change INTEGER,
                pcr_total REAL,
                top_ce_unwinding_strike REAL,
                top_pe_unwinding_strike REAL
            )
        ''')
        conn.commit()
        conn.close()
    except Exception:
        pass

def sqlite_worker():
    """Dedicated background daemon thread for non-blocking high-frequency SQLite tick logging."""
    db_path = os.path.join(OUTPUT_DIR, "nifty_macro_ticks.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    
    while True:
        item = db_queue.get()
        if item is None:
            break
        try:
            cursor.execute('''
                INSERT INTO macro_ticks (
                    timestamp, nifty_spot, nifty_fut, nifty_fut_imbalance_pct,
                    nifty_fut_bid_qty, nifty_fut_ask_qty, hdfc_spot, reliance_spot,
                    icici_spot, infy_spot, tcs_spot, ce_cum_oi_change, pe_cum_oi_change,
                    pcr_total, top_ce_unwinding_strike, top_pe_unwinding_strike
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', item)
            conn.commit()
        except Exception:
            pass
        finally:
            db_queue.task_done()

# Initialize SQLite database schema
init_sqlite_db()

# Launch background worker threads
threading.Thread(target=siren_worker, daemon=True, name="AsyncSirenWorker").start()
threading.Thread(target=csv_writer_worker, daemon=True, name="AsyncCSVWorker").start()
threading.Thread(target=sqlite_worker, daemon=True, name="AsyncSQLiteWorker").start()

def trigger_async_siren(freq=1800, duration=600):
    """Pushes sound task to siren queue instantly and returns control."""
    try:
        siren_queue.put_nowait((freq, duration))
    except queue.Full:
        pass

def enqueue_csv_write(file_path, data):
    """Pushes disk write task to CSV queue instantly and returns control."""
    try:
        csv_queue.put_nowait((file_path, data))
    except queue.Full:
        pass

def enqueue_db_write(record_tuple):
    """Pushes tick data to SQLite harvester queue instantly."""
    try:
        db_queue.put_nowait(record_tuple)
    except queue.Full:
        pass

# =============================================================================
# 2. HELPER FUNCTIONS: GAUGE BUILDER & BUILDUP CLASSIFIER
# =============================================================================
def build_orderbook_gauge(buy_qty, sell_qty, bar_len=14):
    """Constructs a 1-line visual momentum gauge for Order Book Imbalance."""
    total = buy_qty + sell_qty
    if total <= 0:
        return f"Bids [{'░'*bar_len}] Asks | Imbalance: +0.0% (Neutral)", "Neutral"
    
    bid_ratio = buy_qty / total
    green_blocks = int(round(bid_ratio * bar_len))
    green_blocks = max(0, min(bar_len, green_blocks))
    gray_blocks = bar_len - green_blocks
    
    bar = "█" * green_blocks + "░" * gray_blocks
    imbalance_pct = ((buy_qty - sell_qty) / total) * 100.0
    
    if imbalance_pct >= 30.0:
        status_str = "🟢 BIDS DOMINANT"
    elif imbalance_pct <= -30.0:
        status_str = "🔴 ASKS DOMINANT"
    else:
        status_str = "Neutral"
        
    return f"Bids [{bar}] Asks | Imbalance: {imbalance_pct:+.1f}% ({status_str})", status_str

def classify_buildup(price_change, oi_change):
    if price_change > 0 and oi_change > 0:
        return "🟢 LONG BUILDUP", "Bulls Buying / Momentum"
    elif price_change < 0 and oi_change > 0:
        return "🔴 SHORT BUILDUP", "Writers Selling / Resistance-Support"
    elif price_change > 0 and oi_change < 0:
        return "🚀 SHORT COVERING", "Sellers Exiting / Panic Rally Risk"
    elif price_change < 0 and oi_change < 0:
        return "📉 LONG UNWINDING", "Buyers Closing / Profit Taking"
    else:
        return "🟡 NEUTRAL", "Consolidation"

# =============================================================================
# 3. INSTRUMENT & MATRIX RESOLUTION HELPERS
# =============================================================================
def parse_expiry_date(exp_str):
    if not exp_str:
        return datetime.datetime.max
    exp_upper = str(exp_str).upper()
    for fmt in ["%d%b%Y", "%d-%b-%Y", "%Y-%m-%d"]:
        try:
            return datetime.datetime.strptime(exp_upper, fmt)
        except ValueError:
            pass
    return datetime.datetime.max

def get_stock_instruments(scrips, symbol_name):
    spot = None
    futs = []
    opts = []
    
    for scrip in scrips:
        # Spot
        if scrip.get("exch_seg") == "NSE" and (scrip.get("symbol") == f"{symbol_name}-EQ" or scrip.get("symbol") == symbol_name or scrip.get("name") == symbol_name):
            if scrip.get("instrumenttype") in ["", "AMXIDX"]:
                spot = scrip
            elif scrip.get("token") in ["26000", "1333", "2885", "4963", "1594", "11536"]:
                spot = scrip

        # Futures
        if scrip.get("exch_seg") == "NFO" and scrip.get("name") == symbol_name and scrip.get("instrumenttype") in ["FUTIDX", "FUTSTK"]:
            futs.append(scrip)
            
        # Options
        if scrip.get("exch_seg") == "NFO" and scrip.get("name") == symbol_name and scrip.get("instrumenttype") in ["OPTIDX", "OPTSTK"]:
            opts.append(scrip)
            
    fut = None
    if futs:
        futs.sort(key=lambda x: parse_expiry_date(x.get("expiry")))
        fut = futs[0]
        
    return spot, fut, opts

def resolve_atm_options(all_opts, spot_price):
    if not all_opts or not spot_price or spot_price <= 0:
        return None, None
        
    expiry_map = {}
    for o in all_opts:
        exp = o.get("expiry")
        if exp and exp not in expiry_map:
            dt = parse_expiry_date(exp)
            if dt != datetime.datetime.max:
                expiry_map[exp] = dt
    if not expiry_map:
        return None, None
    nearest_exp = min(expiry_map.items(), key=lambda x: x[1])[0]
    
    near_opts = [o for o in all_opts if o.get("expiry") == nearest_exp]
    
    ce_opts = []
    pe_opts = []
    for o in near_opts:
        raw_stk = float(o.get("strike", 0))
        stk = raw_stk / 100.0 if raw_stk > 100000.0 else raw_stk
        sym = str(o.get("symbol", ""))
        if sym.endswith("CE"):
            ce_opts.append((stk, o))
        elif sym.endswith("PE"):
            pe_opts.append((stk, o))
            
    atm_ce = min(ce_opts, key=lambda x: abs(x[0] - spot_price))[1] if ce_opts else None
    atm_pe = min(pe_opts, key=lambda x: abs(x[0] - spot_price))[1] if pe_opts else None
    return atm_ce, atm_pe

def build_multi_expiry_strike_matrix(all_opts, spot_price, num_expiries=1, strike_range=5):
    rounded_spot = round(spot_price / 50.0) * 50.0
    valid_strikes = set([rounded_spot + (i * 50.0) for i in range(-strike_range, strike_range + 1)])
    
    expiry_map = {}
    for o in all_opts:
        exp = o.get("expiry")
        if exp and exp not in expiry_map:
            dt = parse_expiry_date(exp)
            if dt != datetime.datetime.max:
                expiry_map[exp] = dt
            
    sorted_expiries = [k for k, v in sorted(expiry_map.items(), key=lambda item: item[1])][:num_expiries]
    
    matrix_tokens = {}
    for o in all_opts:
        exp = o.get("expiry")
        if exp in sorted_expiries:
            try:
                raw_stk = float(o.get("strike", 0))
                strike = raw_stk / 100.0 if raw_stk > 100000.0 else raw_stk
                if strike in valid_strikes:
                    token = str(o.get("token"))
                    sym = o.get("symbol")
                    opt_type = "CE" if sym.endswith("CE") else ("PE" if sym.endswith("PE") else "UNKNOWN")
                    
                    matrix_tokens[token] = {
                        "token": token,
                        "symbol": sym,
                        "expiry": exp,
                        "strike": strike,
                        "option_type": opt_type
                    }
            except ValueError:
                continue
                
    return matrix_tokens, sorted_expiries

# =============================================================================
# 4. POST-12:00 PM AUTOMATED FORENSIC REPORT GENERATOR
# =============================================================================
def generate_12pm_forensic_report(current_time):
    """Generates Cause-and-Effect Forensic Post-Mortem Report for Morning Session."""
    report_path = os.path.join(OUTPUT_DIR, f"nifty_forensic_report_12PM_{current_time.strftime('%Y%m%d')}.txt")
    db_path = os.path.join(OUTPUT_DIR, "nifty_macro_ticks.db")
    
    if not os.path.exists(db_path):
        return False
        
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("SELECT * FROM macro_ticks", conn)
        conn.close()
        
        if df.empty:
            return False
            
        open_spot = df["nifty_spot"].iloc[0]
        high_spot = df["nifty_spot"].max()
        low_spot = df["nifty_spot"].min()
        curr_spot = df["nifty_spot"].iloc[-1]
        net_change = curr_spot - open_spot
        
        hdfc_chg = (df["hdfc_spot"].iloc[-1] - df["hdfc_spot"].iloc[0]) if "hdfc_spot" in df and len(df) > 1 else 0.0
        rel_chg = (df["reliance_spot"].iloc[-1] - df["reliance_spot"].iloc[0]) if "reliance_spot" in df and len(df) > 1 else 0.0
        icici_chg = (df["icici_spot"].iloc[-1] - df["icici_spot"].iloc[0]) if "icici_spot" in df and len(df) > 1 else 0.0
        infy_chg = (df["infy_spot"].iloc[-1] - df["infy_spot"].iloc[0]) if "infy_spot" in df and len(df) > 1 else 0.0
        tcs_chg = (df["tcs_spot"].iloc[-1] - df["tcs_spot"].iloc[0]) if "tcs_spot" in df and len(df) > 1 else 0.0
        
        hdfc_pts = round(hdfc_chg * 0.115, 2)
        rel_pts = round(rel_chg * 0.098, 2)
        icici_pts = round(icici_chg * 0.078, 2)
        infy_pts = round(infy_chg * 0.058, 2)
        tcs_pts = round(tcs_chg * 0.038, 2)
        
        report_text = f"""--------------------------------------------------------------------------------
🔍 NIFTY MARKET FORENSIC REPORT (Morning Session: 09:15 AM to 12:00 PM)
Generated At: {current_time.strftime('%Y-%m-%d %H:%M:%S')}
--------------------------------------------------------------------------------
📊 MACRO SESSION SUMMARY:
   • Session Open Spot : {open_spot:,.2f}
   • Session High Spot : {high_spot:,.2f}
   • Session Low Spot  : {low_spot:,.2f}
   • 12:00 PM Spot     : {curr_spot:,.2f} (Net Move: {net_change:+.2f} Pts)

🏛️ TOP HEAVYWEIGHTS POINT CONTRIBUTION:
   • HDFC Bank (11.5% Weight) : {hdfc_chg:+.2f} ({hdfc_pts:+.2f} Nifty Pts)
   • Reliance  (9.8% Weight)  : {rel_chg:+.2f} ({rel_pts:+.2f} Nifty Pts)
   • ICICI Bank (7.8% Weight) : {icici_chg:+.2f} ({icici_pts:+.2f} Nifty Pts)
   • Infosys   (5.8% Weight)  : {infy_chg:+.2f} ({infy_pts:+.2f} Nifty Pts)
   • TCS       (3.8% Weight)  : {tcs_chg:+.2f} ({tcs_pts:+.2f} Nifty Pts)

🎯 OPTION WRITER TRAPS & SHORT COVERING:
   • Total CE Cum Change : {df['ce_cum_oi_change'].iloc[-1]:+,} Qty
   • Total PE Cum Change : {df['pe_cum_oi_change'].iloc[-1]:+,} Qty
   • Morning End PCR     : {df['pcr_total'].iloc[-1]:.2f}

--------------------------------------------------------------------------------
"""
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        return True
    except Exception:
        return False

# =============================================================================
# 5. MAIN LIVE TRACKING ENGINE
# =============================================================================
def main():
    client = AngelOneClient()
    if not client.login_with_auto_retry():
        print("[ERROR] Angel One login failed. Check credentials in config.py")
        return

    scrip_path = "scrip_master.json"
    if not os.path.exists(scrip_path):
        print(f"[ERROR] {scrip_path} not found. Triggering download...")
        client.get_token_for_contract("NIFTY")
    
    with open(scrip_path, 'r') as f:
        scrips = json.load(f)
        
    # Resolve Instruments for NIFTY & Top 5 Heavyweights (Avoid API Rate Limits)
    nifty_spot, nifty_fut, nifty_opts = get_stock_instruments(scrips, "NIFTY")
    hdfc_spot, hdfc_fut, _ = get_stock_instruments(scrips, "HDFCBANK")
    rel_spot, rel_fut, _ = get_stock_instruments(scrips, "RELIANCE")
    icici_spot, _, _ = get_stock_instruments(scrips, "ICICIBANK")
    infy_spot, _, _ = get_stock_instruments(scrips, "INFY")
    tcs_spot, _, _ = get_stock_instruments(scrips, "TCS")
    
    if not nifty_spot: nifty_spot = {"token": "26000", "symbol": "NIFTY_SPOT"}
    if not hdfc_spot: hdfc_spot = {"token": "1333", "symbol": "HDFCBANK_SPOT"}
    if not rel_spot: rel_spot = {"token": "2885", "symbol": "RELIANCE_SPOT"}
    if not icici_spot: icici_spot = {"token": "4963", "symbol": "ICICIBANK_SPOT"}
    if not infy_spot: infy_spot = {"token": "1594", "symbol": "INFY_SPOT"}
    if not tcs_spot: tcs_spot = {"token": "11536", "symbol": "TCS_SPOT"}
    
    # Fetch Initial Spot Prices
    spot_req_tokens = [nifty_spot["token"], hdfc_spot["token"], rel_spot["token"], icici_spot["token"], infy_spot["token"], tcs_spot["token"]]
    res = client.get_market_data_throttled("QUOTE", {"NSE": spot_req_tokens})
    
    nifty_ltp, hdfc_ltp, rel_ltp, icici_ltp, infy_ltp, tcs_ltp = 24200.0, 1610.0, 3120.0, 1220.0, 1850.0, 4200.0
    if res.get("status") and "data" in res and res["data"].get("fetched"):
        for item in res["data"]["fetched"]:
            t = str(item.get("symbolToken") or item.get("token"))
            price = float(item.get("ltp", 0.0))
            if t == nifty_spot["token"] and price > 0: nifty_ltp = price
            elif t == hdfc_spot["token"] and price > 0: hdfc_ltp = price
            elif t == rel_spot["token"] and price > 0: rel_ltp = price
            elif t == icici_spot["token"] and price > 0: icici_ltp = price
            elif t == infy_spot["token"] and price > 0: infy_ltp = price
            elif t == tcs_spot["token"] and price > 0: tcs_ltp = price
            
    current_atm_strike = round(nifty_ltp / 50.0) * 50.0
    matrix_tokens, expiries_list = build_multi_expiry_strike_matrix(nifty_opts, nifty_ltp, num_expiries=1, strike_range=5)
    
    # Resolve ATM CE / PE for NIFTY
    nifty_atm_ce, nifty_atm_pe = resolve_atm_options(nifty_opts, nifty_ltp)
    
    primary_nse_tokens = [nifty_spot["token"], hdfc_spot["token"], rel_spot["token"], icici_spot["token"], infy_spot["token"], tcs_spot["token"]]
    primary_nfo_tokens = []
    primary_token_map = {
        nifty_spot["token"]: "NIFTY_SPOT", str(nifty_spot["token"]): "NIFTY_SPOT",
        hdfc_spot["token"]: "HDFCBANK_SPOT", str(hdfc_spot["token"]): "HDFCBANK_SPOT",
        rel_spot["token"]: "RELIANCE_SPOT", str(rel_spot["token"]): "RELIANCE_SPOT",
        icici_spot["token"]: "ICICIBANK_SPOT", str(icici_spot["token"]): "ICICIBANK_SPOT",
        infy_spot["token"]: "INFY_SPOT", str(infy_spot["token"]): "INFY_SPOT",
        tcs_spot["token"]: "TCS_SPOT", str(tcs_spot["token"]): "TCS_SPOT",
    }
    
    # Add Futures & ATM Options to Primary Mapping
    if nifty_fut:
        primary_nfo_tokens.append(nifty_fut["token"])
        primary_token_map[nifty_fut["token"]] = nifty_fut.get("symbol", "NIFTY_FUT")
        primary_token_map[str(nifty_fut["token"])] = nifty_fut.get("symbol", "NIFTY_FUT")
    if hdfc_fut:
        primary_nfo_tokens.append(hdfc_fut["token"])
        primary_token_map[hdfc_fut["token"]] = hdfc_fut.get("symbol", "HDFCBANK_FUT")
    if rel_fut:
        primary_nfo_tokens.append(rel_fut["token"])
        primary_token_map[rel_fut["token"]] = rel_fut.get("symbol", "RELIANCE_FUT")
        
    for opt_inst in [nifty_atm_ce, nifty_atm_pe]:
        if opt_inst:
            primary_nfo_tokens.append(opt_inst["token"])
            primary_token_map[opt_inst["token"]] = opt_inst["symbol"]
            primary_token_map[str(opt_inst["token"])] = opt_inst["symbol"]

    prev_state = {}            # Token -> previous tick state
    initial_oi_state = {}      # Token -> session start baseline OI
    initial_ltp_state = {}     # Token -> session start baseline LTP
    happy_ai_events = []       # AI memory tracker
    spot_history = []          # Rolling buffer for Volatility Events
    last_signal_time = None    # Rate limit siren audio to once per 10s per signal
    report_generated_today = False
    
    ai_memory_file = os.path.join(OUTPUT_DIR, "happy_option_ai_memory.csv")
    oi_matrix_file = os.path.join(OUTPUT_DIR, "nifty_oi_writing_matrix.csv")
    heavyweights_csv = os.path.join(OUTPUT_DIR, "heavyweights_orderbook.csv")
    forensic_log_csv = os.path.join(OUTPUT_DIR, "forensic_event_log.csv")
    
    active_locked_signal = None     # Lock-in state for active trade signal
    signal_candidate = None         # Candidate signal ("CE" or "PE") awaiting persistence
    candidate_signal_tag = "REVERSAL"
    candidate_ticks = 0             # Consecutive tick counter
    nifty_ce_ltp, nifty_pe_ltp = 0.0, 0.0  # Persistent ATM Option LTPs (NEVER ₹0.00)
    
    TARGET_CYCLE_SEC = 2.5     # Strictly locked loop refresh interval
    
    # HFT Anti-Spoofing States
    spoof_tracker = {'bids': {}, 'asks': {}}
    volume_delta_history = []
    prev_nifty_fut_volume = 0
    
    while True:
        loop_start = time.monotonic()
        try:
            timestamp = datetime.datetime.now()
            
            # 1. Fetch Primary Focus Instruments with FULL L2 Depth
            primary_req = {"NSE": primary_nse_tokens, "NFO": primary_nfo_tokens}
            primary_data = client.get_market_data_throttled("FULL", primary_req)
            
            cur_nifty_spot, cur_hdfc_spot, cur_rel_spot = nifty_ltp, hdfc_ltp, rel_ltp
            cur_icici_spot, cur_infy_spot, cur_tcs_spot = icici_ltp, infy_ltp, tcs_ltp
            cur_nifty_fut = nifty_ltp
            
            primary_fetched = []
            if primary_data.get("status") and "data" in primary_data:
                primary_fetched = primary_data["data"].get("fetched", [])
                for item in primary_fetched:
                    t = str(item.get("symbolToken") or item.get("token"))
                    price = float(item.get("ltp", 0.0))
                    if t == nifty_spot["token"] and price > 0: cur_nifty_spot = price
                    elif t == hdfc_spot["token"] and price > 0: cur_hdfc_spot = price
                    elif t == rel_spot["token"] and price > 0: cur_rel_spot = price
                    elif t == icici_spot["token"] and price > 0: cur_icici_spot = price
                    elif t == infy_spot["token"] and price > 0: cur_infy_spot = price
                    elif t == tcs_spot["token"] and price > 0: cur_tcs_spot = price
                    elif nifty_fut and t == nifty_fut["token"] and price > 0: cur_nifty_fut = price

            # Maintain Rolling Spot History for Volatility Event Detection
            spot_history.append((timestamp, cur_nifty_spot))

            # 2. DYNAMIC ATM SHIFT AUTOMATION (NIFTY)
            if cur_nifty_spot and cur_nifty_spot > 0:
                calculated_atm = round(cur_nifty_spot / 50.0) * 50.0
                if calculated_atm != current_atm_strike:
                    current_atm_strike = calculated_atm
                    matrix_tokens, expiries_list = build_multi_expiry_strike_matrix(nifty_opts, cur_nifty_spot, num_expiries=1, strike_range=5)
                    nifty_atm_ce, nifty_atm_pe = resolve_atm_options(nifty_opts, cur_nifty_spot)

            # 3. Fetch Multi-Expiry Nifty Matrix Options in Batches for Option Chain Postmortem
            matrix_token_ids = list(matrix_tokens.keys())
            batch_size = 20
            all_matrix_fetched = []
            
            for i in range(0, len(matrix_token_ids), batch_size):
                batch = matrix_token_ids[i:i+batch_size]
                m_res = client.get_market_data_throttled("FULL", {"NSE": [nifty_spot["token"]], "NFO": batch})
                if m_res.get("status") and "data" in m_res:
                    all_matrix_fetched.extend(m_res["data"].get("fetched", []))
                    
            # Process Option Chain Postmortem & Calculate Dynamic Support / Resistance
            strike_analytics = []
            pe_writing_strikes = []
            ce_writing_strikes = []
            total_ce_oi, total_pe_oi = 0, 0
            total_ce_cum_change, total_pe_cum_change = 0, 0
            top_ce_unwinding_stk = 0.0
            top_pe_unwinding_stk = 0.0
            
            for item in all_matrix_fetched:
                t = str(item.get("symbolToken") or item.get("token"))
                if t not in matrix_tokens:
                    continue
                    
                info = matrix_tokens[t]
                current_oi = int(item.get("opnInterest", 0))
                ltp = float(item.get("ltp", 0.0))
                
                # Direct ATM Option LTP Resolution (Fixes Option LTP ₹0.00 Bug)
                if info["strike"] == current_atm_strike and ltp > 0:
                    if info["option_type"] == "CE":
                        nifty_ce_ltp = ltp
                    elif info["option_type"] == "PE":
                        nifty_pe_ltp = ltp
                
                if t not in initial_oi_state: initial_oi_state[t] = current_oi
                if t not in initial_ltp_state or initial_ltp_state[t] == 0: initial_ltp_state[t] = ltp if ltp > 0 else 1.0
                    
                oi_cum_change = current_oi - initial_oi_state[t]
                ltp_cum_change = ltp - initial_ltp_state[t]
                ltp_pct_change = ((ltp_cum_change / initial_ltp_state[t]) * 100.0) if initial_ltp_state[t] > 0 else 0.0
                
                buildup_code, buildup_desc = classify_buildup(ltp_cum_change, oi_cum_change)
                
                if buildup_code == "🚀 SHORT COVERING" and info["option_type"] == "CE":
                    top_ce_unwinding_stk = info["strike"]
                elif buildup_code == "📉 LONG UNWINDING" and info["option_type"] == "PE":
                    top_pe_unwinding_stk = info["strike"]
                
                info_copy = info.copy()
                info_copy["current_oi"] = current_oi
                info_copy["oi_cum_change"] = oi_cum_change
                info_copy["ltp"] = ltp
                info_copy["ltp_pct_change"] = round(ltp_pct_change, 2)
                info_copy["buildup"] = buildup_code
                strike_analytics.append(info_copy)
                
                if info["option_type"] == "CE":
                    total_ce_oi += current_oi
                    total_ce_cum_change += oi_cum_change
                    if info["strike"] >= current_atm_strike:
                        ce_writing_strikes.append(info_copy)
                elif info["option_type"] == "PE":
                    total_pe_oi += current_oi
                    total_pe_cum_change += oi_cum_change
                    if info["strike"] <= current_atm_strike:
                        pe_writing_strikes.append(info_copy)

            pcr_total = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 1.0

            # Determine Key Dynamic Support & Resistance Levels
            major_support = current_atm_strike - 50.0
            if pe_writing_strikes:
                pe_writing_strikes.sort(key=lambda x: (x["current_oi"], x["oi_cum_change"]), reverse=True)
                major_support = pe_writing_strikes[0]["strike"]

            major_resistance = current_atm_strike + 50.0
            if ce_writing_strikes:
                ce_writing_strikes.sort(key=lambda x: (x["current_oi"], x["oi_cum_change"]), reverse=True)
                major_resistance = ce_writing_strikes[0]["strike"]

            # Process Primary Order Books (Calculate Orderbook Gauge & Collect Backend Data)
            nifty_fut_buy_qty, nifty_fut_sell_qty = 0, 0
            heavy_records = []
            institutional_blocks = []
            
            for item in primary_fetched:
                raw_token = item.get("symbolToken") or item.get("token") or item.get("symboltoken") or item.get("tradingSymbol")
                token_str = str(raw_token) if raw_token is not None else ""
                trading_sym = item.get("tradingSymbol") or item.get("symbol") or ""
                symbol = primary_token_map.get(raw_token) or primary_token_map.get(token_str) or primary_token_map.get(trading_sym) or (trading_sym if trading_sym else f"UNKNOWN_{token_str}")
                ltp = float(item.get("ltp", 0.0))
                oi = int(item.get("opnInterest", 0))
                volume = int(item.get("vtt", item.get("volume", 0)))
                
                buy_depth = item.get("depth", {}).get("buy", [])
                sell_depth = item.get("depth", {}).get("sell", [])
                
                if nifty_atm_ce and (token_str == str(nifty_atm_ce["token"]) or symbol == nifty_atm_ce["symbol"]):
                    nifty_ce_ltp = ltp
                if nifty_atm_pe and (token_str == str(nifty_atm_pe["token"]) or symbol == nifty_atm_pe["symbol"]):
                    nifty_pe_ltp = ltp

                if "NIFTY" in symbol and "FUT" in symbol:
                    # 1. Volume Delta Tracker
                    tick_vol_delta = max(0, volume - prev_nifty_fut_volume) if prev_nifty_fut_volume > 0 else 0
                    prev_nifty_fut_volume = volume
                    volume_delta_history.append((loop_start, tick_vol_delta))
                    volume_delta_history = [x for x in volume_delta_history if loop_start - x[0] <= 5.0]
                    rolling_5s_vol = sum(x[1] for x in volume_delta_history)

                    # 2. Refined Imbalance Processing (Anti-Spoofing)
                    refined_buy_qty, refined_sell_qty = 0, 0
                    
                    # Process Bids
                    current_bid_prices = set()
                    for lvl, b in enumerate(buy_depth):
                        price = float(b.get('price', 0))
                        qty = int(b.get('quantity', 0))
                        current_bid_prices.add(price)
                        weight = 1.0 if lvl < 3 else 0.4
                        
                        if qty >= 5000:
                            if price not in spoof_tracker['bids']:
                                spoof_tracker['bids'][price] = {'qty': qty, 'cycles': 1}
                                if qty >= 10000:
                                    trigger_async_siren(1000, 300) # Deep beep for new 10K+ bid
                            else:
                                spoof_tracker['bids'][price]['cycles'] += 1
                                
                            if qty >= 10000:
                                institutional_blocks.append(f"🟢 BUY SIDE BLOCK: {qty:,} Qty @ ₹{price:,.2f}")
                                
                            # Validity check: Must persist for 3 cycles OR volume must be expanding
                            if spoof_tracker['bids'][price]['cycles'] < 3 and rolling_5s_vol < 1000:
                                qty = 0 # Exclude from refined math (Spoofed Wall)
                        
                        refined_buy_qty += (qty * weight)
                        
                    # Process Asks
                    current_ask_prices = set()
                    for lvl, s in enumerate(sell_depth):
                        price = float(s.get('price', 0))
                        qty = int(s.get('quantity', 0))
                        current_ask_prices.add(price)
                        weight = 1.0 if lvl < 3 else 0.4
                        
                        if qty >= 5000:
                            if price not in spoof_tracker['asks']:
                                spoof_tracker['asks'][price] = {'qty': qty, 'cycles': 1}
                                if qty >= 10000:
                                    trigger_async_siren(1000, 300) # Deep beep for new 10K+ ask
                            else:
                                spoof_tracker['asks'][price]['cycles'] += 1
                                
                            if qty >= 10000:
                                institutional_blocks.append(f"🔴 SELL SIDE BLOCK: {qty:,} Qty @ ₹{price:,.2f}")
                                
                            if spoof_tracker['asks'][price]['cycles'] < 3 and rolling_5s_vol < 1000:
                                qty = 0 # Exclude
                                
                        refined_sell_qty += (qty * weight)
                        
                    # Cleanup old spoof tracker entries
                    spoof_tracker['bids'] = {p: d for p, d in spoof_tracker['bids'].items() if p in current_bid_prices}
                    spoof_tracker['asks'] = {p: d for p, d in spoof_tracker['asks'].items() if p in current_ask_prices}
                    
                    nifty_fut_buy_qty = int(refined_buy_qty)
                    nifty_fut_sell_qty = int(refined_sell_qty)
                    cur_nifty_fut = ltp

                # Async Backend Orderbook Logging (100% UNTOUCHED LOGGING ARCHITECTURE)
                if "FUT" in symbol or symbol in [nifty_fut.get("symbol"), hdfc_fut.get("symbol") if hdfc_fut else "", rel_fut.get("symbol") if rel_fut else ""]:
                    total_buy_qty = sum(int(b.get('quantity', 0)) for b in buy_depth)
                    total_sell_qty = sum(int(s.get('quantity', 0)) for s in sell_depth)
                    imbalance_qty = total_buy_qty - total_sell_qty
                    total_depth_qty = total_buy_qty + total_sell_qty
                    imbalance_pct = ((imbalance_qty / total_depth_qty) * 100.0) if total_depth_qty > 0 else 0.0
                    
                    max_len = max(len(buy_depth), len(sell_depth), 5)
                    fut_row = {
                        "timestamp": timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                        "symbol": symbol,
                        "ltp": ltp,
                        "total_bid_qty": total_buy_qty,
                        "total_ask_qty": total_sell_qty,
                        "imbalance_qty": imbalance_qty,
                        "imbalance_pct": round(imbalance_pct, 2)
                    }
                    for lvl in range(min(max_len, 5)):
                        fut_row[f"L{lvl+1}_bid_price"] = float(buy_depth[lvl].get('price', 0)) if lvl < len(buy_depth) else 0.0
                        fut_row[f"L{lvl+1}_bid_qty"] = int(buy_depth[lvl].get('quantity', 0)) if lvl < len(buy_depth) else 0
                        fut_row[f"L{lvl+1}_bid_orders"] = int(buy_depth[lvl].get('orders', 0)) if lvl < len(buy_depth) else 0
                        fut_row[f"L{lvl+1}_ask_price"] = float(sell_depth[lvl].get('price', 0)) if lvl < len(sell_depth) else 0.0
                        fut_row[f"L{lvl+1}_ask_qty"] = int(sell_depth[lvl].get('quantity', 0)) if lvl < len(sell_depth) else 0
                        fut_row[f"L{lvl+1}_ask_orders"] = int(sell_depth[lvl].get('orders', 0)) if lvl < len(sell_depth) else 0
                        
                    if "NIFTY" in symbol:
                        enqueue_csv_write(os.path.join(OUTPUT_DIR, f"nifty_fut_orderbook_{timestamp.strftime('%Y%m%d')}.csv"), [fut_row])
                    else:
                        heavy_records.append(fut_row)
                        
                prev_state[symbol] = {'volume': volume, 'ltp': ltp}

            # 4. Orderbook Momentum Gauge
            gauge_str, momentum_bias = build_orderbook_gauge(nifty_fut_buy_qty, nifty_fut_sell_qty)
            tot_depth = nifty_fut_buy_qty + nifty_fut_sell_qty
            imbalance_pct = ((nifty_fut_buy_qty - nifty_fut_sell_qty) / tot_depth * 100.0) if tot_depth > 0 else 0.0

            # Async SQLite Tick Harvesting (Non-Blocking Queue Push)
            db_record = (
                timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                cur_nifty_spot, cur_nifty_fut, round(imbalance_pct, 2),
                nifty_fut_buy_qty, nifty_fut_sell_qty,
                cur_hdfc_spot, cur_rel_spot, cur_icici_spot, cur_infy_spot, cur_tcs_spot,
                total_ce_cum_change, total_pe_cum_change, pcr_total,
                top_ce_unwinding_stk, top_pe_unwinding_stk
            )
            enqueue_db_write(db_record)

            # Volatility Event Snapshot Logging (Rolling 3-minute Window)
            cutoff_3m = timestamp - datetime.timedelta(seconds=180)
            valid_hist = [x for x in spot_history if x[0] >= cutoff_3m]
            if len(valid_hist) > 1:
                min_sp = min(x[1] for x in valid_hist)
                max_sp = max(x[1] for x in valid_hist)
                if (max_sp - min_sp) >= 20.0:
                    start_sp = valid_hist[0][1]
                    delta_pts = cur_nifty_spot - start_sp
                    dir_tag = "🟢 RALLY" if delta_pts > 0 else "🔴 DROP"
                    forensic_event = {
                        "timestamp": timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                        "event_type": f"{dir_tag} ({delta_pts:+.1f} Pts)",
                        "nifty_spot": cur_nifty_spot,
                        "fut_imbalance_pct": round(imbalance_pct, 2),
                        "hdfc_spot": cur_hdfc_spot,
                        "reliance_spot": cur_rel_spot,
                        "icici_spot": cur_icici_spot,
                        "infy_spot": cur_infy_spot,
                        "tcs_spot": cur_tcs_spot,
                        "top_ce_unwinding": top_ce_unwinding_stk,
                        "top_pe_unwinding": top_pe_unwinding_stk
                    }
                    enqueue_csv_write(forensic_log_csv, [forensic_event])

            # Post-12:00 PM Forensic Report Trigger
            if timestamp.hour >= 12 and not report_generated_today:
                if generate_12pm_forensic_report(timestamp):
                    report_generated_today = True

            # 5. EXPANDED INSTITUTIONAL SIGNAL ENGINE (BOUNCE + BREAKDOWN/BREAKOUT MOMENTUM)
            now_sec = time.monotonic()
            raw_signal = None
            raw_signal_tag = "REVERSAL"
            raw_siren_freq = 1800
            
            # Anti-Spoofing Cross-Verification Trap Detection
            # Institutional Pillar 2: Intent vs. Reality
            # If imbalance is heavily skewed but actual 5s executed volume is suspiciously low, it's a phantom wall trap.
            buyer_trap = (imbalance_pct >= 50.0) and (rolling_5s_vol < 300)
            seller_trap = (imbalance_pct <= -50.0) and (rolling_5s_vol < 300)
            
            # Institutional Pillar 5: Patience Over Noise (65% Threshold + Macro Level Confluence)
            if not seller_trap and ((cur_nifty_spot <= major_support - 5.0) or (imbalance_pct <= -65.0 and cur_nifty_spot <= (major_support + major_resistance) / 2.0)):
                raw_signal = "PE"
                raw_signal_tag = "SCALPING SIGNAL (BREAKDOWN)"
                raw_siren_freq = 1200
            elif not buyer_trap and ((cur_nifty_spot >= major_resistance + 5.0) or (imbalance_pct >= 65.0 and cur_nifty_spot >= (major_support + major_resistance) / 2.0)):
                raw_signal = "CE"
                raw_signal_tag = "SCALPING SIGNAL (BREAKOUT)"
                raw_siren_freq = 1800
            elif not buyer_trap and (abs(cur_nifty_spot - major_support) <= 15.0) and (imbalance_pct >= 65.0):
                raw_signal = "CE"
                raw_signal_tag = "SCALPING SIGNAL (SUPPORT BOUNCE)"
                raw_siren_freq = 1800
            elif not seller_trap and (abs(cur_nifty_spot - major_resistance) <= 15.0) and (imbalance_pct <= -65.0):
                raw_signal = "PE"
                raw_signal_tag = "SCALPING SIGNAL (RESISTANCE REJECT)"
                raw_siren_freq = 1200
                
            # 2-Cycle Persistence Filter (Signal must hold for 2 consecutive ticks / 5.0s)
            if raw_signal is not None:
                if signal_candidate == raw_signal:
                    candidate_ticks += 1
                else:
                    signal_candidate = raw_signal
                    candidate_signal_tag = raw_signal_tag
                    candidate_ticks = 1
            else:
                signal_candidate = None
                candidate_ticks = 0

            # Signal Lock-In & Cooldown State Machine
            if active_locked_signal is not None:
                elapsed_lock = now_sec - active_locked_signal["start_time"]
                rem_lock = max(0, int(180.0 - elapsed_lock))
                
                curr_opt_price = nifty_ce_ltp if active_locked_signal["type"] == "CE" else nifty_pe_ltp
                target_p = active_locked_signal["target"]
                sl_p = active_locked_signal["sl"]
                
                status_note = f"HOLDING | Lock: {rem_lock}s"
                if curr_opt_price >= target_p and curr_opt_price > 0:
                    status_note = "🎯 TARGET HIT (+10 Pts) - INSTITUTIONAL SCALP SUCCESS!"
                elif curr_opt_price <= sl_p and curr_opt_price > 0:
                    status_note = "🛑 STOPLOSS HIT (-7 Pts) - EXIT TRADE!"
                
                if elapsed_lock >= 180.0:
                    active_locked_signal = None
                    signal_text = "[ SYSTEM STATUS: 🟡 PATIENCE OVER NOISE / WAITING FOR 65% IMBALANCE ]"
                else:
                    opt_type_str = active_locked_signal['type']
                    tag_str = active_locked_signal.get('tag', 'SIGNAL')
                    signal_text = (
                        f"🔒 [ACTIVE {tag_str} LOCKED - {opt_type_str} BUY] ({status_note})\n"
                        f"   👉 ACTION: BUY NIFTY {active_locked_signal['strike']} {opt_type_str} @ ₹{active_locked_signal['entry_price']:.2f} | "
                        f"TARGET: ₹{target_p:.2f} | SL: ₹{sl_p:.2f} | Current LTP: ₹{curr_opt_price:.2f}"
                    )
            else:
                if candidate_ticks >= 2 and signal_candidate is not None:
                    opt_type_str = signal_candidate
                    tag_str = candidate_signal_tag
                    entry_p = nifty_ce_ltp if opt_type_str == "CE" else nifty_pe_ltp
                    target_p = entry_p + 10.0
                    sl_p = max(0.5, entry_p - 7.0)
                    
                    active_locked_signal = {
                        "type": opt_type_str,
                        "tag": tag_str,
                        "strike": int(current_atm_strike),
                        "entry_price": entry_p,
                        "target": target_p,
                        "sl": sl_p,
                        "start_time": now_sec
                    }
                    
                    trigger_async_siren(raw_siren_freq, 600)
                    signal_candidate = None
                    candidate_ticks = 0
                    
                    badge = "🔴" if opt_type_str == "PE" else "🟢"
                    signal_text = (
                        f"{badge} [{tag_str} - {opt_type_str} TRIGGERED]\n"
                        f"   👉 ACTION: BUY NIFTY {int(current_atm_strike)} {opt_type_str} @ ₹{entry_p:.2f} | TARGET: +10 Pts (₹{target_p:.2f}) | SL: -7 Pts (₹{sl_p:.2f})"
                    )
                else:
                    if buyer_trap:
                        signal_text = "[ SYSTEM STATUS: 🟡 BUYER TRAP DETECTED - SPOOFED BIDS (CE SIGNALS SUPPRESSED) ]"
                    elif seller_trap:
                        signal_text = "[ SYSTEM STATUS: 🟡 SELLER TRAP DETECTED - SPOOFED ASKS (PE SIGNALS SUPPRESSED) ]"
                    else:
                        signal_text = "[ SYSTEM STATUS: 🟡 PATIENCE OVER NOISE / WAITING FOR 65% IMBALANCE ]"

            # 6. RENDER DASHBOARD BLUEPRINT (Single Terminal Screen - No Cognitive Overload)
            os.system('cls' if os.name == 'nt' else 'clear')
            print("=" * 80)
            print(f"📊 NIFTY PRO-SCALPER DASHBOARD | [{timestamp.strftime('%Y-%m-%d %H:%M:%S')}]")
            print("=" * 80)
            print(f"SPOT: {cur_nifty_spot:,.2f}  |  FUT: {cur_nifty_fut:,.2f}  |  ATM STRIKE: {int(current_atm_strike):,}")
            print("\n🎯 KEY TRADING LEVELS & INSTITUTIONAL SENTIMENT:")
            print(f"🟢 Major Support  : {int(major_support):,} (Strong Put Writing)")
            print(f"🔴 Major Resistance: {int(major_resistance):,} (Heavy Call Writing)")
            
            if top_ce_unwinding_stk > 0:
                print(f"🔥 Panic Unwinding : {int(top_ce_unwinding_stk):,} CE (Short Covering / Bullish Fuel)")
            elif top_pe_unwinding_stk > 0:
                print(f"🩸 Panic Unwinding : {int(top_pe_unwinding_stk):,} PE (Long Unwinding / Bearish Fuel)")
            else:
                print(f"⚖️ Panic Unwinding : None Detected")
                
            pcr_tag = "Bullish" if pcr_total >= 1.0 else "Bearish"
            print(f"📊 PCR (Put-Call)  : {pcr_total:.2f} ({pcr_tag})")
            print(f"\n⚖️ L2 BOOK MOMENTUM: {gauge_str.replace('Imbalance:', 'Refined Imbalance:')}")
            print(f"📉 OPTION LTP      : {int(current_atm_strike)} CE: ₹{nifty_ce_ltp:.2f}  |  {int(current_atm_strike)} PE: ₹{nifty_pe_ltp:.2f}")
            print("-" * 80)
            print("🚨 ACTIVE LIVE SIGNAL STATUS:")
            print(f"   {signal_text}")
            print("-" * 80)
            
            if institutional_blocks:
                print("🐳 INSTITUTIONAL WHALE BLOCKS DETECTED (L1-L5):")
                for block in institutional_blocks:
                    print(f"   {block}")
                print("-" * 80)
                
            rep_status = "READY" if report_generated_today else "HARVESTING TICKS TO SQLite DB (Triggers @ 12:01 PM)"
            print(f"🔍 MARKET FORENSIC ENGINE: {rep_status}")
            print("-" * 80)
            sys.stdout.flush()

            # Asynchronous Disk Persistence (100% UNTOUCHED LOGGING)
            if heavy_records:
                enqueue_csv_write(heavyweights_csv, heavy_records)

            if strike_analytics:
                matrix_df = pd.DataFrame(strike_analytics)
                matrix_df["timestamp"] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                enqueue_csv_write(oi_matrix_file, matrix_df)

            # Strictly locked 2.5s refresh cycle
            loop_elapsed = time.monotonic() - loop_start
            sleep_duration = max(0.05, TARGET_CYCLE_SEC - loop_elapsed)
            time.sleep(sleep_duration)
            
        except KeyboardInterrupt:
            print("\n[INFO] Gracefully stopped by user. Exiting...")
            break
        except Exception as e:
            time.sleep(2.5)

if __name__ == '__main__':
    main()
