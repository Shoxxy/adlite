from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import json
import os
import secrets

app = FastAPI()

# ============================================================================
# SECURITY & CONFIGURATION
# ============================================================================

secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    secret_key = secrets.token_hex(32)
    print("⚠️  WARNING: Using generated SECRET_KEY")

app.add_middleware(SessionMiddleware, secret_key=secret_key)

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin")

templates = Jinja2Templates(directory="app/templates")

# Try multiple possible paths for data_android.json
def find_data_file():
    """Find data_android.json in various possible locations"""
    possible_paths = [
        "data_android.json",           # Root directory
        "../data_android.json",        # Parent directory (if running from app/)
        "app/data_android.json",       # Inside app folder
        "./data_android.json",         # Current directory
    ]

    for path in possible_paths:
        if os.path.exists(path):
            abs_path = os.path.abspath(path)
            print(f"✓ Found data_android.json at: {abs_path}")
            return path

    print(f"❌ data_android.json NOT FOUND in any of these locations:")
    for path in possible_paths:
        abs_path = os.path.abspath(path)
        print(f"   ✗ {abs_path}")

    print(f"   Current directory: {os.getcwd()}")
    print(f"   Files here: {os.listdir('.')}")

    return None

APP_DATA_FILE = find_data_file()

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def check_auth(request: Request) -> bool:
    """Check if user is authenticated"""
    return request.session.get("authenticated", False)


def load_json_disk(path: str) -> dict:
    """Load JSON file with error handling"""
    if not path:
        print("❌ No path provided to load_json_disk")
        return {}

    if not os.path.exists(path):
        print(f"❌ File does not exist: {path}")
        print(f"   Absolute path: {os.path.abspath(path)}")
        return {}

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            print(f"✓ Successfully loaded {path}: {len(data)} apps")

            # Show first 3 app names as verification
            if data:
                sample_apps = list(data.keys())[:3]
                print(f"   Sample apps: {', '.join(sample_apps)}")

            return data
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode error in {path}: {e}")
        print(f"   Line {e.lineno}, Column {e.colno}")
        return {}
    except Exception as e:
        print(f"❌ Error loading {path}: {type(e).__name__}: {e}")
        import traceback
        print(traceback.format_exc())
        return {}


# ============================================================================
# ROUTES
# ============================================================================

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": None
    })


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["authenticated"] = True
        return RedirectResponse("/", status_code=303)
    else:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid credentials"
        })


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/")
async def index(request: Request):
    if not check_auth(request):
        return RedirectResponse("/login")
    return RedirectResponse("/manual")


@app.get("/manual")
async def manual_page(request: Request):
    if not check_auth(request):
        return RedirectResponse("/login")
    return templates.TemplateResponse("manual.html", {"request": request})


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/api/manual/apps")
async def get_apps(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)

    if not APP_DATA_FILE:
        print("❌ APP_DATA_FILE is None - data file not found at startup")
        return {"apps": []}

    app_data = load_json_disk(APP_DATA_FILE)

    if not app_data:
        print(f"⚠️  No data loaded from {APP_DATA_FILE}")
        return {"apps": []}

    apps_sorted = sorted(list(app_data.keys()))
    print(f"✓ Returning {len(apps_sorted)} apps")

    return {"apps": apps_sorted}


@app.get("/api/manual/events/{app_name}")
async def get_events(request: Request, app_name: str):
    if not check_auth(request):
        raise HTTPException(status_code=401)

    if not APP_DATA_FILE:
        return {"events": []}

    app_data = load_json_disk(APP_DATA_FILE)

    if app_name not in app_data:
        print(f"⚠️  App '{app_name}' not found")
        return {"events": []}

    events = list(app_data[app_name].get('events', {}).keys())
    print(f"✓ App '{app_name}': {len(events)} events")

    return {"events": events}


