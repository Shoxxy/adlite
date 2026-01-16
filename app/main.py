from fastapi import FastAPI, Request, Form, HTTPException, Header
import json
import os

# Import der Logik aus deiner logic.py
try:
    from app.logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app
except ImportError:
    from logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app

app = FastAPI()

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "DeinGeheimerKey")
FIXED_APP_NAME = "Crypto Miner Tycoon"

def load_app_data():
    path = "data_android.json"
    if not os.path.exists(path): return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

@app.post("/api/internal-execute")
async def internal_execute(
    platform: str = Form(...),
    device_id: str = Form(...),
    event_name: str = Form(...),
    x_api_key: str = Header(None)
):
    # 1. Security Check
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403)

    # 2. Daten laden
    data = load_app_data()
    app_info = data[FIXED_APP_NAME]
    event_token = app_info['events'].get(event_name)
    app_token = app_info.get('app_token')
    use_get = app_info.get('use_get_request', False)
    
    try:
        # 3. Adjust Request ausführen
        url = generate_adjust_url(event_token, app_token, device_id, platform)
        raw_response = send_request_auto_detect(url, platform, use_get)
        raw_lower = raw_response.lower()

        # 4. FILTERUNG direkt in Zone C
        if "request doesn't contain device identifiers" in raw_lower:
            user_msg = "Device ID fehlerhaft."
        elif "device not found" in raw_lower:
            user_msg = "Spiel nicht installiert oder nach Installation noch nicht gestartet (Tracking akzeptiert?)."
        elif "app_token" in raw_lower:
            user_msg = "Erfolgreich!"
        else:
            user_msg = "Vorgang abgeschlossen."

        return {"filtered_message": user_msg}

    except Exception as e:
        return {"filtered_message": "Systemfehler in Zone C."}