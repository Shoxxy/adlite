import time
import random
import requests
import datetime
import sqlite3
import threading
import os
import json
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------
# 1. USER AGENT MANAGER (Nur für DB Storage)
# ---------------------------------------------------------
class UserAgentManager:
    def __init__(self):
        self.db_path = "/tmp/user_agents.db"
        if os.name == 'nt': self.db_path = "user_agents.db"
        self.lock = threading.Lock()
        self._init_db()
    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('''CREATE TABLE IF NOT EXISTS agents (device_id TEXT PRIMARY KEY, user_agent TEXT, tracker_link TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                try: cursor.execute("ALTER TABLE agents ADD COLUMN tracker_link TEXT")
                except: pass
        except: pass
    def get_or_create(self, device_id, platform, browser=None, model=None, os_ver=None, use_random=False, force_update=False, save_to_db=True, incoming_link=None):
        platform = platform.lower() if platform else "android"
        if not browser or not browser.strip(): browser = "Chrome"
        if not model or not model.strip(): model = "Samsung Galaxy S23" if platform == "android" else "iPhone 15"
        if not os_ver or not os_ver.strip(): os_ver = "14" if platform == "android" else "17.4"
        should_gen = force_update or use_random
        new_ua = self._generate_random(platform) if use_random else self._construct_specific(platform, browser, model, os_ver)
        final_ua = new_ua; final_link = incoming_link; is_cached = False
        try:
            with self.lock:
                with sqlite3.connect(self.db_path, check_same_thread=False, timeout=5) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT user_agent, tracker_link FROM agents WHERE device_id = ?", (device_id,))
                    row = cur.fetchone()
                    if row and not should_gen:
                        final_ua = row[0]; saved_link = row[1]; is_cached = True
                        if not final_link and saved_link: final_link = saved_link
                    if save_to_db:
                        if should_gen or not row:
                            cur.execute("INSERT OR REPLACE INTO agents (device_id, user_agent, tracker_link) VALUES (?, ?, ?)", (device_id, final_ua, final_link))
                            conn.commit()
                        elif row and incoming_link:
                            cur.execute("UPDATE agents SET tracker_link = ? WHERE device_id = ?", (incoming_link, device_id))
                            conn.commit()
                            final_link = incoming_link
                    return final_ua, is_cached, final_link
        except: return final_ua, False, final_link
    def _generate_random(self, p):
        if p == "android": return f"Mozilla/5.0 (Linux; Android 14; {random.choice(['SM-S918B','Pixel 8 Pro'])}; de-DE) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
        return "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"
    def _construct_specific(self, p, b, m, o):
        if p == "android": return f"Mozilla/5.0 (Linux; Android {o}; {m}) AppleWebKit/537.36 (KHTML, like Gecko) {b}/121.0.0.0 Mobile Safari/537.36"
        else: return f"Mozilla/5.0 (iPhone; CPU iPhone OS {o.replace('.', '_')} like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) {b}/Custom Mobile/15E148"

ua_manager = UserAgentManager()

# --- PROXY ENGINE ---
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

# ---------------------------------------------------------
# 3. HELPER FUNCTIONS
# ---------------------------------------------------------
def extract_id_and_platform_from_link(link):
    if not link or "adjust" not in link: return None, None
    try:
        parsed = urlparse(link); q = parse_qs(parsed.query)
        if "gps_adid" in q: return q["gps_adid"][0], "android"
        if "adid" in q: return q["adid"][0], "android"
        if "idfa" in q: return q["idfa"][0], "ios"
    except: pass
    return None, None

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
# 4. CORE: GENERATE SDK PAYLOAD (Like fix14.py)
# ---------------------------------------------------------
def generate_adjust_payload(event_token, app_token, device_id, platform, skadn=None, tracker_link=None):
    base_url = "https://app.adjust.com/event"
    current_time = str(int(time.time()))
    
    # 1. SDK STANDARD DATA (Aus fix14.py)
    # Wichtig: Wir nutzen environment='production', damit es zählt.
    data = {
        'app_token': app_token,
        'event_token': event_token,
        'environment': 'production',
        'created_at': current_time,
        'sent_at': current_time,
        'session_count': '1', 
    }
    
    # 2. DEVICE DATA (Simuliert das echte Gerät)
    if platform == "android":
        data.update({
            'gps_adid': device_id, # DAS MUSS EXAKT STIMMEN!
            'device_manufacturer': 'samsung',
            'device_name': 'SM-G998B',
            'os_name': 'android', 
            'os_version': '13'
        })
    else:
        data.update({
            'idfa': device_id, # DAS MUSS EXAKT STIMMEN!
            'device_manufacturer': 'apple',
            'device_name': 'iPhone14,2',
            'os_name': 'ios', 
            'os_version': '16.0'
        })

    if skadn and platform == "ios":
        data['skadn_conv_value'] = str(skadn)

    extracted_ip = None
    
    # 3. LINK PARSING & INJECTION (Das Herzstück)
    # Wir nehmen ALLE Parameter aus dem Link und packen sie in partner_params.
    # Adjust leitet diese dann an die Offerwall weiter.
    partner_params_dict = {}

    if tracker_link and "adjust" in tracker_link:
        try:
            parsed = urlparse(tracker_link)
            query_params = parse_qs(parsed.query)
            
            # Diese technischen Parameter brauchen wir nicht im Partner-Block
            blocked_keys = ["gps_adid", "adid", "idfa", "app_token", "skadn", "s2s", "event_token", "environment", "created_at", "sent_at", "session_count"]
            
            for key, val_list in query_params.items():
                val = val_list[0]
                
                # Alles was unbekannt ist (click_id, sub_id, oid...) kommt in die Partner Params
                if key not in blocked_keys:
                    partner_params_dict[key] = val

                # IP & Referrer extrahieren wir für den Header/Body
                if key == "referrer": data["install_referrer"] = val; continue
                if key in ["ip", "device_ip", "user_ip", "ip_address"]: extracted_ip = val; data["ip_address"] = val; continue
        except: pass
    
    # Hier packen wir die Link-Daten in das JSON Format, das Adjust erwartet
    if partner_params_dict:
        json_params = json.dumps(partner_params_dict)
        data["partner_params"] = json_params
        data["callback_params"] = json_params 

    return base_url, data, extracted_ip, current_time

# ---------------------------------------------------------
# 5. CORE: SEND REQUEST (Like fix14.py)
# ---------------------------------------------------------
def send_request_auto_detect(base_url, data_payload, current_time, platform, spoof_ip=None, proxies=None):
    headers = {}
    
    # SDK HEADERS (1:1 aus fix14.py übernommen)
    # Damit geben wir vor, die echte App zu sein.
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

    # Stealth: Wir geben die IP aus dem Link weiter (falls vorhanden)
    if spoof_ip:
        headers["X-Forwarded-For"] = spoof_ip
        headers["X-Real-IP"] = spoof_ip
        headers["Client-IP"] = spoof_ip

    try:
        # POST Request (SDK Standard)
        r = requests.post(base_url, data=data_payload, headers=headers, timeout=10, proxies=proxies)
        
        status = r.status_code
        resp_text = r.text
        
        # 200 OK ist das Ziel.
        if status == 200:
            return f"Status {status}: OK | {resp_text}"
        
        return f"Status {status}: {resp_text}"
    except Exception as e:
        return f"Request Failed: {str(e)}"