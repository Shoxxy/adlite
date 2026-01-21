import os
import json
import logging
import traceback
import socket
from fastapi import FastAPI, Form, HTTPException, Header
from fastapi.responses import JSONResponse
from discord_webhook import DiscordWebhook, DiscordEmbed

try:
    # ACHTUNG: Importiere jetzt generate_adjust_params statt generate_adjust_url
    from logic import generate_adjust_params, send_request_auto_detect, get_skadn_value_for_app, ua_manager, extract_id_and_platform_from_link
except ImportError:
    from app.logic import generate_adjust_params, send_request_auto_detect, get_skadn_value_for_app, ua_manager, extract_id_and_platform_from_link

app = FastAPI(title="Zone C Engine")

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "SET_THIS_IN_ENV")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
HOSTNAME = socket.gethostname()
logging.basicConfig(level=logging.INFO)

@app.on_event("startup")
async def startup_event():
    if DISCORD_WEBHOOK_URL:
        try: DiscordWebhook(url=DISCORD_WEBHOOK_URL).execute()
        except: pass

def send_detailed_log_extended(status_type, context, response_text, user_agent, is_fixed_ua, saved_to_db, id_overridden, used_link, spoofed_ip, proxy_info):
    if not DISCORD_WEBHOOK_URL: return
    color = "39ff14" if status_type == "success" else "ff3333"
    if status_type == "warning": color = "ffaa00"
    if status_type == "error": color = "ff0000"

    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
        status_text = ""
        if id_overridden: status_text += "(LINK PARSED) "
        if is_fixed_ua: status_text += "(LOCKED)"
        elif saved_to_db: status_text += "(SAVED)"
        
        embed = DiscordEmbed(title=f"INJECTION {status_type.upper()} {status_text}", color=color)
        embed.set_author(name=f"OPERATOR: {context.get('username', 'Unknown').upper()}")
        embed.add_embed_field(name="Target", value=f"`{context['app_name']}` ({context['platform'].upper()})", inline=True)
        embed.add_embed_field(name="Event", value=f"**{context['event_name']}**", inline=True)
        embed.add_embed_field(name="Device ID", value=f"`{context['device_id']}`", inline=False)
        
        adv_val = f"Proxy: **{proxy_info}**\n"
        if spoofed_ip: adv_val += f"Spoof IP: `{spoofed_ip}`\n"
        if used_link: adv_val += "Link: Parsed ✅"
        
        embed.add_embed_field(name="Stealth & Attribution", value=adv_val, inline=False)
        embed.add_embed_field(name="User Agent", value=f"```\n{user_agent}\n```", inline=False)
        
        clean_resp = str(response_text).replace("```", "")[:600]
        embed.add_embed_field(name="Engine Response", value=f"```json\n{clean_resp}\n```", inline=False)
        webhook.add_embed(embed); webhook.execute()
    except: pass

def load_app_data():
    for path in ["app/data_android.json", "data_android.json", "../data_android.json"]:
        if os.path.exists(path):
            with open(path, 'r') as f: return json.load(f)
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
    force_ua_update: bool = Form(False),
    save_ua: bool = Form(True),
    tracker_link: str = Form(None),
    proxy_url: str = Form(None),
    use_auto_proxy: bool = Form(False),
    x_api_key: str = Header(None)
):
    final_ua = "N/A"; active_link = None; is_cached = False; id_was_overridden = False; ip_spoofed = None

    try:
        if x_api_key != INTERNAL_API_KEY: raise HTTPException(status_code=403)

        if tracker_link:
            ex_id, ex_plat = extract_id_and_platform_from_link(tracker_link)
            if ex_id: device_id = ex_id; platform = ex_plat; id_was_overridden = True

        final_ua, is_cached, active_link = ua_manager.get_or_create(
            device_id=device_id, platform=platform, browser=pro_browser, model=pro_model,
            os_ver=pro_os_ver, use_random=use_random_ua, force_update=force_ua_update,
            save_to_db=save_ua, incoming_link=tracker_link 
        )

        data = load_app_data()
        if app_name not in data: return {"status": "error", "message": "Config Missing"}
        
        app_info = data[app_name]
        event_token = app_info['events'].get(event_name)
        app_token = app_info.get('app_token')
        
        # HIER LESEN WIR DIE JSON CONFIG:
        use_get = app_info.get('use_get_request', False) 
        
        skadn_val = get_skadn_value_for_app(app_name) if platform == "ios" else None

        # NEU: Dict zurückbekommen
        base_url, params, ip_to_spoof = generate_adjust_params(event_token, app_token, device_id, platform, skadn_val, active_link)
        if ip_to_spoof: ip_spoofed = ip_to_spoof

        # AN SENDER ÜBERGEBEN
        raw = send_request_auto_detect(
            base_url, 
            params, # Übergebe jetzt das Dictionary!
            use_get, # true = params in URL, false = params in Body
            user_agent=final_ua, 
            spoof_ip=ip_spoofed,
            manual_proxy=proxy_url,
            use_auto_proxy=use_auto_proxy
        )
        
        raw_l = str(raw).lower()
        status = "error"; msg = "Error"
        if "ignoring event" in raw_l: status="warning"; msg="Duplicate"
        elif "success" in raw_l or "ok" in raw_l: status="success"; msg="Success"
        elif "via" in raw_l: status="success"; msg="Success"
        else: status="error"; msg=f"Server: {raw[:40]}"
        
        log_ctx = {"username":username, "app_name":app_name, "platform":platform, "device_id":device_id, "event_name":event_name}
        used_proxy_info = "Auto-Proxy" if use_auto_proxy else ("Manual" if proxy_url else "None")
        
        send_detailed_log_extended(status, log_ctx, raw, final_ua, is_cached, save_ua, id_was_overridden, active_link, ip_spoofed, used_proxy_info)
        
        return {"status": status, "message": msg}

    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Engine Error: {str(e)}"})