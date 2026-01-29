import os
import json
import requests
import time
from datetime import datetime
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

# --- CONFIG ---
LOG_FILE = "security_activity.log"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
ZONE_C_URL = str(os.environ.get("ZONE_C_URL", "")).strip().rstrip("/")
INTERNAL_API_KEY = str(os.environ.get("INTERNAL_API_KEY", "")).strip()

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", "safe-key-999"), max_age=7200)
templates = Jinja2Templates(directory="templates")

# --- ERWEITERTES LOGGING ---
def send_debug_log(title, details, color=1752220):
    """Sendet detaillierte technische Daten an Discord"""
    if not DISCORD_WEBHOOK: return
    
    fields = []
    for key, val in details.items():
        fields.append({"name": key, "value": str(val), "inline": True})

    payload = {
        "embeds": [{
            "title": f"🛠 {title}",
            "color": color,
            "fields": fields,
            "footer": {"text": f"Zeitstempel: {datetime.now().strftime('%H:%M:%S')}"}
        }]
    }
    try: requests.post(DISCORD_WEBHOOK, json=payload, timeout=5)
    except: pass

@app.get("/")
async def index(request: Request):
    if not request.session.get("user"):
        return templates.TemplateResponse("login.html", {"request": request})
    
    app_config = {}
    base_url = ZONE_C_URL if ZONE_C_URL.startswith("http") else f"https://{ZONE_C_URL}"
    target_url = f"{base_url}/api/get-apps"
    
    start_time = time.time()
    
    try:
        resp = requests.get(
            target_url, 
            headers={"x-api-key": INTERNAL_API_KEY, "Accept": "application/json"}, 
            timeout=15
        )
        duration = round(time.time() - start_time, 2)
        
        if resp.status_code == 200:
            app_config = resp.json()
        else:
            # Detaillierter Log bei Status-Fehlern (z.B. 401, 403, 404, 500)
            send_debug_log("HTTP STATUS ERROR", {
                "Target": target_url,
                "Status": resp.status_code,
                "Reason": resp.reason,
                "Duration": f"{duration}s",
                "Key-Used": f"{INTERNAL_API_KEY[:4]}***"
            }, color=15105570)
            app_config = {"ERROR": f"Status {resp.status_code}"}

    except Exception as e:
        duration = round(time.time() - start_time, 2)
        # Deep-Dive Log bei totalem Verbindungsabbruch
        send_debug_log("CRITICAL CONNECTION FAILED", {
            "Target": target_url,
            "Error-Type": type(e).__name__,
            "Message": str(e)[:200], # Kürzen falls zu lang
            "Duration": f"{duration}s",
            "Zone-C-Raw": ZONE_C_URL
        }, color=15548997)
        app_config = {"ERROR": "Connection Failed"}

    return templates.TemplateResponse("index.html", {"request": request, "app_config": app_config})

# Restliche Routen (Login, API-Send, Admin) bleiben identisch...