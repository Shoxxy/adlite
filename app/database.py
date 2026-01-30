import sqlite3
import json
import time
import os

# Pfad zur Datenbank (Persistent Storage wenn möglich)
DB_FILE = "jobs.db"

def init_db():
    """Erstellt die Job-Tabelle, falls sie noch nicht existiert"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT,
                    platform TEXT,
                    device_id TEXT,
                    app_token TEXT,
                    events_pending TEXT,  -- JSON Liste der noch offenen Events
                    next_execution_ts REAL, -- Wann geht es weiter? (UNIX Timestamp)
                    delay_min REAL,
                    delay_max REAL,
                    username TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
    except Exception as e:
        print(f"DATABASE INIT ERROR: {e}")

def add_job(app_name, platform, device_id, app_token, events_list, next_ts, delay_min, delay_max, username):
    """Fügt einen neuen Auftrag in die Warteschlange ein"""
    events_json = json.dumps(events_list)
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                INSERT INTO job_queue 
                (app_name, platform, device_id, app_token, events_pending, next_execution_ts, delay_min, delay_max, username)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (app_name, platform, device_id, app_token, events_json, next_ts, delay_min, delay_max, username))
        return True
    except Exception as e:
        print(f"ADD JOB ERROR: {e}")
        return False

def get_due_jobs():
    """Holt alle Jobs, deren Zeit gekommen ist"""
    now = time.time()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            # Status 'pending' UND Zeit ist erreicht oder überschritten
            cur.execute("SELECT * FROM job_queue WHERE status='pending' AND next_execution_ts <= ?", (now,))
            return cur.fetchall()
    except Exception as e:
        print(f"GET JOBS ERROR: {e}")
        return []

def update_job(job_id, new_events_list, new_next_ts, status='pending'):
    """Aktualisiert den Job nach einem ausgeführten Event"""
    events_json = json.dumps(new_events_list)
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                UPDATE job_queue 
                SET events_pending = ?, next_execution_ts = ?, status = ?
                WHERE id = ?
            """, (events_json, new_next_ts, status, job_id))
    except Exception as e:
        print(f"UPDATE JOB ERROR: {e}")