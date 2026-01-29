import random
import time
import json
from datetime import datetime
# Importiere DB Funktionen
try:
    from app.database import update_job, get_due_jobs
    from app.logic import execute_single_request, log_to_discord
except ImportError:
    from database import update_job, get_due_jobs
    from logic import execute_single_request, log_to_discord

def process_job_queue():
    """
    Checkt die DB. Wenn ein Job überfällig ist, wird er SOFORT ausgeführt.
    Der nächste Schritt wird dann relativ zu JETZT geplant (kein Nachholen der verlorenen Zeit).
    """
    # Holt alle Jobs, deren Zeit <= JETZT ist
    jobs = get_due_jobs()
    
    if not jobs:
        return {"status": "idle", "jobs_processed": 0}

    processed_count = 0
    
    for job in jobs:
        job_id = job["id"]
        # Lade die Liste der noch offenen Events
        events = json.loads(job["events_pending"])
        
        # Falls Liste leer (sollte eigentlich durch 'completed' status nicht passieren, aber sicher ist sicher)
        if not events:
            update_job(job_id, [], 0, "completed")
            continue

        # 1. Wir nehmen das nächste Event aus der Liste
        current_event_name = list(events.keys())[0]
        current_event_token = events[current_event_name]
        
        # 2. AUSFÜHREN (Hier und Jetzt)
        status, response = execute_single_request(
            job["app_token"], 
            current_event_token, 
            job["device_id"], 
            job["platform"]
        )
        
        # Discord Log
        log_to_discord(f"▶ RESUMED & EXECUTED", {
            "App": job["app_name"],
            "Event": current_event_name,
            "Status": status,
            "Info": "Zeitplan wurde fortgesetzt"
        }, "00ff00" if status == 200 else "ff0000")

        # 3. DAS EVENT AUS DER LISTE LÖSCHEN
        del events[current_event_name]
        
        if not events:
            # Keine Events mehr übrig -> Job fertig
            update_job(job_id, [], 0, "completed")
            log_to_discord(f"🏁 SEQUENCE FINISHED", {"App": job["app_name"]}, "0000ff")
        else:
            # 4. NÄCHSTEN TERMIN BERECHNEN (DIE LOGIK FÜR "NICHT NACHHOLEN")
            
            # Wir berechnen eine zufällige Pause (z.B. 1.5 Stunden)
            delay_hours = random.uniform(job["delay_min"], job["delay_max"])
            
            # WICHTIG: Wir addieren die Pause auf time.time() (JETZT).
            # Wäre der Server 5 Stunden aus gewesen, wird diese Zeit einfach ignoriert.
            # Der nächste Termin ist also: JETZT + PAUSE.
            next_ts = time.time() + (delay_hours * 3600)
            
            next_date_str = datetime.fromtimestamp(next_ts).strftime('%d.%m. %H:%M')
            
            # Speichern in DB
            update_job(job_id, events, next_ts, "pending")
            
            # Optional: Log wann es weitergeht
            # log_to_discord("💤 SCHEDULE UPDATE", {"Next Run": next_date_str}, "808080")

        processed_count += 1
        
    return {"status": "active", "processed": processed_count}