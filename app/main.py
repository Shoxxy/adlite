import os
import json
import logging
import traceback
import socket
import time
from fastapi import FastAPI, Form, HTTPException, Header
from fastapi.responses import JSONResponse
from discord_webhook import DiscordWebhook, DiscordEmbed

try:
    from logic import generate_adjust_payload, send_request_auto_detect, get_proxy_dict, get_skadn_value_for_app, ua_manager, extract_id_and_platform_from_link
except ImportError:
    from app.logic import generate_adjust_payload, send_request_auto_detect, get_proxy_dict, get_skadn_value_for_app, ua_manager, extract_id_and_platform_from_link

app = FastAPI(title="Zone C Engine")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "DEFAULT")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

def send_detailed_log(status, ctx, resp, ip, proxy):
    if not DISCORD_WEBHOOK_URL: return
    color = "39ff14" if "status 200" in status.lower() else "ff3333"
    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
        embed = DiscordEmbed(title=f"SDK EVENT {status.upper()}", color=color)
        embed.set_author(name=f"USER: {ctx.get('username')}")
        embed.add_embed_field(name="Target", value=f"{ctx['app_name']} - {ctx['event_name']}", inline=True)
        embed.add_embed_field(name="Device ID", value=ctx['device_id'], inline=False)
        
        stealth = f"Proxy: {proxy}\n"
        if ip: stealth += f"IP Link: {ip}"
        embed.add_embed_field(name="Stealth Info", value=stealth, inline=False)
        
        embed.add_embed_field(name="Server Response", value=f"```\n{str(resp)[:500]}\n```", inline=False)
        webhook.add_embed(embed); webhook.execute()
    except: pass

def load_app_data():
    for path in ["app/data_android.json", "data_android.json", "../data_android.json"]:
        if os.path.exists(path):
            with open(path, 'r') as f: return json.load(f)
    return {}

@app.post("/api/internal-execute")
async def internal_execute(
    app_name: str = Form(...),
    platform: str = Form(...),
    device_id: str = Form(...),
    event_name: str = Form(...),
    username: str = Form("System"),
    tracker_link: str = Form(None),
    proxy_url: str = Form(None),
    use_auto_proxy: bool = Form(False),
    x_api_key: str = Header(None)
):
    try:
        if x_api_key != INTERNAL_API_KEY: raise HTTPException(status_code=403)

        # 1. Parsing Override (Falls ID im Link steht, hat sie Vorrang)
        if tracker_link:
            ex_id, ex_plat = extract_id_and_platform_from_link(tracker_link)
            if ex_id: device_id = ex_id; platform = ex_plat

        data = load_app_data()
        if app_name not in data: return {"status": "error", "message": "App Config Missing"}
        
        app_info = data[app_name]
        event_token = app_info['events'].get(event_name)
        app_token = app_info.get('app_token')
        skadn_val = get_skadn_value_for_app(app_name) if platform == "ios" else None
        
        # Proxy Setup
        proxies = get_proxy_dict(proxy_url, use_auto_proxy)

        # 2. Payload bauen (Mit Link-Parametern in partner_params!)
        base_url, payload, ip_to_spoof, timestamp = generate_adjust_payload(
            event_token, app_token, device_id, platform, skadn_val, tracker_link
        )

        # 3. Senden (SDK Simulation)
        raw = send_request_auto_detect(
            base_url, 
            payload, 
            timestamp, 
            platform,
            spoof_ip=ip_to_spoof,
            proxies=proxies
        )
        
        # 4. Resultat
        raw_l = str(raw).lower()
        status = "error"
        if "status 200" in raw_l: status = "success"
        
        ctx = {"username":username, "app_name":app_name, "device_id":device_id, "event_name":event_name}
        p_info = "Auto" if use_auto_proxy else ("Manual" if proxy_url else "Direct")
        send_detailed_log(status, ctx, raw, ip_to_spoof, p_info)
        
        return {"status": status, "message": raw}

    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Error: {str(e)}"})