import sqlite3
import os
from cryptography.fernet import Fernet

DB_PATH = 'monitor.db'
KEY_PATH = 'secret.key'

def get_key():
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, 'rb') as f:
            return f.read()
    key = Fernet.generate_key()
    with open(KEY_PATH, 'wb') as f:
        f.write(key)
    return key

fernet = Fernet(get_key())

def encrypt_password(password):
    return fernet.encrypt(password.encode()).decode()

def decrypt_password(token):
    try:
        return fernet.decrypt(token.encode()).decode()
    except Exception:
        return token

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS hosts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip TEXT UNIQUE NOT NULL,
        port INTEGER DEFAULT 22,
        username TEXT NOT NULL,
        password TEXT NOT NULL,
        description TEXT DEFAULT '',
        group_name TEXT DEFAULT '默认分组',
        status TEXT DEFAULT 'offline',
        cpu_threshold INTEGER DEFAULT 80,
        mem_threshold INTEGER DEFAULT 85,
        disk_threshold INTEGER DEFAULT 90,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        cpu_usage REAL, mem_total INTEGER, mem_used INTEGER,
        mem_usage REAL, disk_total INTEGER, disk_used INTEGER,
        disk_usage REAL, net_speed_down REAL, net_speed_up REAL,
        load_avg TEXT, uptime TEXT,
        FOREIGN KEY(host_id) REFERENCES hosts(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER, alert_type TEXT,
        current_value REAL, threshold REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(host_id) REFERENCES hosts(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS status_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER, old_status TEXT, new_status TEXT,
        changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(host_id) REFERENCES hosts(id))''')
    conn.commit()
    conn.close()
