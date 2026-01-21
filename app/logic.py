import time
import random
import requests
import datetime
import sqlite3
import threading
import os
import json
from urllib.parse import urlparse, parse_qs

# --- UA MANAGER (Bleibt erhalten für Kompatibilität) ---
class UserAgentManager:
    def __init__(self):
        self.db_path = "/tmp/user_agents.db" if os.name != 'nt' else "user_agents.db"
        self._init_db()
    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                conn.cursor().execute('CREATE TABLE IF NOT EXISTS agents (device_id TEXT PRIMARY KEY, user_agent TEXT, tracker_link TEXT)')
        except: pass
ua_manager = UserAgentManager()

# --- PROXY ---
GLOBAL_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
GLOBAL_SESSION.mount('https://', adapter)

SKADN_APP_CONFIGS = {"TikTok": 8, "Snapchat": 12, "Facebook": 16, "Google": 20, "Unity": 24}
def get_skadn_value_for_app(app_name):
    for k, v in SKADN_APP_CONFIGS.items(): 
        if k.lower() in app_name.lower(): return v
    return 8

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

# --- SDK LOGIC (aus fix14.py) ---

def extract_id_and_platform_from_link(link):
    if not link or "adjust" not in link: return None, None
    try:
        parsed = urlparse(link); q = parse_qs(parsed.query)
        if "gps_adid" in q: return q["gps_adid"][0], "android"
        if "adid" in q: return q["adid"][0], "android"
        if "idfa" in q: return q["idfa"][0], "ios"
    except: pass
    return None, None

def generate_adjust_payload(event_token, app_token, device_id, platform, skadn=None, tracker_link=None):
    # Basis URL (SDK Endpoint aus fix14.py)
    base_url = "https://app.adjust.com/event"
    
    current_time = str(int(time.time()))
    
    # PAYLOAD AUFBAU (Exakt wie send_post_event in fix14.py)
    data = {
        'app_token': app_token,
        'event_token': event_token,
        'environment': 'production',
        'created_at': current_time,
        'sent_at': current_time,
        'session_count': '1',
    }
    
    # Plattform-spezifische Daten (aus fix14.py)
    if platform == "android":
        data.update({
            'gps_adid': device_id,
            'device_manufacturer': 'samsung', 
            'device_name': 'SM-G998B',
            'os_name': 'android', 
            'os_version': '13'
        })
    else:
        data.update({
            'idfa': device_id,
            'device_manufacturer': 'apple',
            'device_name': 'iPhone14,2',
            'os_name': 'ios',
            'os_version': '16.0'
        })

    if skadn and platform == "ios":
        data['skadn_conv_value'] = str(skadn)

    extracted_ip = None
    
    # LINK PARSING & ID INJECTION
    potential_id_keys = ["click_id", "clickid", "trans_id", "transaction_id", "sub_id", "aff_sub", "oid", "uid"]
    found_callback_id = None
    partner_params_dict = {}

    if tracker_link and "adjust" in tracker_link:
        try:
            parsed = urlparse(tracker_link)
            query_params = parse_qs(parsed.query)
            blocked_keys = ["gps_adid", "adid", "idfa", "app_token", "skadn", "s2s", "event_token", "environment", "created_at", "sent_at"]
            
            for key, val_list in query_params.items():
                val = val_list[0]
                
                if key not in blocked_keys:
                    partner_params_dict[key] = val

                key_lower = key.lower()
                if not found_callback_id:
                    for pid in potential_id_keys:
                        if pid in key_lower: found_callback_id = val; break

                if key == "referrer": data["install_referrer"] = val; continue
                if key in ["ip", "device_ip", "user_ip", "ip_address"]: extracted_ip = val; data["ip_address"] = val; continue
        except: pass
    
    # Callback ID (aus Link)
    if found_callback_id:
        data["callback_id"] = found_callback_id
    
    # Partner Params (JSON)
    if partner_params_dict:
        json_params = json.dumps(partner_params_dict)
        data["partner_params"] = json_params
        data["callback_params"] = json_params

    return base_url, data, extracted_ip, current_time

def send_request_auto_detect(base_url, data_payload, current_time, platform, spoof_ip=None, manual_proxy=None, use_auto_proxy=False):
    
    # HEADER (Exakt wie fix14.py)
    headers = {}
    if platform == "android":
        headers = {
            'User-Agent': 'Adjust/4.38.0 (Android 13; SM-G998B; Build/TP1A.220624.014)',
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Adjust-SDK-Version': '4.38.0',
            'X-Adjust-Build': current_time,
            'Client-SDK': 'android4.38.0'
        }
    else:
        headers = {
            'User-Agent': 'Adjust/4.38.0 (iOS 16.0; iPhone14,2; Build/20A362)',
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Adjust-SDK-Version': '4.38.0',
            'X-Adjust-Build': current_time,
            'Client-SDK': 'ios4.38.0'
        }

    if spoof_ip:
        headers["X-Forwarded-For"] = spoof_ip
        headers["X-Real-IP"] = spoof_ip
        headers["Client-IP"] = spoof_ip

    proxies_to_try = []
    if manual_proxy and len(manual_proxy) > 5:
        fmt = f"http://{manual_proxy}" if not manual_proxy.startswith("http") else manual_proxy
        proxies_to_try.append(fmt)
    elif use_auto_proxy:
        raw_list = proxy_engine.fetch_german_proxies()
        random.shuffle(raw_list)
        for p in raw_list[:5]: proxies_to_try.append(f"http://{p}")
    if not proxies_to_try: proxies_to_try.append(None)

    last_error = ""; attempt_log = []
    
    for proxy in proxies_to_try:
        current_proxies = {"http": proxy, "https": proxy} if proxy else None
        p_name = proxy if proxy else "Direct"
        try:
            # SDK POST REQUEST
            r = requests.post(base_url, data=data_payload, headers=headers, timeout=10, proxies=current_proxies)
            
            status = r.status_code
            resp_text = r.text
            
            if status == 200:
                msg = f"OK (Via {p_name})"
                if resp_text: msg += f" | {resp_text}"
                return f"Status {status}: {msg}"
            
            return f"Status {status}: {resp_text} (via {p_name})"
            
        except Exception as e:
            last_error = str(e)
            attempt_log.append(f"{p_name} failed")
            continue

    return f"Request Failed. {', '.join(attempt_log)}. {last_error}"