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

# --- 1. PROXY & ID HELPERS ---
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

def generate_android_uuid(device_id):
    hash_obj = hashlib.md5(device_id.encode())
    return str(uuid.UUID(hash_obj.hexdigest()))

def generate_google_app_set_id(device_id):
    seed = device_id + "_appset"
    hash_obj = hashlib.md5(seed.encode())
    return str(uuid.UUID(hash_obj.hexdigest()))

def generate_push_token():
    part1 = ''.join(random.choices(string.ascii_letters + string.digits + "-_", k=22))
    part2 = ''.join(random.choices(string.ascii_letters + string.digits + "-_", k=134))
    return f"{part1}:APA91b{part2}"

# --- 2. BLUEPRINT POCO M7 ---
def get_poco_blueprint(device_id, app_token, event_token, android_uuid, app_set_id, push_token):
    now = datetime.now(timezone.utc)
    install_time = (now - timedelta(minutes=random.randint(40, 120))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z+0100"
    current_time = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z+0100"
    
    return {
        "app_token": app_token, "event_token": event_token,
        "gps_adid": device_id, "android_uuid": android_uuid,
        "google_app_set_id": app_set_id, "push_token": push_token,
        "device_name": "2409FPCC4G", "device_type": "phone",
        "device_manufacturer": "Xiaomi", "hardware_name": "2409FPCC4G", 
        "os_name": "android", "os_version": "15", "api_level": "35",
        "os_build": "OS2.0.1.0.VNQMIXM", "language": "de", "country": "DE",
        "mcc": "262", "mnc": "02", "connectivity_type": "1",
        "installed_at": install_time, "created_at": current_time,
        "session_count": "1", "event_count": "1"
    }

# --- 3. DISCORD & EXECUTE ---
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
    payload = get_poco_blueprint(
        device_id, app_token, event_token, 
        generate_android_uuid(device_id), 
        generate_google_app_set_id(device_id), 
        generate_push_token()
    )
    
    ua = "Mozilla/5.0 (Linux; Android 15; 2409FPCC4G Build/OS2.0.1.0.VNQMIXM; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0.6723.102 Mobile Safari/537.36"
    headers = {'User-Agent': ua, 'Content-Type': 'application/x-www-form-urlencoded', 'Client-SDK': 'android4.38.0'}
    
    try:
        r = requests.post(url, data=payload, headers=headers, timeout=15, proxies=get_proxy_dict(True))
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)

# --- 4. JOB PROCESSOR (CRON) ---
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

            code, resp = execute_single_request(job["app_token"], evt_token, job["device_id"], job["platform"])
            
            log_color = "00ff00" if code == 200 else "ff0000"
            log_to_discord(f"⏰ AUTO-EXEC: {evt_name}", {
                "App": job["app_name"], "Status": code, "Resp": resp[:100]
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