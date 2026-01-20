import time
import random
import requests
import datetime
from urllib.parse import quote

# --- USER AGENT MANAGEMENT ---
class UserAgentManager:
    def __init__(self):
        # Speicher: device_id -> user_agent
        self.storage = {}
        
    def get_or_create(self, device_id, platform, browser=None, model=None, os_ver=None, use_random=False):
        # 1. Existiert bereits ein UA für dieses Gerät?
        if device_id in self.storage:
            return self.storage[device_id]
        
        # 2. Generierung
        ua = ""
        platform = platform.lower()
        
        # Falls Random gewünscht oder keine spezifischen Angaben
        if use_random or (not browser and not model):
            ua = self._generate_random(platform)
        else:
            ua = self._construct_specific(platform, browser, model, os_ver)
            
        # 3. Speichern
        self.storage[device_id] = ua
        return ua

    def _generate_random(self, platform):
        """Erstellt aktuelle Random UAs (IMMER DEUTSCH)"""
        if platform == "android":
            # High-End Androids
            models = ["SM-S918B", "Pixel 8 Pro", "2308CPXD0C", "SM-A546B"]
            model = random.choice(models)
            # Android 14 ist Standard für 'Aktuell'
            return f"Mozilla/5.0 (Linux; Android 14; {model}; de-DE) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"
        else:
            # iOS 17.3
            return "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"

    def _construct_specific(self, platform, browser, model, os_ver):
        """Baut UA aus User-Eingaben mit neuesten Versionen und DE Locale"""
        
        # --- DEFAULTS & CLEANUP ---
        browser = browser.lower() if browser else ("chrome" if platform == "android" else "safari")
        # Standardmodelle falls leer
        model = model or ("SM-S918B" if platform == "android" else "iPhone15,3") 
        # OS Version Cleanup (z.B. "13" -> "13")
        os_ver = os_ver or ("14" if platform == "android" else "17.3")
        
        # --- ANDROID CONSTRUCTION ---
        if platform == "android":
            # Basis-String immer mit de-DE
            base_platform = f"Linux; Android {os_ver}; {model}; de-DE"
            
            if "firefox" in browser:
                return f"Mozilla/5.0 ({base_platform}; rv:122.0) Gecko/122.0 Firefox/122.0"
            elif "opera" in browser:
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36 OPR/79.0.4195.76188"
            elif "edge" in browser:
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36 EdgA/120.0.2210.141"
            elif "brave" in browser:
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36" # Brave tarnt sich als Chrome
            else: # Chrome (Default)
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36"

        # --- IOS CONSTRUCTION ---
        else:
            # iOS Version Formatierung (17.3 -> 17_3)
            os_ver_ua = os_ver.replace(".", "_")
            
            # Basis iPhone String
            # Hinweis: iOS UAs enthalten selten Locale direkt im Plattform-String, 
            # aber moderne Engines übernehmen das aus dem System. Wir halten es Standard-Konform.
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
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1" # Brave iOS nutzt WebKit
            else: # Safari (Default)
                return f"Mozilla/5.0 ({base_platform}) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"

# Singleton Instanz
ua_manager = UserAgentManager()

# --- REQUEST LOGIC (Unverändert, aber nötig für Imports) ---
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
        # Optional: Accept-Language Header für noch mehr Authentizität
        headers["Accept-Language"] = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    
    try:
        if use_get:
            r = GLOBAL_SESSION.get(url, headers=headers, timeout=10)
        else:
            r = GLOBAL_SESSION.post(url, headers=headers, timeout=10)
        return r.text
    except Exception as e:
        return f"Request Error: {str(e)}"