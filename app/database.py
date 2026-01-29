import sqlite3
import json
import time

DB_FILE = "jobs.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name TEXT,
                platform TEXT,
                device_id TEXT,
                app_token TEXT,
                events_pending TEXT,
                next_execution_ts REAL,
                delay_min REAL,
                delay_max REAL,
                username TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)

def add_job(app_name, platform, device_id, app_token, events_list, next_ts, delay_min, delay_max, username):
    events_json = json.dumps(events_list)
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            INSERT INTO job_queue 
            (app_name, platform, device_id, app_token, events_pending, next_execution_ts, delay_min, delay_max, username)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (app_name, platform, device_id, app_token, events_json, next_ts, delay_min, delay_max, username))

def get_due_jobs():
    now = time.time()
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        # Holt Jobs, deren Zeit <= JETZT ist.
        # Egal ob sie vor 1 Minute oder 10 Stunden fällig waren.
        return conn.execute("SELECT * FROM job_queue WHERE status='pending' AND next_execution_ts <= ?", (now,)).fetchall()

def update_job(job_id, new_events_list, new_next_ts, status='pending'):
    events_json = json.dumps(new_events_list)
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            UPDATE job_queue 
            SET events_pending = ?, next_execution_ts = ?, status = ?
            WHERE id = ?
        """, (events_json, new_next_ts, status, job_id))