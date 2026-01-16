import time
import random
import requests
import datetime
import threading
import json
import traceback
from urllib.parse import quote, urlparse, parse_qs

GLOBAL_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
GLOBAL_SESSION.mount('https://', adapter)

SKADN_APP_CONFIGS = {
    "TikTok": 8, "TikTok iOS": 8, "TikTok SKAN": 8,
    "Snapchat": 12, "Snapchat iOS": 12, "Snapchat SKAN": 12,
    "Facebook": 16, "Facebook iOS": 16, "Meta": 16,
    "Google": 20, "Google iOS": 20,
    "Unity": 24, "Unity iOS": 24,
}

def get_skadn_value_for_app(app_name):
    if app_name in SKADN_APP_CONFIGS: return SKADN_APP_CONFIGS[app_name]
    app_lower = app_name.lower()
    for k, v in SKADN_APP_CONFIGS.items():
        if k.lower() in app_lower or app_lower in k.lower(): return v
    keywords = ['skan', 'ios', 'tiktok', 'snapchat', 'facebook', 'meta', 'google', 'unity']
    if any(k in app_lower for k in keywords): return 8
    return None

def generate_adjust_url(event_token, app_token, device_id, platform="android", skadn_conv_value=None):
    now = datetime.datetime.now(datetime.timezone.utc)
    params = {
        's2s': '1', 'event_token': event_token, 'app_token': app_token,
        'created_at': now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
        'environment': 'production'
    }
    if skadn_conv_value is not None: params['skadn_conv_value'] = str(skadn_conv_value)
    
    if platform == "android":
        params.update({'gps_adid': device_id, 'os_name': 'android', 'os_version': '13', 'device_type': 'phone'})
    elif platform == "ios":
        params.update({'idfa': device_id, 'os_name': 'ios', 'os_version': '16.0', 'device_type': 'phone'})
    
    base_url = "https://s2s.adjust.com/event"
    query_string = "&".join([f"{k}={quote(str(v))}" for k, v in params.items()])
    return f"{base_url}?{query_string}"

def send_post_event(event_token, app_token, device_id, platform="android", skadn_conv_value=None):
    url = "https://app.adjust.com/event"
    curr = str(int(time.time()))
    data = {
        'app_token': app_token, 'event_token': event_token, 'environment': 'production',
        'created_at': curr, 'sent_at': curr, 'session_count': '1',
    }
    if skadn_conv_value is not None: data['skadn_conv_value'] = str(skadn_conv_value)
    
    if platform == "android":
        data.update({'gps_adid': device_id, 'device_manufacturer': 'samsung', 'device_name': 'SM-G998B', 'os_name': 'android', 'os_version': '13'})
        headers = {'User-Agent': 'Adjust/4.38.0 (Android 13; SM-G998B; Build/TP1A.220624.014)', 'Content-Type': 'application/x-www-form-urlencoded', 'X-Adjust-SDK-Version': '4.38.0', 'X-Adjust-Build': curr, 'Client-SDK': 'android4.38.0'}
    else:
        data.update({'idfa': device_id, 'device_manufacturer': 'apple', 'device_name': 'iPhone14,2', 'os_name': 'ios', 'os_version': '16.0'})
        headers = {'User-Agent': 'Adjust/4.38.0 (iOS 16.0; iPhone14,2; Build/20A362)', 'Content-Type': 'application/x-www-form-urlencoded', 'X-Adjust-SDK-Version': '4.38.0', 'X-Adjust-Build': curr, 'Client-SDK': 'ios4.38.0'}
    
    try:
        r = GLOBAL_SESSION.post(url, data=data, headers=headers, timeout=10)
        if r.status_code != 200:
            try: 
                if 'error' in r.json(): return False, f"Adjust Error: {r.json()['error']}"
            except: pass
        return r.status_code == 200, r.text.strip()
    except Exception as e: return False, f"Fehler: {e}"

def send_request_auto_detect(url, platform="android", use_get_request=False, skadn_conv_value=None):
    if use_get_request:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36'
            if platform == "android" else
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
        }
        try: return GLOBAL_SESSION.get(url, headers=headers, timeout=10).text.strip()
        except Exception as e: return f"Fehler: {e}"
    else:
        try:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            et = qs.get('event_token', [''])[0]; at = qs.get('app_token', [''])[0]
            did = qs.get('gps_adid', qs.get('idfa', [''])[0])
            succ, txt = send_post_event(et, at, did, platform, skadn_conv_value)
            return f"POST {'Success' if succ else 'Failed'}: {txt}"
        except Exception as e: return f"POST Fehler: {e}"

