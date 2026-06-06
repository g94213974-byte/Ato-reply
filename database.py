# database.py
import sqlite3
import os

DB_PATH = "data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS replies
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  keyword TEXT NOT NULL,
                  reply TEXT NOT NULL,
                  match_type TEXT DEFAULT 'contains')''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    conn.close()

def get_setting(key, default=''):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else default

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()

def add_reply(keyword, reply, match_type='contains'):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO replies (keyword, reply, match_type) VALUES (?,?,?)", (keyword, reply, match_type))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return rid

def delete_reply(rid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM replies WHERE id=?", (rid,))
    conn.commit()
    d = c.rowcount > 0
    conn.close()
    return d

def get_all_replies():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, keyword, reply, match_type FROM replies ORDER BY id")
    r = c.fetchall()
    conn.close()
    return r

def get_reply_count():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM replies")
    r = c.fetchone()[0]
    conn.close()
    return r
