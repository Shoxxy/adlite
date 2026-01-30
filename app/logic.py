import time
import random
import requests
import json
import uuid
import hashlib
import string
import os
from datetime import datetime, timezone, timedelta
from discord_webhook import DiscordWebhook, DiscordEmbed

# Versuche Import aus app.database oder lokal
try:
    from app.database import update_job, get_due_jobs
except ImportError:
    from database import update_job, get_due_jobs

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# --- 1. PROXY & NETWORK ---
class AutoProxyEngine:
    def __init__(self): 
        self.cached_proxies = []
        self.last_fetch = 0
    def fetch_proxies(self):
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
        except: pass
        return []
proxy_engine = AutoProxyEngine()

def get_proxy_dict(use_auto=True):
    if use_auto:
        raw = proxy_engine.fetch_proxies()
        if raw:
            p = random.choice(raw[:10])
            return {"http": f"http://{p}", "https": f"http://{p}"}
    return None

# --- 2. ID GENERATORS ---
def generate_uuid_from_string(seed_str):
    """Erzeugt eine deterministische UUID aus einem String"""
    hash_obj = hashlib.md5(seed_str.encode())
    return str(uuid.UUID(hash_obj.hexdigest()))

def generate_push_token():
    """Simuliert FCM (Android) oder APNS (iOS) Token"""
    part1 = ''.join(random.choices(string.ascii_letters + string.digits + "-_", k=22))
    part2 = ''.join(random.choices(string.ascii_letters + string.digits + "-_", k=134))
    return f"{part1}:{part2}"

# --- 3. BLUEPRINTS ---

def get_poco_blueprint(device_id, app_token, event_token):
    """ANDROID PROFILE: POCO M7 Pro 5G"""
    now = datetime.now(timezone.utc)
    # Installation vor zufällig 40-120 Minuten
    install_time = (now - timedelta(minutes=random.randint(40, 120))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z+0100"
    current_time = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z+0100"
    
    android_uuid = generate_uuid_from_string(device_id)
    app_set_id = generate_uuid_from_string(device_id + "_appset")
    
    return {
        "app_token": app_token, "event_token": event_token,
        "gps_adid": device_id,  # WICHTIG: GAID
        "android_uuid": android_uuid,
        "google_app_set_id": app_set_id, 
        "push_token": generate_push_token(),
        "device_name": "2409FPCC4G", "device_type": "phone",
        "device_manufacturer": "Xiaomi", "hardware_name": "2409FPCC4G", 
        "os_name": "android", "os_version": "15", "api_level": "35",
        "os_build": "OS2.0.1.0.VNQMIXM", "language": "de", "country": "DE",
        "mcc": "262", "mnc": "02", "connectivity_type": "1",
        "installed_at": install_time, "created_at": current_time,
        "session_count": "1", "event_count": "1"
    }, "Mozilla/5.0 (Linux; Android 15; 2409FPCC4G Build/OS2.0.1.0.VNQMIXM; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0.6723.102 Mobile Safari/537.36"

def get_ios_blueprint(device_id, app_token, event_token):
    """IOS PROFILE: iPhone 15 Pro (iOS 17.5.1)"""
    now = datetime.now(timezone.utc)
    install_time = (now - timedelta(minutes=random.randint(40, 120))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z+0100"
    current_time = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z+0100"
    
    idfv = generate_uuid_from_string(device_id + "_idfv")
    
    return {
        "app_token": app_token, "event_token": event_token,
        "idfa": device_id,  # WICHTIG: IDFA statt gps_adid
        "idfv": idfv,
        "push_token": generate_push_token(), # APNS Token Simulation
        "device_name": "iPhone16,1", # iPhone 15 Pro Modell-ID
        "device_type": "phone",
        "device_manufacturer": "Apple", 
        "os_name": "ios", 
        "os_version": "17.5.1", 
        "language": "de", "country": "DE",
        "mcc": "262", "mnc": "02", "connectivity_type": "1",
        "installed_at": install_time, "created_at": current_time,
        "session_count": "1", "event_count": "1",
        "tracking_enabled": "1" # ATT Opt-In simuliert
    }, "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"

# --- 4. DISCORD & EXECUTE ---
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
    
    # 1. Blueprint Auswahl basierend auf Platform
    if platform.lower() == "ios":
        payload, ua = get_ios_blueprint(device_id, app_token, event_token)
        client_sdk = "ios4.38.0"
    else:
        # Default Android (POCO)
        payload, ua = get_poco_blueprint(device_id, app_token, event_token)
        client_sdk = "android4.38.0"
    
    headers = {
        'User-Agent': ua, 
        'Content-Type': 'application/x-www-form-urlencoded', 
        'Client-SDK': client_sdk
    }
    
    try:
        # Request senden (mit Proxy)
        r = requests.post(url, data=payload, headers=headers, timeout=15, proxies=get_proxy_dict(True))
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)

# --- 5. JOB PROCESSOR (CRON) ---
def process_job_queue():
    jobs = get_due_jobs()
    if not jobs: return {"status": "idle", "processed": 0}

    count = 0
    for job in jobs:
        try:
            job_id = job["id"]
            events = json.loads(job["events_pending"])
            
            if not events:
                update_job(job_id, [], 0, "completed")
                continue

            evt_name = list(events.keys())[0]
            evt_token = events[evt_name]

            # Hier wird nun 'platform' korrekt durchgereicht
            code, resp = execute_single_request(
                job["app_token"], 
                evt_token, 
                job["device_id"], 
                job["platform"]
            )
            
            log_color = "00ff00" if code == 200 else "ff0000"
            log_to_discord(f"⏰ AUTO-EXEC: {evt_name}", {
                "App": job["app_name"], 
                "Plat": job["platform"].upper(),
                "Status": code, 
                "Resp": resp[:100]
            }, log_color)

            del events[evt_name]
            
            if not events:
                update_job(job_id, [], 0, "completed")
                log_to_discord("✅ JOB COMPLETED", {"App": job["app_name"], "Device": job["device_id"]}, "0000ff")
            else:
                delay = random.uniform(job["delay_min"], job["delay_max"]) * 3600
                next_ts = time.time() + delay
                update_job(job_id, events, next_ts, "pending")
            
            count += 1
        except Exception as e:
            print(f"CRON ERROR JOB {job['id']}: {e}")

    return {"status": "active", "processed": count}