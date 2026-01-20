import os
import json
import logging
import traceback
import socket
from fastapi import FastAPI, Form, HTTPException, Header
from discord_webhook import DiscordWebhook, DiscordEmbed

# Versuche Logic zu importieren (lokal oder im Container Pfad)
try:
    from logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app, ua_manager
except ImportError:
    from app.logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app, ua_manager

# --- KONFIGURATION ---
app = FastAPI(title="Zone C Engine")

# Environment Variablen laden
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "SET_THIS_IN_ENV")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
HOSTNAME = socket.gethostname()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- STARTUP EVENT ---
@app.on_event("startup")
async def startup_event():
    """Sendet Nachricht an Discord, wenn der Server hochfährt."""
    if DISCORD_WEBHOOK_URL:
        try:
            webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
            embed = DiscordEmbed(title="🟢 ENGINE ONLINE", description="Zone C ist bereit und Datenbank geladen.", color="00ff00")
            embed.set_footer(text=f"Host: {HOSTNAME}")
            webhook.add_embed(embed)
            webhook.execute()
            logging.info("Startup-Nachricht gesendet.")
        except Exception as e:
            logging.error(f"Startup-Nachricht fehlgeschlagen: {e}")
    else:
        logging.warning("⚠️ Keine DISCORD_WEBHOOK_URL gesetzt!")

# --- LOGGING FUNKTION ---
def send_detailed_log(status_type, context, response_text, user_agent, is_fixed_ua):
    """
    Sendet formatiertes Log an Discord.
    is_fixed_ua: True = UA kam aus DB (nicht geändert). False = UA wurde neu erstellt/überschrieben.
    """
    if not DISCORD_WEBHOOK_URL: return
    
    # Farben definieren
    color = "39ff14" if status_type == "success" else "ff3333" # Grün / Rot
    if status_type == "warning": color = "ffaa00" # Orange

    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
        
        # Titel Status
        db_status = "(DB LOCKED)" if is_fixed_ua else "(UPDATED / NEW)"
        embed = DiscordEmbed(title=f"INJECTION {status_type.upper()} {db_status}", color=color)
        
        embed.set_author(name=f"OPERATOR: {context.get('username', 'Unknown').upper()}")
        embed.set_timestamp()
        
        # Grid Info
        embed.add_embed_field(name="Target", value=f"`{context['app_name']}` ({context['platform'].upper()})", inline=True)
        embed.add_embed_field(name="Event", value=f"**{context['event_name']}**", inline=True)
        embed.add_embed_field(name="Device ID", value=f"`{context['device_id']}`", inline=False)
        
        # User Agent Info
        ua_source = "🔒 LOADED FROM DATABASE (Persistent)" if is_fixed_ua else "♻️ OVERWRITTEN / NEWLY CREATED"
        embed.add_embed_field(name="UA Strategy", value=ua_source, inline=True)
        embed.add_embed_field(name="User Agent Used", value=f"```\n{user_agent}\n```", inline=False)
        
        # Response kürzen
        clean_resp = str(response_text).replace("```", "")[:700]
        embed.add_embed_field(name="Engine Response", value=f"```json\n{clean_resp}\n```", inline=False)
        
        webhook.add_embed(embed)
        webhook.execute()
    except Exception as e:
        logging.error(f"Discord Log Error: {e}")

# --- DATA LOADING ---
def load_app_data():
    """Lädt die JSON Konfiguration"""
    paths = ["app/data_android.json", "data_android.json", "../data_android.json"]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"JSON Load Error: {e}")
    return {}

# --- ROUTEN ---

@app.get("/health")
async def health():
    return {"status": "online"}

@app.get("/api/get-apps")
async def get_apps(x_api_key: str = Header(None)):
    """Liefert Liste der Apps an Zone B"""
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")
    
    data = load_app_data()
    # Nur App-Namen und Event-Namen zurückgeben (Sicherheit!)
    return {app_name: list(details.get('events', {}).keys()) for app_name, details in data.items()}

@app.post("/api/internal-execute")
async def internal_execute(
    app_name: str = Form(...),
    platform: str = Form(...),
    device_id: str = Form(...),
    event_name: str = Form(...),
    username: str = Form("System"),
    
    # Pro Toolz Parameter
    pro_browser: str = Form(None),
    pro_model: str = Form(None),
    pro_os_ver: str = Form(None),
    use_random_ua: bool = Form(False),
    force_ua_update: bool = Form(False), # <--- Wenn True, wird DB Eintrag überschrieben
    
    x_api_key: str = Header(None)
):
    """Führt den Request aus"""
    
    # 1. Security Check
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

    # 2. User Agent Management (Logic.py)
    # Gibt den UA zurück und ob er aus dem Cache kam (is_cached)
    final_ua, is_cached = ua_manager.get_or_create(
        device_id=device_id,
        platform=platform,
        browser=pro_browser,
        model=pro_model,
        os_ver=pro_os_ver,
        use_random=use_random_ua,
        force_update=force_ua_update
    )

    # 3. App Daten laden
    data = load_app_data()
    if app_name not in data:
        return {"status": "error", "message": "App Configuration not found in Zone C."}
    
    app_info = data[app_name]
    event_token = app_info['events'].get(event_name)
    app_token = app_info.get('app_token')
    use_get = app_info.get('use_get_request', False)
    skadn_val = get_skadn_value_for_app(app_name) if platform == "ios" else None

    # Context für Logs sammeln
    log_ctx = {
        "username": username,
        "app_name": app_name,
        "platform": platform,
        "device_id": device_id,
        "event_name": event_name
    }

    try:
        # 4. URL Generieren
        url = generate_adjust_url(event_token, app_token, device_id, platform, skadn_val)
        
        # 5. Request Senden (Mit dem festen User Agent)
        raw_response = send_request_auto_detect(url, platform, use_get, skadn_val, user_agent=final_ua)
        
        # 6. Response Analysieren
        raw_lower = str(raw_response).lower()
        status = "error"
        msg = "Error"
        
        if "ignoring event" in raw_lower:
            status = "warning"
            msg = "Event bereits gesendet (Duplicate)."
        elif "request doesn't contain device identifiers" in raw_lower:
            status = "error"
            msg = "Fehler: Ungültiges ID Format."
        elif "device not found" in raw_lower:
            status = "warning"
            msg = "Warnung: Gerät nicht getrackt (Organic?)."
        elif "app_token" in raw_lower or "success" in raw_lower or "ok" in raw_lower:
            status = "success"
            msg = "Erfolgreich gesendet."
        else:
            status = "error"
            msg = f"Server Error: {raw_response[:40]}"

        # 7. Loggen & Antworten
        send_detailed_log(status, log_ctx, raw_response, final_ua, is_cached)
        
        return {"status": status, "message": msg}

    except Exception as e:
        err_msg = traceback.format_exc()
        logging.error(f"Crash in Execution: {err_msg}")
        # Sende Error Log
        send_detailed_log("error", log_ctx, f"CRASH: {str(e)}", final_ua, is_cached)
        return {"status": "error", "message": "Internal Engine Error"}