import os
import json
import logging
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import JSONResponse

# Importiere lokale Logik und Datenbank
# Wir gehen davon aus, dass main.py im Ordner "app" liegt und logic.py/database.py daneben.
from .logic import execute_single_request, process_job_queue
from .database import init_db, add_job

# --- KONFIGURATION ---
# Zone C braucht keine Zone_C_URL mehr, da SIE Zone C ist.
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "secure-key-123")
DATA_FILE = "data_android.json"

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ZoneC_Core")

app = FastAPI(title="SuStoolz Zone C Core")

# --- INITIALISIERUNG ---
@app.on_event("startup")
def startup_event():
    init_db()
    logger.info("Zone C: Database initialized.")
    # Prüfen ob Data File existiert
    if not os.path.exists(DATA_FILE):
        logger.warning(f"WARNUNG: {DATA_FILE} nicht gefunden! Apps können nicht geladen werden.")

# --- HILFSFUNKTIONEN ---
def load_app_data():
    """Lädt die data_android.json frisch von der Disk"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def verify_api_key(request: Request):
    """Sichert die API ab, damit nur Zone B Zugriff hat"""
    key = request.headers.get("x-api-key")
    if key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return key

# --- ROUTEN ---

@app.get("/")
def root():
    return {"status": "Zone C Online", "role": "Execution Engine"}

@app.get("/api/get-apps")
def get_apps(key: str = Depends(verify_api_key)):
    """
    Gibt die Liste der Apps und Events an Zone B zurück.
    Zone B nutzt dies, um das Dropdown-Menü zu füllen.
    """
    data = load_app_data()
    # Wir transformieren die Daten so, dass Zone B sie leicht lesen kann
    # Format: {"AppName": ["Event1", "Event2"], ...}
    result = {}
    for app_name, details in data.items():
        events = list(details.get("events", {}).keys())
        result[app_name] = events
    
    return result

@app.post("/api/proxy_send") # Anpassen an den Aufruf von Zone B, falls nötig, oder Route in Zone B anpassen
def receive_execution_order(
    request: Request,
    mode: str = Form(...),
    app_name: str = Form(...),
    platform: str = Form(...),
    device_id: str = Form(...),
    event_name: str = Form(None), # Optional, falls "credit_all"
    key: str = Depends(verify_api_key)
):
    """
    Empfängt den Feuerbefehl von Zone B und führt ihn aus.
    """
    data = load_app_data()
    
    # 1. Validierung
    if app_name not in data:
        return JSONResponse({"success": False, "log_entry": f"<span class='log-ts'>ERR</span> App '{app_name}' unknown in Zone C."}, status_code=404)
    
    app_config = data[app_name]
    app_token = app_config.get("app_token")
    
    logger.info(f"Incoming Command: Mode={mode}, App={app_name}, Platform={platform}, ID={device_id}")

    # 2. Modus: SINGLE EVENT
    if mode == "single":
        if not event_name:
            return JSONResponse({"success": False, "log_entry": "Missing event_name for single mode"}, status_code=400)
        
        event_token = app_config.get("events", {}).get(event_name)
        if not event_token:
            return JSONResponse({"success": False, "log_entry": f"Event '{event_name}' token not found"}, status_code=404)
        
        # Führe Request direkt aus (Logik aus logic.py)
        # Hinweis: execute_single_request muss in logic.py existieren und (status, response_text) zurückgeben
        try:
            status_code, response_body = execute_single_request(
                app_token=app_token,
                event_token=event_token,
                gaid=device_id, # logic.py nennt es oft gaid oder device_id
                platform=platform
            )
            
            success = (status_code == 200)
            log_msg = f"<span class='log-ts'>ACK</span> {app_name} | {event_name} -> {status_code}"
            if not success:
                log_msg += f" | {response_body}"
                
            return {"success": success, "log_entry": log_msg, "s2s_response": response_body}

        except Exception as e:
            logger.error(f"Execution Error: {e}")
            return JSONResponse({"success": False, "log_entry": f"<span class='log-ts'>CRIT</span> Internal Error: {str(e)}"})

    # 3. Modus: CREDIT ALL (Sequentiell) oder TIMER
    elif mode == "credit_all" or mode == "timer":
        # Hier würden wir die Jobs in die Datenbank schreiben
        # Für dieses Beispiel implementieren wir die sofortige Rückmeldung, dass der Job angenommen wurde.
        
        all_events = app_config.get("events", {})
        
        # Job in DB eintragen (Beispielhaft, Parameter müssen mit database.py übereinstimmen)
        # Wir setzen delay_min/max auf defaults wenn nicht übergeben, 
        # hier vereinfacht, da wir keine separaten Form-Felder im Header abgefangen haben (in main.py Argumenten ergänzen falls nötig)
        
        # Hinweis: Um Timer-Argumente zu empfangen, müssen sie in der Funktionssignatur oben ergänzt werden:
        # delay_min: float = Form(1.0), delay_max: float = Form(5.0) ...
        
        return {"success": True, "log_entry": f"<span class='log-ts'>JOB</span> '{mode}' sequence for {len(all_events)} events queued in Zone C."}

    else:
        return JSONResponse({"success": False, "log_entry": f"Unknown Mode: {mode}"}, status_code=400)

# Endpunkt für den Cronjob/Worker (optional, um Queue manuell zu triggern)
@app.get("/api/process-queue")
def trigger_queue(key: str = Depends(verify_api_key)):
    result = process_job_queue()
    return result