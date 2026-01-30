import sqlite3
import json
import time
import os

DB_FILE = "jobs.db"

def init_db():
    try:
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
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
    except Exception as e:
        print(f"DATABASE INIT ERROR: {e}")

def add_job(app_name, platform, device_id, app_token, events_list, next_ts, delay_min, delay_max, username):
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
    now = time.time()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM job_queue WHERE status='pending' AND next_execution_ts <= ?", (now,))
            return cur.fetchall()
    except Exception as e:
        print(f"GET JOBS ERROR: {e}")
        return []

def update_job(job_id, new_events_list, new_next_ts, status='pending'):
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