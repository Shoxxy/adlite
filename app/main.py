import os
import json
from fastapi import FastAPI, Request, Form, HTTPException, Header

try:
    from logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app
except ImportError:
    from app.logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app

app = FastAPI()

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")

def load_app_data():
    for path in ["data_android.json", "app/data_android.json"]:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    return {}

@app.get("/health")
async def health_check():
    return {"status": "online"}

# NEU: Endpunkt für die App-Liste und deren Events
@app.get("/api/get-apps")
async def get_apps(x_api_key: str = Header(None)):
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403)
    
    data = load_app_data()
    # Wir geben nur die Namen der Apps und deren Events zurück (keine Tokens!)
    config = {app_name: list(details.get('events', {}).keys()) for app_name, details in data.items()}
    return config

@app.post("/api/internal-execute")
async def internal_execute(
    app_name: str = Form(...), # Geändert: App Name kommt jetzt von Zone B
    platform: str = Form(...),
    device_id: str = Form(...),
    event_name: str = Form(...),
    x_api_key: str = Header(None)
):
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403)

    data = load_app_data()
    if app_name not in data:
        return {"filtered_message": "Fehler: App nicht gefunden."}

    app_info = data[app_name]
    event_token = app_info['events'].get(event_name)
    app_token = app_info.get('app_token')
    use_get = app_info.get('use_get_request', False)
    skadn_val = get_skadn_value_for_app(app_name) if platform == "ios" else None

    try:
        url = generate_adjust_url(event_token, app_token, device_id, platform, skadn_val)
        raw_response = send_request_auto_detect(url, platform, use_get, skadn_val)
        
        raw_lower = str(raw_response).lower()
        if "request doesn't contain device identifiers" in raw_lower:
            user_msg = "Device ID fehlerhaft."
        elif "device not found" in raw_lower:
            user_msg = "Spiel nicht installiert oder Tracking nicht akzeptiert."
        elif "app_token" in raw_lower:
            user_msg = "Erfolgreich!"
        else:
            user_msg = "Vorgang abgeschlossen."

        return {"filtered_message": user_msg}
    except Exception as e:
        return {"filtered_message": "Verarbeitungsfehler in Zone C."}