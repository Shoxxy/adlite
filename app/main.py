import os
import json
import requests
import time
from datetime import datetime
from fastapi import FastAPI, Request, Header, HTTPException, Form
from fastapi.responses import JSONResponse

# --- CONFIG ---
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
ZONE_C_URL = os.environ.get("ZONE_C_URL", "").strip().rstrip("/")
# API-Key, den du mitsenden musst, um Zone B zu nutzen
ZONE_B_ACCESS_KEY = os.environ.get("ZONE_B_ACCESS_KEY", "dein-geheimer-zugang")
# Key für die Kommunikation mit Zone C
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "").strip()

app = FastAPI(docs_url=None, redoc_url=None) # Dokumentation deaktiviert für Security

# --- REINES JSON LOGGING ---
def log_event(title, details, is_alert=False):
    if not DISCORD_WEBHOOK: return
    payload = {
        "embeds": [{
            "title": f"🛡️ ZONE B: {title}",
            "color": 15548997 if is_alert else 1752220,
            "fields": [{"name": k, "value": str(v), "inline": True} for k, v in details.items()],
            "timestamp": datetime.utcnow().isoformat()
        }]
    }
    try: requests.post(DISCORD_WEBHOOK, json=payload, timeout=5)
    except: pass

# --- MIDDLEWARE: AUTH-CHECK ---
@app.middleware("http")
async def verify_access(request: Request, call_next):
    # Wir prüfen den API-Key im Header "X-B-Key"
    api_key = request.headers.get("X-B-Key")
    if api_key != ZONE_B_ACCESS_KEY:
        return JSONResponse({"status": "error", "message": "Unauthorized Access"}, status_code=401)
    return await call_next(request)

# --- ENDPUNKT 1: APPS VON C ABRUFEN ---
@app.get("/get-data")
async def get_zone_c_data():
    try:
        r = requests.get(
            f"{ZONE_C_URL}/api/get-apps", 
            headers={"x-api-key": INTERNAL_API_KEY}, 
            timeout=10
        )
        return r.json()
    except Exception as e:
        log_event("FETCH ERROR", {"error": str(e)}, is_alert=True)
        return JSONResponse({"status": "error", "detail": "Uplink to Zone C failed"}, status_code=502)

# --- ENDPUNKT 2: BEFEHL AN C SENDEN ---
@app.post("/execute")
async def execute_command(
    app_name: str = Form(...), 
    platform: str = Form(...), 
    device_id: str = Form(...), 
    event_name: str = Form(...)
):
    log_event("EXECUTE REQUEST", {"app": app_name, "event": event_name})
    
    try:
        r = requests.post(
            f"{ZONE_C_URL}/api/internal-execute",
            data={
                "app_name": app_name, 
                "platform": platform, 
                "device_id": device_id, 
                "event_name": event_name
            },
            headers={"x-api-key": INTERNAL_API_KEY},
            timeout=30
        )
        return r.json()
    except Exception as e:
        log_event("EXECUTION FAILED", {"error": str(e)}, is_alert=True)
        return JSONResponse({"status": "error", "message": "Relay to C failed"}, status_code=502)

# --- ENDPUNKT 3: SYSTEM STATUS ---
@app.get("/status")
async def system_status():
    try:
        r = requests.get(f"{ZONE_C_URL}/api/get-apps", headers={"x-api-key": INTERNAL_API_KEY}, timeout=5)
        status = "Online" if r.status_code == 200 else "Degraded"
    except:
        status = "Offline"
    
    return {
        "zone_b": "Active",
        "zone_c_uplink": status,
        "timestamp": datetime.now().isoformat()
    }