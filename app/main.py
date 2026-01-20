import os
import json
import logging
import traceback
import socket
from fastapi import FastAPI, Form, HTTPException, Header
from discord_webhook import DiscordWebhook, DiscordEmbed

try:
    from logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app, ua_manager
except ImportError:
    from app.logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app, ua_manager

app = FastAPI(title="Zone C Engine")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "SET_THIS_IN_ENV")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
HOSTNAME = socket.gethostname()
logging.basicConfig(level=logging.INFO)

def send_detailed_log(status_type, context, response_text, user_agent, is_fixed_ua):
    if not DISCORD_WEBHOOK_URL: return
    color = "39ff14" if status_type == "success" else "ff3333"
    if status_type == "warning": color = "ffaa00"
    
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    
    # DB Status im Titel
    db_status = "(DB LOCKED)" if is_fixed_ua else "(NEW RECORD)"
    embed = DiscordEmbed(title=f"INJECTION {status_type.upper()} {db_status}", color=color)
    
    embed.set_author(name=f"OPERATOR: {context.get('username', 'Unknown').upper()}")
    embed.add_embed_field(name="Target", value=f"`{context['app_name']}` ({context['platform'].upper()})", inline=True)
    embed.add_embed_field(name="Event", value=f"**{context['event_name']}**", inline=True)
    embed.add_embed_field(name="Device ID", value=f"`{context['device_id']}`", inline=False)
    
    # UA Info
    ua_source = "🔒 LOADED FROM DATABASE (Persistent)" if is_fixed_ua else "💾 CREATED & SAVED TO DB"
    embed.add_embed_field(name="Agent Status", value=ua_source, inline=False)
    embed.add_embed_field(name="User Agent", value=f"```\n{user_agent}\n```", inline=False)
    
    clean_resp = response_text.replace("```", "")[:600]
    embed.add_embed_field(name="Engine Response", value=f"```json\n{clean_resp}\n```", inline=False)
    
    webhook.add_embed(embed)
    try: webhook.execute()
    except: pass

def load_app_data():
    paths = ["app/data_android.json", "data_android.json", "../data_android.json"]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f: return json.load(f)
            except: pass
    return {}

@app.get("/health")
async def health(): return {"status": "online"}

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
    x_api_key: str = Header(None)
):
    if x_api_key != INTERNAL_API_KEY: raise HTTPException(status_code=403)

    # UA abrufen (Gibt zurück: UA String + Boolean ob aus DB geladen)
    final_ua, is_cached = ua_manager.get_or_create(device_id, platform, pro_browser, pro_model, pro_os_ver, use_random_ua)
    
    data = load_app_data()
    if app_name not in data: return {"status": "error", "message": "App Missing"}
    
    app_info = data[app_name]
    event_token = app_info['events'].get(event_name)
    app_token = app_info.get('app_token')
    use_get = app_info.get('use_get_request', False)
    skadn_val = get_skadn_value_for_app(app_name) if platform == "ios" else None

    try:
        url = generate_adjust_url(event_token, app_token, device_id, platform, skadn_val)
        raw = send_request_auto_detect(url, platform, use_get, skadn_val, user_agent=final_ua)
        raw_l = str(raw).lower()
        
        status = "error"; msg = "Error"
        if "ignoring event" in raw_l: status="warning"; msg="Duplicate"
        elif "success" in raw_l or "ok" in raw_l: status="success"; msg="Success"
        
        send_detailed_log(status, {"username":username, "app_name":app_name, "platform":platform, "device_id":device_id, "event_name":event_name}, raw, final_ua, is_cached)
        return {"status": status, "message": msg}
    except Exception as e:
        return {"status": "error", "message": "Crash"}