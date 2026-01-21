import time
import random
import requests
import datetime
import sqlite3
import threading
import os
import json
import uuid
import hashlib
from urllib.parse import urlparse, parse_qs, unquote

# ---------------------------------------------------------
# 1. HELPER: UUID GENERATOR
# ---------------------------------------------------------
def generate_android_uuid(device_id):
    hash_obj = hashlib.md5(device_id.encode())
    guid = uuid.UUID(hash_obj.hexdigest())
    return str(guid)

# ---------------------------------------------------------
# 2. PROXY & NETWORK
# ---------------------------------------------------------
GLOBAL_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
GLOBAL_SESSION.mount('https://', adapter)

class AutoProxyEngine:
    def __init__(self): self.cached_proxies = []; self.last_fetch = 0
    def fetch_german_proxies(self):
        if self.cached_proxies and (time.time() - self.last_fetch < 300): return self.cached_proxies
        try:
            url = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=3000&country=DE&ssl=all&anonymity=all"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                proxies = [p.strip() for p in r.text.split("\n") if p.strip()]
                if proxies: self.cached_proxies = proxies; self.last_fetch = time.time(); return proxies
        except: pass
        return []
proxy_engine = AutoProxyEngine()

def get_proxy_dict(manual_proxy=None, use_auto_proxy=False):
    if manual_proxy and len(manual_proxy) > 5:
        fmt = f"http://{manual_proxy}" if not manual_proxy.startswith("http") else manual_proxy
        return {"http": fmt, "https": fmt}
    elif use_auto_proxy:
        raw_list = proxy_engine.fetch_german_proxies()
        if raw_list:
            p = random.choice(raw_list[:5])
            return {"http": f"http://{p}", "https": f"http://{p}"}
    return None

# ---------------------------------------------------------
# 3. SKADN CONFIG (Das fehlte!)
# ---------------------------------------------------------
SKADN_APP_CONFIGS = {"TikTok": 8, "Snapchat": 12, "Facebook": 16, "Google": 20, "Unity": 24}

def get_skadn_value_for_app(app_name):
    for k, v in SKADN_APP_CONFIGS.items(): 
        if k.lower() in app_name.lower(): return v
    return 8

