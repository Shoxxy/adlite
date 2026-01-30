import os
import json
import time
from datetime import datetime
from fastapi import FastAPI, Form, Header, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

# Imports aus unseren Modulen
try:
    from app.logic import execute_single_request, process_job_queue, log_to_discord
    from app.database import init_db, add_job
except ImportError:
    from logic import execute_single_request, process_job_queue, log_to_discord
    from database import init_db, add_job

app = FastAPI(title="SuStoolz Zone B Engine")

# Env Vars
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "secure-key-123")
DATA_FILE = "data_android.json"
app_data_cache = {}

def load_data():
    """Lädt die App-Konfigurationen"""
    global app_data_cache
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                app_data_cache = json.load(f)
            print(f"Loaded {len(app_data_cache)} apps.")
        except Exception as e:
            print(f"DATA LOAD ERROR: {e}")

@app.on_event("startup")
async def startup_event():
    load_data()
    init_db() # Wichtig: DB initialisieren

@app.get("/")
def index():
    return {"status": "Zone B Operational", "mode": "POCO Engine"}

@app.get("/api/get-apps")
async def get_apps(x_api_key: str = Header(None)):
    """Gibt die Liste der Apps an Zone A (ohne Tokens)"""
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403)
    
    # Safe List erstellen
    safe_list = {}
    for name, data in app_data_cache.items():
        if "events" in data:
            safe_list[name] = list(data["events"].keys())
            
    return safe_list

@app.get("/cron")
async def cron_trigger():
    """
    Dieser Endpunkt muss extern (z.B. UptimeRobot) alle 1-5min aufgerufen werden.
    Er triggert die Abarbeitung der Warteschlange.
    """
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
    start_time: str = Form(None), # Format YYYY-MM-DDTHH:MM
    delay_min: float = Form(0),
    delay_max: float = Form(0),
    username: str = Form("System")
):
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

    if app_name not in app_data_cache:
        return JSONResponse({"status": "error", "message": "App unknown"}, status_code=404)

    target_app_data = app_data_cache[app_name]

    # --- MODE: SINGLE (Sofort) ---
    if mode == "single":
        if not event_name:
            return {"status": "error", "message": "Missing Event Name"}
        
        events = target_app_data.get("events", {})
        if event_name not in events:
            return {"status": "error", "message": "Event Token not found"}
            
        # Ausführen
        code, resp = execute_single_request(
            target_app_data["app_token"], 
            events[event_name], 
            device_id, 
            platform
        )
        
        # Loggen
        log_to_discord("SINGLE MANUAL EXEC", {
            "User": username,
            "App": app_name, 
            "Event": event_name,
            "Status": code
        }, "00ff00" if code == 200 else "ff0000")
        
        return {"success": True, "http_code": code, "server_response": resp}

    # --- MODE: ALL / TIMER (Queue) ---
    elif mode in ["credit_all", "timer"]:
        
        # 1. Startzeit berechnen
        first_run_ts = time.time() # Standard: Sofort
        
        if start_time and start_time.strip():
            try:
                # Versuche Datum zu parsen
                dt = datetime.strptime(start_time, "%Y-%m-%dT%H:%M")
                first_run_ts = dt.timestamp()
                
                # Info Log
                log_to_discord("⏳ JOB SCHEDULED", {
                    "User": username,
                    "App": app_name,
                    "Start": start_time.replace("T", " "),
                    "Mode": mode
                }, "ffff00")
            except:
                pass # Fallback auf sofort

        # 2. Events vorbereiten
        events_dict = target_app_data.get("events", {})
        if not events_dict:
            return {"status": "error", "message": "No events configured for this app"}

        # 3. In Datenbank speichern
        success = add_job(
            app_name, 
            platform, 
            device_id, 
            target_app_data["app_token"], 
            events_dict, 
            first_run_ts,
            delay_min, 
            delay_max, 
            username
        )
        
        if success:
            return {"success": True, "message": "Job in Database queued. Cron will handle execution."}
        else:
            return {"success": False, "message": "Database Error"}

    return {"status": "error", "message": "Invalid Mode"}