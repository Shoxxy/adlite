import os
import json
import logging
import traceback
import socket
from fastapi import FastAPI, Form, HTTPException, Header
from discord_webhook import DiscordWebhook, DiscordEmbed

# Versuche Logic zu importieren
try:
    from logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app
except ImportError:
    from app.logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app

# --- KONFIGURATION ---
app = FastAPI(title="Zone C Engine | Headless")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "SET_THIS_IN_ENV")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
HOSTNAME = socket.gethostname()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- LOGGING SYSTEM ---
def send_detailed_log(status_type, context, response_text, url_used=""):
    if not DISCORD_WEBHOOK_URL: return

    if status_type == "success":
        color = "39ff14"
        title = "✅ INJECTION SUCCESSFUL"
    elif status_type == "warning":
        color = "ffaa00"
        title = "⚠️ INJECTION WARNING / DUPLICATE"
    else:
        color = "ff3333"
        title = "⛔ INJECTION FAILED / ERROR"

    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    embed = DiscordEmbed(title=title, color=color)
    
    embed.set_author(name=f"OPERATOR: {context.get('username', 'Unknown').upper()}")
    embed.set_timestamp()
    
    embed.add_embed_field(name="Application", value=f"`{context['app_name']}`", inline=True)
    embed.add_embed_field(name="Platform", value=f"`{context['platform'].upper()}`", inline=True)
    embed.add_embed_field(name="Trigger Event", value=f"**{context['event_name']}**", inline=True)
    embed.add_embed_field(name="Device Identifier", value=f"`{context['device_id']}`", inline=False)
    
    clean_resp = response_text.replace("```", "") 
    if len(clean_resp) > 800: clean_resp = clean_resp[:800] + "..."
    embed.add_embed_field(name="Engine Response Payload", value=f"```json\n{clean_resp}\n```", inline=False)
    embed.set_footer(text=f"Engine: Zone C | Node: {HOSTNAME}")

    webhook.add_embed(embed)
    try: webhook.execute()
    except: pass

# --- DATA LOAD ---
def load_app_data():
    paths = ["app/data_android.json", "data_android.json", "../data_android.json"]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: pass
    return {}

# --- ROUTES ---
@app.get("/health")
async def health_check():
    return {"status": "online"}

@app.get("/api/get-apps")
async def get_apps(x_api_key: str = Header(None)):
    if x_api_key != INTERNAL_API_KEY: raise HTTPException(status_code=403)
    data = load_app_data()
    return {app_name: list(details.get('events', {}).keys()) for app_name, details in data.items()}

@app.post("/api/internal-execute")
async def internal_execute(
    app_name: str = Form(...),
    platform: str = Form(...),
    device_id: str = Form(...),
    event_name: str = Form(...),
    username: str = Form("System"),
    x_api_key: str = Header(None)
):
    if x_api_key != INTERNAL_API_KEY: raise HTTPException(status_code=403)

    log_ctx = {"username": username, "app_name": app_name, "platform": platform, "device_id": device_id, "event_name": event_name}
    data = load_app_data()
    
    if app_name not in data:
        send_detailed_log("error", log_ctx, "App Config Missing")
        return {"status": "error", "message": "Error"}

    app_info = data[app_name]
    event_token = app_info['events'].get(event_name)
    app_token = app_info.get('app_token')
    use_get = app_info.get('use_get_request', False)
    skadn_val = get_skadn_value_for_app(app_name) if platform == "ios" else None

    try:
        url = generate_adjust_url(event_token, app_token, device_id, platform, skadn_val)
        raw_response = send_request_auto_detect(url, platform, use_get, skadn_val)
        
        raw_lower = str(raw_response).lower()
        
        if "ignoring event" in raw_lower:
            status_type = "warning"
            user_msg = "Event bereits gesendet."
        elif "request doesn't contain device identifiers" in raw_lower:
            status_type = "error"
            user_msg = "Error: Invalid ID format."
        elif "device not found" in raw_lower:
            status_type = "warning"
            user_msg = "Warning: Device not tracked."
        elif "app_token" in raw_lower or "success" in raw_lower or "ok" in raw_lower:
            status_type = "success"
            user_msg = "Success"
        else:
            status_type = "error"
            user_msg = "Error"

        send_detailed_log(status_type, log_ctx, raw_response, url)
        return {"status": status_type, "message": user_msg}

    except Exception as e:
        err_msg = traceback.format_exc()
        send_detailed_log("error", log_ctx, f"CRITICAL:\n{err_msg}")
        return {"status": "error", "message": "Error"}