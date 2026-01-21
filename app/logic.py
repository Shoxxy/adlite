import time
import random
import requests
import datetime
import sqlite3
import threading
import os
import traceback

class UserAgentManager:
    def __init__(self):
        self.use_memory_fallback = False
        self.memory_storage = {} # Fallback falls DB crasht
        self.lock = threading.Lock()
        
        # Versuche DB zu initialisieren
        self.db_path = "/tmp/user_agents.db"
        if os.name == 'nt': self.db_path = "user_agents.db"
        
        try:
            self._init_db()
        except Exception as e:
            print(f"CRITICAL DB INIT ERROR: {e} -> Switching to RAM Mode")
            self.use_memory_fallback = True
        
    def _init_db(self):
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS agents (
                    device_id TEXT PRIMARY KEY,
                    user_agent TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

    def get_or_create(self, device_id, platform, browser=None, model=None, os_ver=None, use_random=False, force_update=False):
        # 1. Inputs vorbereiten
        platform = platform.lower() if platform else "android"
        browser = browser if browser and browser.strip() else None
        model = model if model and model.strip() else None
        os_ver = os_ver if os_ver and os_ver.strip() else None

        # 2. Ist es ein manueller Override?
        is_manual = (browser is not None or model is not None or os_ver is not None)
        should_gen_new = is_manual or force_update or use_random

        # 3. UA Generieren
        new_ua = ""
        if use_random or (not browser and not model):
            new_ua = self._generate_random(platform)
        else:
            new_ua = self._construct_specific(platform, browser, model, os_ver)

        # 4. Speichern / Laden (Fail-Safe Logik)
        if self.use_memory_fallback:
            return self._handle_memory_storage(device_id, new_ua, should_gen_new)
        else:
            return self._handle_db_storage(device_id, new_ua, should_gen_new)

    def _handle_memory_storage(self, device_id, new_ua, should_gen_new):
        """Fallback Methode ohne Datenbank"""
        if device_id in self.memory_storage and not should_gen_new:
            return self.memory_storage[device_id], True
        
        self.memory_storage[device_id] = new_ua
        return new_ua, False

    def _handle_db_storage(self, device_id, new_ua, should_gen_new):
        """Normale Datenbank Methode"""
        try:
            with self.lock:
                with sqlite3.connect(self.db_path, check_same_thread=False, timeout=5) as conn:
                    cursor = conn.cursor()
                    
                    if not should_gen_new:
                        cursor.execute("SELECT user_agent FROM agents WHERE device_id = ?", (device_id,))
                        row = cursor.fetchone()
                        if row: return row[0], True
                    
                    cursor.execute("INSERT OR REPLACE INTO agents (device_id, user_agent) VALUES (?, ?)", (device_id, new_ua))
                    conn.commit()
                    return new_ua, False
        except Exception as e:
            print(f"DB WRITE ERROR: {e} -> Using RAM for this request")
            return new_ua, False

    def _generate_random(self, platform):
        if platform == "android":
            models = ["SM-S918B", "Pixel 8 Pro", "2308CPXD0C", "SM-A546B"]
            model = random.choice(models)
            return f"Mozilla/5.0 (Linux; Android 14; {model}; de-DE) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
        else:
            return "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"

    def _construct_specific(self, platform, browser, model, os_ver):
        # Basis Defaults
        browser = browser.lower() if browser else ("chrome" if platform == "android" else "safari")
        model = model or ("SM-S918B" if platform == "android" else "iPhone15,3") 
        os_ver = os_ver or ("14" if platform == "android" else "17.3")
        
        if platform == "android":
            base = f"Linux; Android {os_ver}; {model}; de-DE"
            if "firefox" in browser: return f"Mozilla/5.0 ({base}; rv:122.0) Gecko/122.0 Firefox/122.0"
            elif "opera" in browser: return f"Mozilla/5.0 ({base}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36 OPR/79.0.4195.76188"
            elif "edge" in browser: return f"Mozilla/5.0 ({base}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36 EdgA/120.0.2210.141"
            else: return f"Mozilla/5.0 ({base}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
        else:
            os_ua = os_ver.replace(".", "_")
            base = f"iPhone; CPU iPhone OS {os_ua} like Mac OS X"
            if "chrome" in browser: return f"Mozilla/5.0 ({base}) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/121.0.6167.101 Mobile/15E148 Safari/604.1"
            elif "firefox" in browser: return f"Mozilla/5.0 ({base}) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/122.0 Mobile/15E148 Safari/605.1.15"
            else: return f"Mozilla/5.0 ({base}) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"

ua_manager = UserAgentManager()

# --- REQUEST LOGIC ---
GLOBAL_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
GLOBAL_SESSION.mount('https://', adapter)

SKADN_APP_CONFIGS = {"TikTok": 8, "Snapchat": 12, "Facebook": 16, "Google": 20, "Unity": 24}

def get_skadn_value_for_app(app_name):
    for k, v in SKADN_APP_CONFIGS.items():
        if k.lower() in app_name.lower(): return v
    return 8

def generate_adjust_url(event_token, app_token, device_id, platform, skadn=None):
    base = "https://app.adjust.com"
    params = f"?gps_adid={device_id}&adid={device_id}" if platform == "android" else f"?idfa={device_id}"
    url = f"{base}/{event_token}{params}&app_token={app_token}"
    if platform == "ios" and skadn: url += f"&skadn={skadn}"
    return url

def send_request_auto_detect(url, platform, use_get, skadn=None, user_agent=None):
    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent
        headers["Accept-Language"] = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    try:
        if use_get: r = GLOBAL_SESSION.get(url, headers=headers, timeout=10)
        else: r = GLOBAL_SESSION.post(url, headers=headers, timeout=10)
        return r.text
    except Exception as e: return f"Request Error: {str(e)}"