# =============================================================================
# 3. WORKER PROZESS (MIT VISUELLEM COUNTDOWN)
# =============================================================================

def worker_process(instance_id, config, stop_evt, skip_evt, credit_evt, initial_credit_mode, log_callback, app_data_full):
    app_name = config.get('app_name')
    platform = config.get('platform')
    device_id = config.get('device_id')
    
    try:
        app_data = app_data_full.get(app_name, {})
        if not app_data:
            log_callback(instance_id, "Error", 0, f"App '{app_name}' nicht gefunden!")
            return

        events = app_data.get('events', {})
        app_token = app_data.get('app_token', '')
        use_get = app_data.get('use_get_request', False)
        events_list = list(events.items())
        
        min_h = float(config.get('min_hours', 0.1))
        max_h = float(config.get('max_hours', 1.0))
        start_idx = config.get('current_event_index', 0)
        
        skadn = get_skadn_value_for_app(app_name) if platform == "ios" else None

        mode_info = "CREDIT ALL (2s)" if initial_credit_mode else f"RANDOM ({min_h}-{max_h}h)"
        log_callback(instance_id, "Running", start_idx, f"Starte {platform.upper()} [{mode_info}]")

        for i in range(start_idx, len(events_list)):
            # ERROR CATCHING LOOP
            try:
                if stop_evt.is_set():
                    log_callback(instance_id, "Stopped", i, "Manuell gestoppt.")
                    return

                event_name, event_token = events_list[i]
                
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                log_callback(instance_id, "Running", i, f"[{ts}] Sende '{event_name}'...")
                
                url = generate_adjust_url(event_token, app_token, device_id, platform, skadn)
                resp = send_request_auto_detect(url, platform, use_get, skadn)
                
                short_resp = (resp[:60] + '..') if len(resp) > 60 else resp
                log_callback(instance_id, "Running", i + 1, f"Resp: {short_resp}")

                if i < len(events_list) - 1:
                    is_credit = initial_credit_mode or credit_evt.is_set()
                    
                    if is_credit:
                        delay = 2
                        msg = "🚀 Credit All: Warte 2s..."
                    else:
                        delay_h = round(random.uniform(min_h, max_h), 2)
                        delay = int(delay_h * 3600)
                        msg = f"Timer: {delay_h}h ({delay}s)"

                    log_callback(instance_id, "Waiting", i + 1, msg)
                    
                    # COUNTDOWN LOOP
                    end_time = time.time() + delay
                    last_update = 0
                    
                    while time.time() < end_time:
                        if stop_evt.is_set():
                            log_callback(instance_id, "Stopped", i + 1, "Gestoppt.")
                            return
                        if not is_credit and credit_evt.is_set():
                            log_callback(instance_id, "Running", i + 1, "🚀 Credit All aktiviert!")
                            break 
                        if skip_evt.is_set():
                            log_callback(instance_id, "Running", i + 1, "⏩ SKIP.")
                            skip_evt.clear()
                            break 
                        
                        # VISUELLER UPDATE (Damit man sieht dass es läuft)
                        # Update alle 30s bei langen Timern, oder jede Sekunde bei kurzen
                        remaining = int(end_time - time.time())
                        now = time.time()
                        
                        # Nur loggen, wenn nicht im Credit Mode (da geht es eh schnell)
                        if not is_credit:
                            if (remaining > 60 and now - last_update > 30) or (remaining <= 10 and now - last_update >= 1):
                                log_callback(instance_id, "Waiting", i + 1, f"⏳ Noch {remaining}s warten...")
                                last_update = now

                        time.sleep(0.5)
            except Exception as e:
                log_callback(instance_id, "Running", i, f"⚠️ FEHLER: {e}")
                time.sleep(5)

        log_callback(instance_id, "Completed", len(events_list), "Fertig.")

    except Exception as e:
        log_callback(instance_id, "Error", 0, f"CRASH: {e}")
        traceback.print_exc()