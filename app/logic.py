import time
import random
import requests
import datetime
import sqlite3
import threading
import os
import traceback
from urllib.parse import urlparse, parse_qs, urlencode

# --- USER AGENT MANAGER MIT LINK-SPEICHERUNG ---
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
                # Tabelle erstellen
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS agents (
                        device_id TEXT PRIMARY KEY,
                        user_agent TEXT,
                        tracker_link TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                # Migration: Spalte hinzufügen falls sie fehlt (für Updates)
                try: cursor.execute("ALTER TABLE agents ADD COLUMN tracker_link TEXT")
                except: pass
        except: pass

    def get_or_create(self, device_id, platform, browser=None, model=None, os_ver=None, use_random=False, force_update=False, save_to_db=True, incoming_link=None):
        platform = platform.lower() if platform else "android"
        browser = browser if browser and browser.strip() else None
        model = model if model and model.strip() else None
        os_ver = os_ver if os_ver and os_ver.strip() else None
        
        should_gen = (browser is not None or model is not None or os_ver is not None) or force_update or use_random
        new_ua = self._generate_random(platform) if use_random or (not browser and not model) else self._construct_specific(platform, browser, model, os_ver)
        
        final_ua = new_ua
        final_link = incoming_link
        is_cached = False

        try:
            with self.lock:
                with sqlite3.connect(self.db_path, check_same_thread=False, timeout=5) as conn:
                    cur = conn.cursor()
                    
                    # Lesen
                    cur.execute("SELECT user_agent, tracker_link FROM agents WHERE device_id = ?", (device_id,))
                    row = cur.fetchone()
                    
                    if row and not should_gen:
                        final_ua = row[0]
                        saved_link = row[1]
                        is_cached = True
                        # Wenn wir keinen neuen Link haben, nehmen wir den gespeicherten
                        if not final_link and saved_link:
                            final_link = saved_link
                    
                    # Schreiben
                    if save_to_db:
                        if should_gen or not row:
                            cur.execute("INSERT OR REPLACE INTO agents (device_id, user_agent, tracker_link) VALUES (?, ?, ?)", (device_id, final_ua, final_link))
                            conn.commit()
                        elif row and incoming_link:
                            # UA behalten, aber Link updaten
                            cur.execute("UPDATE agents SET tracker_link = ? WHERE device_id = ?", (incoming_link, device_id))
                            conn.commit()
                            final_link = incoming_link
                    
                    return final_ua, is_cached, final_link
        except:
            return final_ua, False, final_link

    def _generate_random(self, p):
        if p == "android":
            return f"Mozilla/5.0 (Linux; Android 14; {random.choice(['SM-S918B','Pixel 8 Pro','2308CPXD0C'])}; de-DE) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
        return "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"

    def _construct_specific(self, p, b, m, o):
        return f"Mozilla/5.0 ({p}; {o}; {m}) {b}/Custom"

ua_manager = UserAgentManager()

# --- CONFIG & SESSIONS ---
GLOBAL_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
GLOBAL_SESSION.mount('https://', adapter)

SKADN_APP_CONFIGS = {"TikTok": 8, "Snapchat": 12, "Facebook": 16, "Google": 20, "Unity": 24}

def get_skadn_value_for_app(app_name):
    for k, v in SKADN_APP_CONFIGS.items(): 
        if k.lower() in app_name.lower(): return v
    return 8

# --- AUTO PROXY ENGINE ---
class AutoProxyEngine:
    def __init__(self):
        self.cached_proxies = []
        self.last_fetch = 0
        
    def fetch_german_proxies(self):
        # Cache 5 Minuten
        if self.cached_proxies and (time.time() - self.last_fetch < 300):
            return self.cached_proxies
        try:
            # ProxyScrape API (DE, HTTP)
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

# --- LINK PARSER & URL GENERATOR ---
def extract_id_and_platform_from_link(link):
    if not link or "adjust" not in link: return None, None
    try:
        parsed = urlparse(link)
        q = parse_qs(parsed.query)
        if "gps_adid" in q: return q["gps_adid"][0], "android"
        if "adid" in q: return q["adid"][0], "android"
        if "idfa" in q: return q["idfa"][0], "ios"
    except: pass
    return None, None

def generate_adjust_url(event_token, app_token, device_id, platform, skadn=None, tracker_link=None):
    base = "https://app.adjust.com"
    params = {"app_token": app_token, "s2s": "1"}
    
    if platform == "android":
        params["gps_adid"] = device_id; params["adid"] = device_id
    else:
        params["idfa"] = device_id
        if skadn: params["skadn"] = skadn

    extracted_ip = None
    has_referrer = False

    # Dynamic Pass-Through
    if tracker_link and "adjust" in tracker_link:
        try:
            parsed = urlparse(tracker_link)
            query_params = parse_qs(parsed.query)
            blocked_keys = ["gps_adid", "adid", "idfa", "app_token", "skadn", "s2s"]
            
            for key, val_list in query_params.items():
                val = val_list[0]
                
                # Referrer Mapping
                if key == "referrer":
                    params["install_referrer"] = val
                    has_referrer = True
                    continue
                
                # IP Extraction
                if key in ["ip", "device_ip", "user_ip", "ip_address"]:
                    extracted_ip = val
                    params["ip_address"] = val
                    continue

                if key not in blocked_keys:
                    params[key] = val
        except: pass
        
    # Time Travel (Google Play Referrer Timestamps)
    if has_referrer and platform == "android":
        now = int(time.time())
        params["referrer_click_timestamp_seconds"] = str(now - random.randint(45, 120))
        params["install_begin_timestamp_seconds"] = str(now - random.randint(5, 30))

    return f"{base}/{event_token}?{urlencode(params)}", extracted_ip

# --- REQUEST SENDER (MIT PROXY LOOP) ---
def send_request_auto_detect(url, platform, use_get, skadn=None, user_agent=None, spoof_ip=None, manual_proxy=None, use_auto_proxy=False):
    headers = {}
    if user_agent: headers["User-Agent"] = user_agent
    headers["Accept-Language"] = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    
    # Header Spoofing
    if spoof_ip:
        headers["X-Forwarded-For"] = spoof_ip
        headers["X-Real-IP"] = spoof_ip
        headers["Client-IP"] = spoof_ip

    # Proxy Liste erstellen
    proxies_to_try = []

    if manual_proxy and len(manual_proxy) > 5:
        # Priorität 1: Manueller Proxy
        fmt = f"http://{manual_proxy}" if not manual_proxy.startswith("http") else manual_proxy
        proxies_to_try.append(fmt)
    
    elif use_auto_proxy:
        # Priorität 2: Auto Proxy
        raw_list = proxy_engine.fetch_german_proxies()
        random.shuffle(raw_list)
        for p in raw_list[:5]: # Max 5 Versuche
            proxies_to_try.append(f"http://{p}")
    
    if not proxies_to_try:
        proxies_to_try.append(None) # Fallback: Direkt senden

    # Loop
    last_error = ""
    attempt_log = []

    for proxy in proxies_to_try:
        current_proxies = {"http": proxy, "https": proxy} if proxy else None
        p_name = proxy if proxy else "Direct"
        
        try:
            if use_get: 
                r = GLOBAL_SESSION.get(url, headers=headers, timeout=5, proxies=current_proxies)
            else: 
                r = GLOBAL_SESSION.post(url, headers=headers, timeout=5, proxies=current_proxies)
            
            # Erfolg!
            return f"{r.text} (via {p_name})"
            
        except Exception as e:
            last_error = str(e)
            attempt_log.append(f"{p_name} failed")
            continue

    return f"Request Failed. Attempts: {', '.join(attempt_log)}. Last Error: {last_error}"