# ---------------------------------------------------------
# 4. UA MANAGER (DB)
# ---------------------------------------------------------
class UserAgentManager:
    def __init__(self):
        self.db_path = "/tmp/user_agents.db"
        if os.name == 'nt': self.db_path = "user_agents.db"
        self._init_db()
    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('''CREATE TABLE IF NOT EXISTS agents (device_id TEXT PRIMARY KEY, user_agent TEXT, tracker_link TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                try: cursor.execute("ALTER TABLE agents ADD COLUMN tracker_link TEXT")
                except: pass
        except: pass
    def get_or_create(self, device_id, platform, save_to_db=True, incoming_link=None):
        final_link = incoming_link
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False, timeout=5) as conn:
                cur = conn.cursor()
                cur.execute("SELECT tracker_link FROM agents WHERE device_id = ?", (device_id,))
                row = cur.fetchone()
                if row and not final_link: final_link = row[0]
                if save_to_db and incoming_link:
                    cur.execute("INSERT OR REPLACE INTO agents (device_id, user_agent, tracker_link) VALUES (?, ?, ?)", (device_id, "POCO-M7-Pro-Mode", final_link))
                    conn.commit()
        except: pass
        return None, False, final_link

ua_manager = UserAgentManager()

def extract_id_and_platform_from_link(link):
    if not link or "adjust" not in link: return None, None
    try:
        parsed = urlparse(link); q = parse_qs(parsed.query)
        if "gps_adid" in q: return q["gps_adid"][0], "android"
        if "adid" in q: return q["adid"][0], "android"
    except: pass
    return None, None

# ---------------------------------------------------------
# 5. BLUEPRINT: POCO M7 Pro 5G (Android 15)
# ---------------------------------------------------------
def get_poco_blueprint(device_id, app_token, event_token, android_uuid):
    now = datetime.datetime.now(datetime.timezone.utc)
    install_time = (now - datetime.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z+0100"
    current_time = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z+0100"
    
    data = {
        "app_token": app_token,
        "event_token": event_token,
        "gps_adid": device_id,
        "android_uuid": android_uuid,
        
        # Device Specs: POCO M7 Pro 5G (Model: 2409FPCC4G)
        "device_name": "2409FPCC4G",
        "device_type": "phone",
        "device_manufacturer": "Xiaomi",
        "hardware_name": "2409FPCC4G",
        
        # Display
        "display_width": "2400",
        "display_height": "1080",
        "screen_size": "large",
        "screen_format": "long",
        "screen_density": "xxhdpi",
        
        # CPU
        "cpu_type": "arm64-v8a", 
        
        # OS (Android 15 / HyperOS 2)
        "os_name": "android",
        "os_version": "15",
        "api_level": "35",
        "os_build": "OS2.0.1.0.VNQMIXM",
        
        # Locale & Network
        "language": "de",
        "country": "DE",
        "mcc": "262",
        "mnc": "02",
        "connectivity_type": "1",
        
        # App Info
        "package_name": "com.yottagames.mafiawar",
        "app_version": "1.8.181",
        "tracking_enabled": "1",
        "attribution_deeplink": "1",
        "environment": "production",
        "needs_response_details": "1",
        "gps_adid_src": "service",
        "gps_adid_attempt": "1",
        
        # Session
        "installed_at": install_time,
        "created_at": current_time,
        "sent_at": current_time,
        "session_count": "1",
        "subsession_count": "1",
        "foreground": "1",
        "offline_mode_enabled": "0"
    }
    return data

# ---------------------------------------------------------
# 6. PAYLOAD GENERATOR
# ---------------------------------------------------------
def generate_adjust_payload(event_token, app_token, device_id, platform, skadn=None, tracker_link=None):
    base_url = "https://app.adjust.com/event"
    android_uuid = generate_android_uuid(device_id)
    data = get_poco_blueprint(device_id, app_token, event_token, android_uuid)

    partner_params_dict = {}
    extracted_ip = None
    
    potential_id_keys = ["click_id", "clickid", "trans_id", "transaction_id", "sub_id", "aff_sub", "oid", "uid"]
    found_callback_id = None

    if tracker_link and "adjust" in tracker_link:
        try:
            parsed = urlparse(tracker_link)
            query_params = parse_qs(parsed.query)
            blocked_keys = list(data.keys()) + ["idfa", "skadn", "s2s", "referrer"]
            
            for key, val_list in query_params.items():
                val = val_list[0]
                if key not in blocked_keys and key != "gps_adid":
                    partner_params_dict[key] = val
                key_lower = key.lower()
                if not found_callback_id:
                    for pid in potential_id_keys:
                        if pid in key_lower: found_callback_id = val; break
                if key in ["ip", "device_ip", "user_ip", "ip_address"]: 
                    extracted_ip = val
                    data["ip_address"] = val
                if key == "referrer":
                    decoded_ref = unquote(val)
                    data["install_referrer"] = decoded_ref
                    data["referrer"] = decoded_ref
        except: pass
    
    if found_callback_id:
        data["callback_id"] = found_callback_id
    
    if partner_params_dict:
        json_params = json.dumps(partner_params_dict)
        data["partner_params"] = json_params
        data["callback_params"] = json_params

    ts_header = str(int(time.time()))
    return base_url, data, extracted_ip, ts_header

# ---------------------------------------------------------
# 7. SENDER (POCO Header)
# ---------------------------------------------------------
def send_request_auto_detect(base_url, data_payload, ts_header, platform, spoof_ip=None, proxies=None):
    user_agent = "Mozilla/5.0 (Linux; Android 15; 2409FPCC4G Build/OS2.0.1.0.VNQMIXM; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0.6723.102 Mobile Safari/537.36"
    
    headers = {
        'User-Agent': user_agent, 
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Adjust-SDK-Version': '4.38.0',
        'X-Adjust-Build': ts_header,
        'Client-SDK': 'android4.38.0'
    }

    if spoof_ip:
        headers["X-Forwarded-For"] = spoof_ip
        headers["X-Real-IP"] = spoof_ip
        headers["Client-IP"] = spoof_ip

    try:
        r = requests.post(base_url, data=data_payload, headers=headers, timeout=10, proxies=proxies)
        status = r.status_code
        resp_text = r.text
        
        if status == 200:
            return f"Status {status}: OK | {resp_text}"
        return f"Status {status}: {resp_text}"
    except Exception as e:
        return f"Request Failed: {str(e)}"