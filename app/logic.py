import time
import random
import requests
import datetime
import sqlite3
import threading
from urllib.parse import quote

# --- USER AGENT MANAGEMENT MIT DATENBANK ---
class UserAgentManager:
    def __init__(self):
        # Wir nutzen SQLite für dauerhafte Speicherung
        self.db_path = "user_agents.db"
        self._init_db()
        # Lock für Thread-Sicherheit bei Datenbank-Zugriffen
        self.lock = threading.Lock()
        
    def _init_db(self):
        """Erstellt die Tabelle, falls sie noch nicht existiert"""
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

    def get_or_create(self, device_id, platform, browser=None, model=None, os_ver=None, use_random=False):
        """
        Lädt UA aus DB oder erstellt neuen und speichert ihn.
        Returns: (user_agent_string, is_from_cache_bool)
        """
        with self.lock: # Verhindert Datenbank-Konflikte bei vielen Zugriffen
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                
                # 1. PRÜFEN: Gibt es die ID schon in der DB?
                cursor.execute("SELECT user_agent FROM agents WHERE device_id = ?", (device_id,))
                row = cursor.fetchone()
                
                if row:
                    # JA -> Zurückgeben (FIXIERT)
                    return row[0], True
                
                # 2. NEIN -> Generieren
                platform = platform.lower()
                ua = ""
                
                if use_random or (not browser and not model):
                    ua = self._generate_random(platform)
                else:
                    ua = self._construct_specific(platform, browser, model, os_ver)
                
                # 3. SPEICHERN -> In DB schreiben
                cursor.execute("INSERT INTO agents (device_id, user_agent) VALUES (?, ?)", (device_id, ua))
                conn.commit()
                
                return ua, False

    def _generate_random(self, platform):
        """Erstellt aktuelle Random UAs (IMMER DEUTSCH)"""
        if platform == "android":
            # High-End Androids
            models = ["SM-S918B", "Pixel 8 Pro", "2308CPXD0C", "SM-A546B"]
            model = random.choice(models)
            return f"Mozilla/5.0 (Linux; Android 14; {model}; de-DE) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
        else:
            # iOS 17.3
            return "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"

    def _construct_specific(self, platform, browser, model, os_ver):
        """Baut UA aus User-Eingaben mit neuesten Versionen und DE Locale"""
        
        browser = browser.lower() if browser else ("chrome" if platform == "android" else "safari")
        model = model or ("SM-S918B" if platform == "android" else "iPhone15,3") 
        os_ver = os_ver or ("14" if platform == "android" else "17.3")
        
        if platform == "android":
            base_platform = f"Linux; Android {os_ver}; {model}; de-DE"
            if "firefox" in browser:
                return f"Mozilla/5.0 ({base_platform}; rv:122.0) Gecko/122.0 Firefox/122.0"
            elif "opera" in browser:
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36 OPR/79.0.4195.76188"
            elif "edge" in browser:
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36 EdgA/120.0.2210.141"
            elif "brave" in browser:
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
            else: 
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
        else:
            os_ver_ua = os_ver.replace(".", "_")
            base_platform = f"iPhone; CPU iPhone OS {os_ver_ua} like Mac OS X"
            
            if "chrome" in browser:
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/121.0.6167.101 Mobile/15E148 Safari/604.1"
            elif "firefox" in browser:
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/122.0 Mobile/15E148 Safari/605.1.15"
            elif "opera" in browser:
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/605.1.15 (KHTML, like Gecko) OPiOS/45.0.2.0 Mobile/15E148 Safari/605.1.15"
            elif "edge" in browser:
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/120.0.2210.126 Version/17.0 Mobile/15E148 Safari/605.1.15"
            elif "brave" in browser:
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"
            else: 
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"

# Singleton Instanz
ua_manager = UserAgentManager()

# --- REQUEST LOGIC ---
GLOBAL_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
GLOBAL_SESSION.mount('https://', adapter)

SKADN_APP_CONFIGS = {
    "TikTok": 8, "Snapchat": 12, "Facebook": 16, "Google": 20, "Unity": 24
}

def get_skadn_value_for_app(app_name):
    for k, v in SKADN_APP_CONFIGS.items():
        if k.lower() in app_name.lower(): return v
    return 8

def generate_adjust_url(event_token, app_token, device_id, platform, skadn=None):
    base = "https://app.adjust.com"
    params = f"?gps_adid={device_id}&adid={device_id}" if platform == "android" else f"?idfa={device_id}"
    url = f"{base}/{event_token}{params}&app_token={app_token}"
    if platform == "ios" and skadn:
        url += f"&skadn={skadn}"
    return url

def send_request_auto_detect(url, platform, use_get, skadn=None, user_agent=None):
    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent
        headers["Accept-Language"] = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    
    try:
        if use_get:
            r = GLOBAL_SESSION.get(url, headers=headers, timeout=10)
        else:
            r = GLOBAL_SESSION.post(url, headers=headers, timeout=10)
        return r.text
    except Exception as e:
        return f"Request Error: {str(e)}"