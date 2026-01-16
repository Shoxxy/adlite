from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import json
import os
import secrets

# Importiere deine vorhandene Logik
try:
    from app.logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app
except ImportError:
    from logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app

app = FastAPI()

# --- CONFIG ---
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
templates = Jinja2Templates(directory="app/templates")

# FESTGELEGTE APP
FIXED_APP_NAME = "Crypto Miner Tycoon"

# --- HELPER: DATA LOADING ---
def load_app_data():
    """Sucht und lädt die data_android.json"""
    possible_paths = ["data_android.json", "app/data_android.json", "../data_android.json"]
    path_to_use = None
    
    for path in possible_paths:
        if os.path.exists(path):
            path_to_use = path
            break
            
    if not path_to_use:
        return None

    try:
        with open(path_to_use, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        return None

# --- ROUTES ---

@app.get("/")
async def index(request: Request):
    # Zeigt direkt das Lite Interface an (kein Login Zwang für Lite, oder nach Wunsch)
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/events")
async def get_events():
    """Lädt nur die Events für die festgelegte App"""
    data = load_app_data()
    if not data or FIXED_APP_NAME not in data:
        return {"events": []}
    
    # Hole Keys (Event Namen)
    events = list(data[FIXED_APP_NAME].get('events', {}).keys())
    return {"events": events}

@app.post("/api/send")
async def send_event(
    platform: str = Form(...),
    device_id: str = Form(...),
    event_name: str = Form(...)
):
    """Sendet das Event für die festgelegte App"""
    data = load_app_data()
    if not data or FIXED_APP_NAME not in data:
        return {"success": False, "log": "App Data not found"}

    app_info = data[FIXED_APP_NAME]
    
    # Token holen
    event_token = app_info['events'].get(event_name)
    if not event_token:
        return {"success": False, "log": "Event Token not found"}

    app_token = app_info.get('app_token')
    use_get = app_info.get('use_get_request', False)

    # iOS SKAdNetwork Logik
    skadn_val = None
    if platform == "ios":
        skadn_val = get_skadn_value_for_app(FIXED_APP_NAME)

    try:
        # URL Generieren (Deine Logik aus logic.py)
        url = generate_adjust_url(
            event_token=event_token,
            app_token=app_token,
            device_id=device_id,
            platform=platform,
            skadn_conv_value=skadn_val
        )

        # Request senden (Deine Logik aus logic.py)
        response_text = send_request_auto_detect(
            url=url,
            platform=platform,
            use_get_request=use_get,
            skadn_conv_value=skadn_val
        )

        return {
            "success": True, 
            "log": f"✓ {FIXED_APP_NAME} | {event_name}: {response_text}"
        }

    except Exception as e:
        return {"success": False, "log": f"Error: {str(e)}"}