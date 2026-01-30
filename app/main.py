import os
import json
import time
from datetime import datetime
from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import JSONResponse

try:
    from app.logic import execute_single_request, process_job_queue, log_to_discord
    from app.database import init_db, add_job
except ImportError:
    from logic import execute_single_request, process_job_queue, log_to_discord
    from database import init_db, add_job

app = FastAPI(title="SuStoolz Zone B Engine")

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "secure-key-123")
DATA_FILE = "data_android.json"
app_data_cache = {}

def load_data():
    global app_data_cache
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                app_data_cache = json.load(f)
        except: pass

@app.on_event("startup")
async def startup_event():
    load_data()
    init_db()

@app.get("/api/get-apps")
async def get_apps(x_api_key: str = Header(None)):
    if x_api_key != INTERNAL_API_KEY: raise HTTPException(status_code=403)
    safe_list = {}
    for name, data in app_data_cache.items():
        if "events" in data:
            safe_list[name] = list(data["events"].keys())
    return safe_list

@app.get("/cron")
async def cron_trigger():
    result = process_job_queue()
    return result

@app.post("/api/internal-execute")
async def internal_execute(
    x_api_key: str = Header(None),
    mode: str = Form(...),
    app_name: str = Form(...),
    platform: str = Form(...),
    device_id: str = Form(...),
    event_name: str = Form(None),
    start_time: str = Form(None),
    delay_min: float = Form(0),
    delay_max: float = Form(0),
    username: str = Form("System")
):
    if x_api_key != INTERNAL_API_KEY: raise HTTPException(status_code=403)
    if app_name not in app_data_cache: return JSONResponse({"status": "error", "message": "App unknown"}, status_code=404)

    target_app_data = app_data_cache[app_name]

    if mode == "single":
        if not event_name or event_name not in target_app_data.get("events", {}):
            return {"status": "error", "message": "Event Token not found"}
            
        code, resp = execute_single_request(
            target_app_data["app_token"], 
            target_app_data["events"][event_name], 
            device_id, platform
        )
        
        log_to_discord("SINGLE EXEC", {"User": username, "App": app_name, "Event": event_name, "Status": code}, "00ff00" if code == 200 else "ff0000")
        return {"success": True, "http_code": code, "server_response": resp}

    elif mode in ["credit_all", "timer"]:
        first_run_ts = time.time()
        if start_time and start_time.strip():
            try:
                dt = datetime.strptime(start_time, "%Y-%m-%dT%H:%M")
                first_run_ts = dt.timestamp()
                log_to_discord("⏳ JOB SCHEDULED", {"User": username, "App": app_name, "Start": start_time}, "ffff00")
            except: pass

        events_dict = target_app_data.get("events", {})
        if not events_dict: return {"status": "error", "message": "No events configured"}

        success = add_job(
            app_name, platform, device_id, target_app_data["app_token"], 
            events_dict, first_run_ts, delay_min, delay_max, username
        )
        
        return {"success": True, "message": "Job queued in Database." if success else "Database Error"}

    return {"status": "error", "message": "Invalid Mode"}