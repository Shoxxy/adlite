import os
import json
import logging
import traceback
import datetime
from fastapi import FastAPI, Form, HTTPException, Header
from discord_webhook import DiscordWebhook, DiscordEmbed

# Import Logic
try:
    from logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app
except ImportError:
    from app.logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app

# --- KONFIGURATION ---
app = FastAPI(title="Zone C Engine | Headless")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "SET_THIS_IN_ENV")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- ADVANCED LOGGING SYSTEM ---
def send_detailed_log(status_type, context, response_text):
    """
    Sendet ein professionelles Embed an Discord.
    status_type: 'success', 'warning', 'error'
    context: Dict mit User, App, Event, DeviceID, Platform
    response_text: Die Antwort vom Server (gekürzt)
    """
    if not DISCORD_WEBHOOK_URL: return

    # Farb-Codierung & Titel
    if status_type == "success":
        color = "39ff14" # Neon Green
        title = "✅ INJECTION SUCCESSFUL"
        icon = "https://i.imgur.com/H1G3xXF.png" # Optionales Icon (Checkmark)
    elif status_type == "warning":
        color = "ffaa00" # Orange
        title = "⚠️ INJECTION WARNING"
        icon = "https://i.imgur.com/Vi51M3y.png"
    else:
        color = "ff3333" # Red
        title = "⛔ INJECTION FAILED"
        icon = "https://i.imgur.com/e37u64d.png"

    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    embed = DiscordEmbed(title=title, color=color)
    
    # Metadaten Header
    embed.set_author(name=f"Operator: {context.get('username', 'Unknown')}")
    embed.set_timestamp()
    
    # Hauptdaten als Grid
    embed.add_embed_field(name="Application", value=f"`{context['app_name']}`", inline=True)
    embed.add_embed_field(name="Platform", value=f"`{context['platform'].upper()}`", inline=True)
    embed.add_embed_field(name="Event", value=f"**{context['event_name']}**", inline=True)
    
    # Identifier (zensiert die Mitte für Sicherheit in Screenshots, falls gewünscht - hier voll angezeigt)
    embed.add_embed_field(name="Device ID", value=f"`{context['device_id']}`", inline=False)
    
    # Technische Antwort (Code Block für Lesbarkeit)
    # Schneidet zu lange Antworten ab
    clean_resp = response_text[:900] + "..." if len(response_text) > 900 else response_text
    embed.add_embed_field(name="Engine Response", value=f"```json\n{clean_resp}\n```", inline=False)
    
    # Footer
    embed.set_footer(text="SuStoolz Engine • Zone C", icon_url=icon)

    webhook.add_embed(embed)
    try:
        webhook.execute()
    except Exception as e:
        logging.error(f"Discord Hook Error: {e}")

# --- CORE DATA LOADING ---
def load_app_data():
    paths = ["app/data_android.json", "data_android.json", "../data_android.json"]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"JSON Load Error: {e}")
    return {}

# --- ROUTES ---

@app.get("/health")
async def health_check():
    return {"status": "online", "mode": "headless"}

@app.get("/api/get-apps")
async def get_apps(x_api_key: str = Header(None)):
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403)
    data = load_app_data()
    return {app_name: list(details.get('events', {}).keys()) for app_name, details in data.items()}

@app.post("/api/internal-execute")
async def internal_execute(
    app_name: str = Form(...),
    platform: str = Form(...),
    device_id: str = Form(...),
    event_name: str = Form(...),
    username: str = Form("System"), # NEU: Empfängt den Usernamen von Zone B
    x_api_key: str = Header(None)
):
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403)

    # Context für Logs sammeln
    log_ctx = {
        "username": username,
        "app_name": app_name,
        "platform": platform,
        "device_id": device_id,
        "event_name": event_name
    }

    data = load_app_data()
    if app_name not in data:
        msg = f"Error: App '{app_name}' not found in configuration."
        send_detailed_log("error", log_ctx, msg)
        return {"status": "error", "message": msg}

    app_info = data[app_name]
    event_token = app_info['events'].get(event_name)
    app_token = app_info.get('app_token')
    use_get = app_info.get('use_get_request', False)
    skadn_val = get_skadn_value_for_app(app_name) if platform == "ios" else None

    try:
        # Ausführung
        url = generate_adjust_url(event_token, app_token, device_id, platform, skadn_val)
        raw_response = send_request_auto_detect(url, platform, use_get, skadn_val)
        
        # Analyse der Antwort
        raw_lower = str(raw_response).lower()
        status_type = "info"
        user_msg = ""

        if "request doesn't contain device identifiers" in raw_lower:
            status_type = "error"
            user_msg = "FAILED: Device Identifier format invalid."
        elif "device not found" in raw_lower:
            status_type = "warning"
            user_msg = "WARNING: Device not tracked (Organic Install?)."
        elif "app_token" in raw_lower or "success" in raw_lower or "ok" in raw_lower:
            status_type = "success"
            user_msg = "SUCCESS: Event injected successfully."
        else:
            status_type = "warning"
            user_msg = f"UNKNOWN RESPONSE: {raw_response[:50]}..."

        # LOGGING AUSLÖSEN
        send_detailed_log(status_type, log_ctx, raw_response)
        
        return {"status": status_type, "message": user_msg}

    except Exception as e:
        err_msg = traceback.format_exc()
        send_detailed_log("error", log_ctx, f"INTERNAL EXCEPTION:\n{err_msg}")
        return {"status": "error", "message": "Critical Engine Failure."}