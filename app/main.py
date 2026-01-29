import os
import json
import requests
import time
from datetime import datetime
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

# --- CONFIG ---
LOG_FILE = "security_activity.log"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
ZONE_C_URL = str(os.environ.get("ZONE_C_URL", "")).strip().rstrip("/")
INTERNAL_API_KEY = str(os.environ.get("INTERNAL_API_KEY", "")).strip()

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", "safe-key-999"), max_age=7200)
templates = Jinja2Templates(directory="templates")

# --- FIX FÜR DISCORD LOGS ---
def send_debug_log(title, details, is_alert=False):
    if not DISCORD_WEBHOOK: return
    color = 15548997 if is_alert else 1752220
    fields = [{"name": k, "value": str(v), "inline": True} for k, v in details.items()]
    payload = {
        "embeds": [{
            "title": f"🛠 {title}",
            "color": color,
            "fields": fields,
            "footer": {"text": f"Zeit: {datetime.now().strftime('%H:%M:%S')}"}
        }]
    }
    try:
        # User-Agent hilft gegen Discord-Blocks
        requests.post(DISCORD_WEBHOOK, json=payload, headers={"User-Agent": "SuStoolz-Bot"}, timeout=5)
    except: pass

# --- HEALTH CHECK (WICHTIG ZUM TESTEN) ---
@app.get("/set/health")
async def health_check(request: Request):
    if not request.session.get("is_admin"):
        return JSONResponse({"status": "unauthorized"}, status_code=401)
    
    # Wir testen ZWEI mögliche Pfade in Zone C
    test_paths = ["/api/get-apps", "/get-apps"]
    results = {}
    
    for path in test_paths:
        url = f"{ZONE_C_URL}{path}"
        try:
            r = requests.get(url, headers={"x-api-key": INTERNAL_API_KEY}, timeout=5)
            results[path] = {"status": r.status_code, "response": r.text[:50]}
        except Exception as e:
            results[path] = {"error": str(e)}
            
    return JSONResponse({"target_base": ZONE_C_URL, "checks": results})

# --- USER DASHBOARD ---
@app.get("/")
async def index(request: Request):
    if not request.session.get("user"):
        return templates.TemplateResponse("login.html", {"request": request})
    
    app_config = {}
    # Versuche den Standard-Pfad
    target_url = f"{ZONE_C_URL}/api/get-apps"
    
    try:
        resp = requests.get(target_url, headers={"x-api-key": INTERNAL_API_KEY}, timeout=10)
        if resp.status_code == 200:
            app_config = resp.json()
        else:
            # Wenn 404, schicke Details an Discord
            send_debug_log("ZONE C PATH ERROR", {
                "URL": target_url,
                "Status": resp.status_code,
                "Response": resp.text[:100]
            }, is_alert=True)
    except Exception as e:
        send_debug_log("DASHBOARD CONNECT FAIL", {"Error": str(e)}, is_alert=True)

    return templates.TemplateResponse("index.html", {"request": request, "app_config": app_config})

# --- AUTH & ADMIN ---
@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    users = json.loads(os.environ.get("USERS_JSON", '{"admin":"gold2026"}'))
    if username in users and users[username] == password:
        request.session["user"] = username
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Login falsch"})

@app.get("/set")
async def admin_panel(request: Request):
    if not request.session.get("is_admin"):
        return templates.TemplateResponse("admin_login.html", {"request": request})
    # Logs laden
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f: logs = f.readlines()[-100:]
    return templates.TemplateResponse("admin_dashboard.html", {"request": request, "logs": reversed(logs)})

@app.post("/set/login")
async def admin_login(request: Request, user: str = Form(...), pw: str = Form(...)):
    if user == os.environ.get("ADMIN_USER") and pw == os.environ.get("ADMIN_PASS"):
        request.session["is_admin"] = True
        return RedirectResponse(url="/set", status_code=303)
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": "Admin-Zutritt verweigert"})

@app.get("/set/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/set")