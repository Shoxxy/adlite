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
        # Wir nutzen /tmp/ für Cloud-Umgebungen
        self.db_path = "/tmp/user_agents.db"
        self.lock = threading.Lock()
        self._init_db()
        
    def _init_db(self):
        try:
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
        except Exception as e:
            print(f"DB INIT WARNING (Non-Critical): {e}")

    def get_or_create(self, device_id, platform, browser=None, model=None, os_ver=None, use_random=False, force_update=False):
        """
        Versucht UA aus DB zu laden. Bei Fehler: Generiert RAM-Only UA (Fail-Safe).
        """
        # Fallback-Generierung vorbereiten
        platform = platform.lower() if platform else "android"
        
        # Inputs bereinigen
        browser = browser if browser and browser.strip() else None
        model = model if model and model.strip() else None
        os_ver = os_ver if os_ver and os_ver.strip() else None

        # UA vorab generieren (falls DB fails)
        generated_ua = ""
        if use_random or (not browser and not model):
            generated_ua = self._generate_random(platform)
        else:
            generated_ua = self._construct_specific(platform, browser, model, os_ver)

        # VERSUCH: Datenbank Zugriff
        try:
            with self.lock:
                with sqlite3.connect(self.db_path, check_same_thread=False, timeout=5) as conn:
                    cursor = conn.cursor()
                    
                    # 1. Lesen
                    cursor.execute("SELECT user_agent FROM agents WHERE device_id = ?", (device_id,))
                    row = cursor.fetchone()
                    
                    # Wenn gefunden und kein Force-Update -> Rückgabe
                    if row and not force_update:
                        return row[0], True # True = Cached
                    
                    # 2. Schreiben (Den generierten UA speichern)
                    cursor.execute("INSERT OR REPLACE INTO agents (device_id, user_agent) VALUES (?, ?)", (device_id, generated_ua))
                    conn.commit()
                    
                    return generated_ua, False # False = Neu gespeichert
                    
        except Exception as e:
            # FALLBACK: Wenn DB crasht, geben wir den generierten UA trotzdem zurück!
            # Wir loggen den Fehler nur intern, der User merkt nichts.
            print(f"UA DB ERROR (Using Fallback): {e}")
            return generated_ua, False

    def _generate_random(self, platform):
        """Generiert High-Trust UAs"""
        if platform == "android":
            models = ["SM-S918B", "Pixel 8 Pro", "2308CPXD0C", "SM-A546B"]
            model = random.choice(models)
            return f"Mozilla/5.0 (Linux; Android 14; {model}; de-DE) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
        else:
            return "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"

    def _construct_specific(self, platform, browser, model, os_ver):
        # Defaults für leere Felder
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

# Instanz erstellen
ua_manager = UserAgentManager()

# --- REQUEST PART ---
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