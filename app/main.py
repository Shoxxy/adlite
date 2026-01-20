import os
import json
import logging
import traceback
from fastapi import FastAPI, Request, Form, HTTPException, Header
from pydantic import BaseModel
# Importiere die Logic aus dem gleichen Verzeichnis
try:
    from logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app
except ImportError:
    # Fallback für lokale Tests
    from app.logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app

# --- KONFIGURATION ---
app = FastAPI(title="Zone C Engine")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "SET_THIS_IN_ENV")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")  # Optional: Loggt Engine-Fehler

# Logging Setup
logging.basicConfig(filename='engine_core.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def log_to_discord(message, level="info"):
    """Sendet kritische Engine-Fehler an Discord"""
    if not DISCORD_WEBHOOK_URL: return
    from discord_webhook import DiscordWebhook, DiscordEmbed
    color = "00ff00" if level == "info" else "ff0000"
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    embed = DiscordEmbed(title=f"ENGINE STATUS: {level.upper()}", description=message, color=color)
    webhook.add_embed(embed)
    try:
        webhook.execute()
    except:
        pass

def load_app_data():
    """Lädt die sensitive data_android.json"""
    paths = ["data_android.json", "app/data_android.json", "../data_android.json"]
    for path in paths:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    logging.error("CRITICAL: data_android.json not found!")
    return {}

@app.get("/health")
async def health_check():
    return {"status": "ENGINE ONLINE", "core": "active"}

@app.get("/api/get-apps")
async def get_apps(x_api_key: str = Header(None)):
    """Gibt verfügbare Apps und Event-Namen zurück (KEINE TOKENS)"""
    if x_api_key != INTERNAL_API_KEY:
        log_to_discord("Unauthorized access attempt to /get-apps", "alert")
        raise HTTPException(status_code=403, detail="Access Denied")
    
    data = load_app_data()
    # Nur Keys zurückgeben, keine Values (Tokens)
    config = {app_name: list(details.get('events', {}).keys()) for app_name, details in data.items()}
    return config

@app.post("/api/internal-execute")
async def internal_execute(
    app_name: str = Form(...),
    platform: str = Form(...),
    device_id: str = Form(...),
    event_name: str = Form(...),
    x_api_key: str = Header(None)
):
    """Führt den eigentlichen Request aus. Unsichtbar für den User."""
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

    data = load_app_data()
    if app_name not in data:
        return {"status": "error", "message": "Target App unmapped."}

    app_info = data[app_name]
    event_token = app_info['events'].get(event_name)
    app_token = app_info.get('app_token')
    use_get = app_info.get('use_get_request', False)
    
    # Logic Processing
    skadn_val = get_skadn_value_for_app(app_name) if platform == "ios" else None

    try:
        # 1. URL Generieren (Logic.py)
        url = generate_adjust_url(event_token, app_token, device_id, platform, skadn_val)
        
        # 2. Request Senden (Logic.py)
        raw_response = send_request_auto_detect(url, platform, use_get, skadn_val)
        
        # 3. Response Analyse
        raw_lower = str(raw_response).lower()
        status = "success"
        if "request doesn't contain device identifiers" in raw_lower:
            user_msg = "ID_INVALID: Device Identifier missing."
            status = "error"
        elif "device not found" in raw_lower:
            user_msg = "TARGET_MISSING: App not installed/tracked."
            status = "warning"
        elif "app_token" in raw_lower or "success" in raw_lower or "ok" in raw_lower:
            user_msg = "INJECTION_CONFIRMED: Packet accepted."
        else:
            user_msg = f"SERVER_RESPONSE: {raw_response[:50]}..."

        # Logge Erfolg intern
        logging.info(f"Exec: {app_name} | {event_name} | {status}")
        
        return {"status": status, "message": user_msg}

    except Exception as e:
        err_msg = traceback.format_exc()
        logging.error(f"Execution Error: {err_msg}")
        log_to_discord(f"Crash in Engine for {app_name}:\n{str(e)}", "critical")
        return {"status": "error", "message": "CORE_EXCEPTION: Processing failed."}