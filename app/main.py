import os
import json
from fastapi import FastAPI, Request, Form, HTTPException, Header
from fastapi.responses import JSONResponse

# Import der Logik aus deiner logic.py
try:
    from logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app
except ImportError:
    # Falls auf Render eine andere Struktur vorliegt
    from app.logic import generate_adjust_url, send_request_auto_detect, get_skadn_value_for_app

app = FastAPI(title="Zone C - Private Adjust Worker")

# --- KONFIGURATION ---
# Dieser Key muss in Render für Zone B und Zone C identisch gesetzt sein!
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "StandardKey_Bitte_Aendern")
FIXED_APP_NAME = "Crypto Miner Tycoon"

def load_app_data():
    """Lädt die Konfiguration aus der data_android.json"""
    # Prüft verschiedene mögliche Pfade
    for path in ["data_android.json", "app/data_android.json"]:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    return None

# --- ROUTES ---

@app.get("/health")
async def health_check():
    """
    WICHTIG: Dieser Pfad sagt Zone B, dass der Server wach ist.
    Aufruf via: https://adlite-1.onrender.com/health
    """
    return {"status": "Zone C is online", "app": FIXED_APP_NAME}

@app.get("/")
async def root():
    """Fallback für die Haupt-URL"""
    return {"message": "Zone C API Service running. Access via Zone B UI."}

@app.post("/api/internal-execute")
async def internal_execute(
    platform: str = Form(...),
    device_id: str = Form(...),
    event_name: str = Form(...),
    x_api_key: str = Header(None) # Erwartet den Key im Header
):
    """
    Dieser Endpunkt wird von Zone B aufgerufen.
    """
    
    # 1. Sicherheits-Check: API Key Vergleich
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")

    # 2. Daten für Adjust laden
    data = load_app_data()
    if not data or FIXED_APP_NAME not in data:
        return {"filtered_message": "Fehler: App-Konfiguration in Zone C fehlt."}

    app_info = data[FIXED_APP_NAME]
    event_token = app_info['events'].get(event_name)
    
    if not event_token:
        return {"filtered_message": "Fehler: Event-Token nicht gefunden."}

    app_token = app_info.get('app_token')
    use_get = app_info.get('use_get_request', False)
    # SKADN nur für iOS
    skadn_val = get_skadn_value_for_app(FIXED_APP_NAME) if platform == "ios" else None

    # 3. Request an Adjust ausführen
    try:
        # Generiere den geheimen Link (nur intern sichtbar)
        url = generate_adjust_url(event_token, app_token, device_id, platform, skadn_val)
        
        # Sende den Request (Logik aus logic.py)
        raw_response = send_request_auto_detect(url, platform, use_get, skadn_val)
        
        # 4. FILTERUNG: Die Antwort von Adjust in deine Vorgaben umwandeln
        raw_lower = str(raw_response).lower()

        if "request doesn't contain device identifiers" in raw_lower:
            user_msg = "Device ID fehlerhaft."
        elif "device not found" in raw_lower:
            user_msg = "Spiel nicht installiert oder nach Installation noch nicht gestartet (Tracking akzeptiert?)."
        elif "app_token" in raw_lower:
            user_msg = "Erfolgreich!"
        else:
            # Fallback, falls Adjust etwas anderes antwortet
            user_msg = f"Vorgang abgeschlossen."

        return {"filtered_message": user_msg}

    except Exception as e:
        print(f"Crash in Zone C: {e}")
        return {"filtered_message": "Interner Verarbeitungsfehler in Zone C."}

if __name__ == "__main__":
    import uvicorn
    # Lokal zum Testen, Render nutzt den Start Command
    uvicorn.run(app, host="0.0.0.0", port=10000)