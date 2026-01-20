import os
import json
import logging
import traceback
import socket
from fastapi import FastAPI, Form, HTTPException, Header
from fastapi.responses import JSONResponse
from discord_webhook import DiscordWebhook, DiscordEmbed

# Versuche Logic zu importieren
try:
    from logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app, ua_manager
except ImportError:
    from app.logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app, ua_manager

app = FastAPI(title="Zone C Engine")

# --- CONFIG ---
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "SET_THIS_IN_ENV")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
HOSTNAME = socket.gethostname()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- LOGGING ---
def send_detailed_log(status_type, context, response_text, user_agent, is_fixed_ua):
    if not DISCORD_WEBHOOK_URL: return
    
    color = "39ff14" if status_type == "success" else "ff3333"
    if status_type == "warning": color = "ffaa00"
    if status_type == "error": color = "ff0000"

    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
        
        db_status = "(LOCKED)" if is_fixed_ua else "(NEW)"
        if user_agent == "N/A (Crash)": db_status = "(FAILED)"
        
        embed = DiscordEmbed(title=f"INJECTION {status_type.upper()} {db_status}", color=color)
        embed.set_author(name=f"OPERATOR: {context.get('username', 'Unknown').upper()}")
        
        # Grid
        embed.add_embed_field(name="Target", value=f"`{context['app_name']}` ({context['platform'].upper()})", inline=True)
        embed.add_embed_field(name="Device ID", value=f"`{context['device_id']}`", inline=False)
        
        # UA Info
        embed.add_embed_field(name="User Agent", value=f"```\n{user_agent}\n```", inline=False)
        
        # Response / Error Message
        clean_resp = str(response_text).replace("```", "")[:700]
        embed.add_embed_field(name="Engine Output", value=f"```json\n{clean_resp}\n```", inline=False)
        
        webhook.add_embed(embed)
        webhook.execute()
    except Exception as e:
        logging.error(f"Discord Log failed: {e}")

def load_app_data():
    paths = ["app/data_android.json", "data_android.json", "../data_android.json"]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f: return json.load(f)
            except: pass
    return {}

# --- ROUTES ---

@app.get("/health")
async def health():
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
    pro_browser: str = Form(None),
    pro_model: str = Form(None),
    pro_os_ver: str = Form(None),
    use_random_ua: bool = Form(False),
    force_ua_update: bool = Form(False),
    x_api_key: str = Header(None)
):
    # 1. Init SAFE Defaults (Verhindert 500er Crash bei Error-Handling)
    final_ua = "N/A (Crash)"
    is_cached = False
    log_ctx = {
        "username": username, 
        "app_name": app_name, 
        "platform": platform, 
        "device_id": device_id, 
        "event_name": event_name
    }

    try:
        # 2. Auth Check
        if x_api_key != INTERNAL_API_KEY:
            raise HTTPException(status_code=403, detail="Forbidden")

        # 3. UA Generierung (Hier könnte der DB Fehler auftreten!)
        # Wir fangen Fehler spezifisch für den UA Manager ab, falls nötig
        try:
            final_ua, is_cached = ua_manager.get_or_create(
                device_id=device_id,
                platform=platform,
                browser=pro_browser,
                model=pro_model,
                os_ver=pro_os_ver,
                use_random=use_random_ua,
                force_update=force_ua_update
            )
        except Exception as db_error:
            # Falls DB crasht, generieren wir einen Notfall-UA ohne Speicherung
            logging.error(f"DB Error: {db_error}")
            final_ua = "Mozilla/5.0 (Emergency; Database Error) AppleWebKit/537.36"
            # Wir machen weiter, damit der Request trotzdem rausgeht!

        # 4. App Data
        data = load_app_data()
        if app_name not in data:
            return {"status": "error", "message": "App Config Missing"}
        
        app_info = data[app_name]
        event_token = app_info['events'].get(event_name)
        app_token = app_info.get('app_token')
        use_get = app_info.get('use_get_request', False)
        skadn_val = get_skadn_value_for_app(app_name) if platform == "ios" else None

        # 5. Execution
        url = generate_adjust_url(event_token, app_token, device_id, platform, skadn_val)
        raw_response = send_request_auto_detect(url, platform, use_get, skadn_val, user_agent=final_ua)
        
        # 6. Analysis
        raw_lower = str(raw_response).lower()
        status = "error"
        msg = "Error"
        
        if "ignoring event" in raw_lower: status="warning"; msg="Duplicate"
        elif "request doesn't contain device identifiers" in raw_lower: status="error"; msg="Invalid ID"
        elif "success" in raw_lower or "ok" in raw_lower: status="success"; msg="Success"
        
        # 7. Success Log
        send_detailed_log(status, log_ctx, raw_response, final_ua, is_cached)
        return {"status": status, "message": msg}

    except Exception as e:
        # 8. CRASH HANDLING
        # Jetzt stürzt es hier nicht mehr ab, weil final_ua oben definiert wurde
        err_msg = traceback.format_exc()
        logging.error(f"CRITICAL ENGINE ERROR: {err_msg}")
        
        send_detailed_log("error", log_ctx, f"INTERNAL CRASH:\n{str(e)}", final_ua, is_cached)
        
        # Wichtig: JSON Return statt 500, damit Zone B den Text anzeigen kann
        return JSONResponse(
            status_code=200, 
            content={"status": "error", "message": f"Engine Crash: {str(e)}"}
        )