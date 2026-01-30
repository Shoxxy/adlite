import time
import random
import requests
import json
import uuid
import hashlib
import string
import os
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, unquote
from discord_webhook import DiscordWebhook, DiscordEmbed

# Import der Datenbank-Funktionen
try:
    from app.database import update_job, get_due_jobs
except ImportError:
    from database import update_job, get_due_jobs

# --- KONFIGURATION ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# --- 1. PROXY ENGINE (Aus deinem Original übernommen) ---
class AutoProxyEngine:
    def __init__(self): 
        self.cached_proxies = []
        self.last_fetch = 0
        
    def fetch_proxies(self):
        # Holt frische Proxies alle 5 Min
        if self.cached_proxies and (time.time() - self.last_fetch < 300): 
            return self.cached_proxies
        try:
            url = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=3000&country=DE&ssl=all&anonymity=all"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                proxies = [p.strip() for p in r.text.split("\n") if p.strip()]
                if proxies: 
                    self.cached_proxies = proxies
                    self.last_fetch = time.time()
                    return proxies
        except: 
            pass
        return []

proxy_engine = AutoProxyEngine()

def get_proxy_dict(use_auto=True):
    # Einfache Rotation
    if use_auto:
        raw = proxy_engine.fetch_proxies()
        if raw:
            p = random.choice(raw[:10]) # Nimm einen der Top 10
            return {"http": f"http://{p}", "https": f"http://{p}"}
    return None

# --- 2. ID GENERATORS & BLUEPRINT ---
def generate_android_uuid(device_id):
    hash_obj = hashlib.md5(device_id.encode())
    guid = uuid.UUID(hash_obj.hexdigest())
    return str(guid)

def generate_google_app_set_id(device_id):
    seed = device_id + "_appset"
    hash_obj = hashlib.md5(seed.encode())
    guid = uuid.UUID(hash_obj.hexdigest())
    return str(guid)

def generate_push_token():
    part1 = ''.join(random.choices(string.ascii_letters + string.digits + "-_", k=22))
    part2 = ''.join(random.choices(string.ascii_letters + string.digits + "-_", k=134))
    return f"{part1}:APA91b{part2}"

def get_poco_blueprint(device_id, app_token, event_token, android_uuid, app_set_id, push_token):
    # Generiert das exakte POCO M7 Profil
    now = datetime.now(timezone.utc)
    install_time = (now - timedelta(minutes=random.randint(40, 120))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z+0100"
    current_time = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z+0100"
    
    return {
        "app_token": app_token,
        "event_token": event_token,
        "gps_adid": device_id,
        "android_uuid": android_uuid,
        "google_app_set_id": app_set_id,
        "push_token": push_token,
        "device_name": "2409FPCC4G",
        "device_type": "phone",
        "device_manufacturer": "Xiaomi",
        "hardware_name": "2409FPCC4G", 
        "os_name": "android",
        "os_version": "15",
        "api_level": "35",
        "os_build": "OS2.0.1.0.VNQMIXM",
        "language": "de",
        "country": "DE",
        "mcc": "262",
        "mnc": "02",
        "connectivity_type": "1",
        "installed_at": install_time,
        "created_at": current_time,
        "session_count": "1",
        "event_count": "1"
    }

# --- 3. EXECUTION LOGIC ---
def log_to_discord(title, fields, color="00ff00"):
    if not DISCORD_WEBHOOK_URL: return
    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
        embed = DiscordEmbed(title=title, color=color)
        embed.set_timestamp()
        for k, v in fields.items():
            embed.add_embed_field(name=k, value=str(v), inline=False)
        webhook.add_embed(embed)
        webhook.execute()
    except: pass

def execute_single_request(app_token, event_token, device_id, platform):
    url = "https://app.adjust.com/event"
    
    # Blueprint Data
    android_uuid = generate_android_uuid(device_id)
    app_set_id = generate_google_app_set_id(device_id)
    push_token = generate_push_token()
    payload = get_poco_blueprint(device_id, app_token, event_token, android_uuid, app_set_id, push_token)
    
    # User Agent
    ua = "Mozilla/5.0 (Linux; Android 15; 2409FPCC4G Build/OS2.0.1.0.VNQMIXM; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0.6723.102 Mobile Safari/537.36"
    
    headers = {
        'User-Agent': ua,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Client-SDK': 'android4.38.0' # SDK Version fixed
    }

    # Proxy holen
    proxies = get_proxy_dict(use_auto=True)

    try:
        # Request
        r = requests.post(url, data=payload, headers=headers, timeout=15, proxies=proxies)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)

# --- 4. JOB QUEUE PROCESSOR (CRON) ---
def process_job_queue():
    """
    Wird vom Cronjob aufgerufen. Prüft die DB auf fällige Tasks.
    """
    jobs = get_due_jobs()
    if not jobs:
        return {"status": "idle", "processed": 0}

    count = 0
    for job in jobs:
        try:
            job_id = job["id"]
            events = json.loads(job["events_pending"])
            
            if not events:
                # Job ist eigentlich fertig
                update_job(job_id, [], 0, "completed")
                continue

            # Nächstes Event holen
            evt_name = list(events.keys())[0]
            evt_token = events[evt_name]

            # Ausführen
            code, resp = execute_single_request(job["app_token"], evt_token, job["device_id"], job["platform"])
            
            # Loggen
            log_color = "00ff00" if code == 200 else "ff0000"
            log_to_discord(f"⏰ AUTO-JOB EXECUTION", {
                "App": job["app_name"],
                "Event": evt_name,
                "Status": code,
                "Resp": resp[:100]
            }, log_color)

            # Queue Updaten
            del events[evt_name] # Event entfernen
            
            if not events:
                # Fertig!
                update_job(job_id, [], 0, "completed")
                log_to_discord("✅ JOB COMPLETED", {"App": job["app_name"], "Device": job["device_id"]}, "0000ff")
            else:
                # Nächste Zeit berechnen
                delay = random.uniform(job["delay_min"], job["delay_max"]) * 3600
                next_ts = time.time() + delay
                next_str = datetime.fromtimestamp(next_ts).strftime('%H:%M:%S')
                
                update_job(job_id, events, next_ts, "pending")
                # Optional: Info log
                # log_to_discord("💤 SLEEPING", {"Next Run": next_str}, "808080")
            
            count += 1
            
        except Exception as e:
            print(f"CRON ERROR JOB {job['id']}: {e}")

    return {"status": "active", "processed": count}