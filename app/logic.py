import time
import random
import requests
import datetime
import sqlite3
import threading
import os
import traceback
from urllib.parse import urlparse, parse_qs, urlencode

# ---------------------------------------------------------
# 1. USER AGENT & DATABASE MANAGER
# ---------------------------------------------------------
class UserAgentManager:
    def __init__(self):
        # Pfad anpassen für Windows/Linux Kompatibilität
        self.db_path = "/tmp/user_agents.db"
        if os.name == 'nt': 
            self.db_path = "user_agents.db"
        self.lock = threading.Lock()
        self._init_db()
        
    def _init_db(self):
        """Erstellt DB und migriert Schema falls nötig"""
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS agents (
                        device_id TEXT PRIMARY KEY,
                        user_agent TEXT,
                        tracker_link TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                # Spalte hinzufügen falls sie fehlt (Update von alter Version)
                try: 
                    cursor.execute("ALTER TABLE agents ADD COLUMN tracker_link TEXT")
                except: 
                    pass
        except Exception as e:
            print(f"DB Init Error: {e}")

    def get_or_create(self, device_id, platform, browser=None, model=None, os_ver=None, use_random=False, force_update=False, save_to_db=True, incoming_link=None):
        platform = platform.lower() if platform else "android"
        
        # --- FIX: FALLBACKS GEGEN "NONE" ---
        # Damit niemals "Mozilla/5.0 (android; None; None)" entsteht
        if not browser or not browser.strip():
            browser = "Chrome"
        if not model or not model.strip():
            model = "Samsung Galaxy S23" if platform == "android" else "iPhone 15"
        if not os_ver or not os_ver.strip():
            os_ver = "14" if platform == "android" else "17.4"

        should_gen = force_update or use_random
        
        # Generierung
        if use_random:
            new_ua = self._generate_random(platform)
        else:
            new_ua = self._construct_specific(platform, browser, model, os_ver)
        
        final_ua = new_ua
        final_link = incoming_link
        is_cached = False

        try:
            with self.lock:
                with sqlite3.connect(self.db_path, check_same_thread=False, timeout=5) as conn:
                    cur = conn.cursor()
                    
                    # 1. Prüfen ob ID existiert
                    cur.execute("SELECT user_agent, tracker_link FROM agents WHERE device_id = ?", (device_id,))
                    row = cur.fetchone()
                    
                    # 2. Bestehenden Eintrag nutzen?
                    if row and not should_gen:
                        final_ua = row[0]
                        saved_link = row[1]
                        is_cached = True
                        
                        # Wenn wir keinen neuen Link eingeben, nehmen wir den gespeicherten
                        if not final_link and saved_link:
                            final_link = saved_link
                    
                    # 3. Speichern / Updaten
                    if save_to_db:
                        if should_gen or not row:
                            # Komplett neu oder Force Update
                            cur.execute("INSERT OR REPLACE INTO agents (device_id, user_agent, tracker_link) VALUES (?, ?, ?)", (device_id, final_ua, final_link))
                            conn.commit()
                        elif row and incoming_link:
                            # UA behalten, aber Link updaten
                            cur.execute("UPDATE agents SET tracker_link = ? WHERE device_id = ?", (incoming_link, device_id))
                            conn.commit()
                            final_link = incoming_link
                    
                    return final_ua, is_cached, final_link
        except:
            # Fallback bei DB Fehler
            return final_ua, False, final_link

    def _generate_random(self, p):
        if p == "android":
            return f"Mozilla/5.0 (Linux; Android 14; {random.choice(['SM-S918B','Pixel 8 Pro','2308CPXD0C'])}; de-DE) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
        return "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"

    def _construct_specific(self, p, b, m, o):
        # Saubere Konstruktion
        if p == "android":
            return f"Mozilla/5.0 (Linux; Android {o}; {m}) AppleWebKit/537.36 (KHTML, like Gecko) {b}/121.0.0.0 Mobile Safari/537.36"
        else:
            return f"Mozilla/5.0 (iPhone; CPU iPhone OS {o.replace('.', '_')} like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) {b}/Custom Mobile/15E148"

ua_manager = UserAgentManager()

# ---------------------------------------------------------
# 2. NETWORK CONFIG
# ---------------------------------------------------------
GLOBAL_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
GLOBAL_SESSION.mount('https://', adapter)

SKADN_APP_CONFIGS = {"TikTok": 8, "Snapchat": 12, "Facebook": 16, "Google": 20, "Unity": 24}

def get_skadn_value_for_app(app_name):
    for k, v in SKADN_APP_CONFIGS.items(): 
        if k.lower() in app_name.lower(): return v
    return 8

# ---------------------------------------------------------
# 3. AUTO PROXY ENGINE
# ---------------------------------------------------------
class AutoProxyEngine:
    def __init__(self):
        self.cached_proxies = []
        self.last_fetch = 0
        
    def fetch_german_proxies(self):
        # Cache für 5 Minuten
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

# ---------------------------------------------------------
# 4. LINK PARSER & URL GENERATOR (CORE LOGIC)
# ---------------------------------------------------------
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
    # --- WICHTIG: S2S ENDPOINT NUTZEN ---
    # Vorher falsch: app.adjust.com/{event_token} -> "Tracker not found"
    # Jetzt richtig: s2s.adjust.com/event mit Parameter event_token
    base = "https://s2s.adjust.com/event"
    
    params = {
        "app_token": app_token,
        "event_token": event_token, # Das Token ist jetzt ein Parameter!
        "s2s": "1"
    }
    
    if platform == "android":
        params["gps_adid"] = device_id
        params["adid"] = device_id
    else:
        params["idfa"] = device_id
        if skadn: params["skadn"] = skadn

    extracted_ip = None
    has_referrer = False

    # Dynamic Parameter Pass-Through
    if tracker_link and "adjust" in tracker_link:
        try:
            parsed = urlparse(tracker_link)
            query_params = parse_qs(parsed.query)
            
            # Diese Keys setzen wir selbst, also nicht aus dem Link überschreiben
            blocked_keys = ["gps_adid", "adid", "idfa", "app_token", "skadn", "s2s", "event_token"]
            
            for key, val_list in query_params.items():
                val = val_list[0]
                
                # Referrer Mapping
                if key == "referrer":
                    params["install_referrer"] = val
                    has_referrer = True
                    continue
                
                # IP Extraction für Spoofing
                if key in ["ip", "device_ip", "user_ip", "ip_address"]:
                    extracted_ip = val
                    params["ip_address"] = val # Offizieller Adjust Parameter
                    continue

                # Alles andere (click_id, campaign etc.) durchlassen
                if key not in blocked_keys:
                    params[key] = val
        except: pass
        
    # Time Travel (Google Play Timestamps simulieren)
    if has_referrer and platform == "android":
        now = int(time.time())
        # Klick war vor 45-120 Sekunden, Install vor 5-30 Sekunden
        params["referrer_click_timestamp_seconds"] = str(now - random.randint(45, 120))
        params["install_begin_timestamp_seconds"] = str(now - random.randint(5, 30))

    return f"{base}?{urlencode(params)}", extracted_ip

# ---------------------------------------------------------
# 5. REQUEST SENDER (PROXY LOOP)
# ---------------------------------------------------------
def send_request_auto_detect(url, platform, use_get, skadn=None, user_agent=None, spoof_ip=None, manual_proxy=None, use_auto_proxy=False):
    headers = {}
    if user_agent: headers["User-Agent"] = user_agent
    headers["Accept-Language"] = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    
    # Header Spoofing (wirkt auch ohne Proxy)
    if spoof_ip:
        headers["X-Forwarded-For"] = spoof_ip
        headers["X-Real-IP"] = spoof_ip
        headers["Client-IP"] = spoof_ip

    proxies_to_try = []

    # 1. Manueller Proxy (Prio A)
    if manual_proxy and len(manual_proxy) > 5:
        fmt = f"http://{manual_proxy}" if not manual_proxy.startswith("http") else manual_proxy
        proxies_to_try.append(fmt)
    
    # 2. Auto Proxy (Prio B)
    elif use_auto_proxy:
        raw_list = proxy_engine.fetch_german_proxies()
        random.shuffle(raw_list)
        for p in raw_list[:5]: # Max 5 Versuche
            proxies_to_try.append(f"http://{p}")
    
    # 3. Direct Connection (Fallback)
    if not proxies_to_try:
        proxies_to_try.append(None)

    last_error = ""
    attempt_log = []

    for proxy in proxies_to_try:
        current_proxies = {"http": proxy, "https": proxy} if proxy else None
        p_name = proxy if proxy else "Direct"
        
        try:
            # Adjust S2S bevorzugt POST Requests
            r = GLOBAL_SESSION.post(url, headers=headers, timeout=10, proxies=current_proxies)
            
            # Erfolg prüfen
            if "OK" in r.text or "success" in r.text.lower():
                return f"{r.text} (via {p_name})"
            
            # Auch bei Adjust-Fehler zurückgeben (z.B. "Event not found"), 
            # damit wir wissen, dass die Verbindung stand.
            return f"{r.text} (via {p_name})"
            
        except Exception as e:
            last_error = str(e)
            attempt_log.append(f"{p_name} failed")
            continue

    return f"Request Failed. Attempts: {', '.join(attempt_log)}. Last Error: {last_error}"