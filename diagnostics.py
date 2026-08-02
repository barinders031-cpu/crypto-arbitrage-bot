import os, json, time, requests
from aiohttp import web

async def diag(request):
    # accept token from header or query param
    token = request.headers.get("x-diag-token") or request.query.get("token")
    if token != os.getenv("DIAG_TOKEN", "delta_hft_diag_2026"):
        return web.Response(text="unauthorized", status=401)

    # sanitized state read
    state = {}
    try:
        with open("bot_state_persistent.json","r") as f:
            s = json.load(f)
            for k,v in s.items():
                if "history" in k.lower(): 
                    continue
                state[k]=v
    except Exception:
        state["error"]="state-read-failed"

    # time and ip
    local_epoch = time.time()
    try:
        ip = requests.get("https://api.ipify.org", timeout=3).text.strip()
    except:
        ip = "ip-fetch-failed"

    try:
        r = requests.get("https://api.india.delta.exchange/v2/tickers/BTCUSD", timeout=5).json()
        delta_ts = int(r.get("result",{}).get("timestamp",0))/1_000_000.0
    except:
        delta_ts = None

    payload = {
        "os": os.uname().sysname if hasattr(os,'uname') else os.name,
        "cwd": os.getcwd(),
        "local_epoch": local_epoch,
        "delta_epoch": delta_ts,
        "time_diff_seconds": (local_epoch - delta_ts) if delta_ts else None,
        "public_ip": ip,
        "env_keys": [k for k in os.environ.keys() if k.upper().startswith(("DELTA_","LIVE_","RENDER","TELEGRAM"))],
        "live_execution": os.getenv("LIVE_EXECUTION","true"),
        "sanitized_state": state
    }
    return web.json_response(payload)

def setup_diag(app):
    app.router.add_get("/_diag", diag)