@app.post("/api/manual/send")
async def send_events(
    request: Request,
    mode: str = Form(...),
    platform: str = Form(...),
    device_id: str = Form(...),
    app_name: str = Form(...),
    event_name: str = Form(None)
):
    if not check_auth(request):
        raise HTTPException(status_code=401)

    if not APP_DATA_FILE:
        return {"success": False, "log": "Data file not found"}

    # Import logic
    try:
        from app.logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app
    except ImportError:
        try:
            from logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app
        except ImportError as e:
            print(f"❌ Cannot import logic: {e}")
            return {"success": False, "log": "Server configuration error - logic module not found"}

    app_data = load_json_disk(APP_DATA_FILE)

    if not app_data:
        return {"success": False, "log": "Could not load app data"}

    if app_name not in app_data:
        return {"success": False, "log": f"App '{app_name}' not found"}

    app_info = app_data[app_name]
    logs = []

    try:
        # WICHTIG: use_get_request aus der Konfiguration holen
        use_get_request = app_info.get('use_get_request', False)
        
        if mode == "single":
            if not event_name:
                return {"success": False, "log": "Event name required"}

            event_token = app_info['events'].get(event_name)
            if not event_token:
                return {"success": False, "log": f"Event '{event_name}' not found"}

            skadn_val = get_skadn_value_for_app(app_name) if platform == "ios" else None
            url = generate_adjust_url(
                event_token=event_token,
                app_token=app_info['app_token'],
                device_id=device_id,
                platform=platform,
                skadn_conv_value=skadn_val
            )

            # WICHTIG: Alle Parameter an send_request_auto_detect übergeben
            response = send_request_auto_detect(
                url=url,
                platform=platform,
                use_get_request=use_get_request,
                skadn_conv_value=skadn_val
            )
            
            logs.append(f"✓ {event_name}: {response}")

        elif mode == "all":
            for evt_name, evt_token in app_info['events'].items():
                skadn_val = get_skadn_value_for_app(app_name) if platform == "ios" else None
                url = generate_adjust_url(
                    event_token=evt_token,
                    app_token=app_info['app_token'],
                    device_id=device_id,
                    platform=platform,
                    skadn_conv_value=skadn_val
                )
                
                # WICHTIG: Alle Parameter an send_request_auto_detect übergeben
                response = send_request_auto_detect(
                    url=url,
                    platform=platform,
                    use_get_request=use_get_request,
                    skadn_conv_value=skadn_val
                )
                logs.append(f"✓ {evt_name}: {response}")

        return {"success": True, "logs": logs}

    except Exception as e:
        import traceback
        print(f"❌ Error: {e}")
        print(traceback.format_exc())
        return {"success": False, "log": str(e)}


# ============================================================================
# STARTUP
# ============================================================================

@app.on_event("startup")
async def startup_event():
    print()
    print("=" * 80)
    print("S2S EVENT SENDER - STARTUP")
    print("=" * 80)
    print(f"Working directory: {os.getcwd()}")
    print(f"Python path: {os.path.dirname(__file__)}")
    print()

    if APP_DATA_FILE:
        print(f"✓ Data file located: {APP_DATA_FILE}")
        print(f"  Absolute path: {os.path.abspath(APP_DATA_FILE)}")

        # Test load
        test_data = load_json_disk(APP_DATA_FILE)
        if test_data:
            print(f"✓ Data file is valid and readable")
        else:
            print(f"⚠️  WARNING: Data file found but could not be loaded")
    else:
        print("❌ DATA FILE NOT FOUND!")
        print()
        print("TROUBLESHOOTING:")
        print("1. Check that data_android.json exists")
        print("2. Check file permissions (readable)")
        print("3. Run server from correct directory:")
        print("   → If main.py is in app/, run from parent directory")
        print("   → Command: uvicorn app.main:app")
        print()
        print(f"Current directory contents:")
        for item in os.listdir('.'):
            print(f"   - {item}")

    print()
    print(f"Admin: {ADMIN_USER} / {ADMIN_PASS}")
    print("=" * 80)
    print()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)