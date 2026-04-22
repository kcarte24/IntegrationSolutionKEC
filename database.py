import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_db_connection():
    conn = sqlite3.connect("messages.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_system TEXT,
            target_system TEXT,
            raw_data TEXT,
            transformed_data TEXT,
            status TEXT,
            failure_reason TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            user_created INTEGER DEFAULT 0
        )''')

    conn.commit()
    conn.close()