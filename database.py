import sqlite3
import os

DB_FILE = os.environ.get("DB_FILE", "userbot.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS replies
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  keyword TEXT NOT NULL,
                  reply_text TEXT NOT NULL,
                  type TEXT DEFAULT 'exact')''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY,
                  value TEXT)''')
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def add_reply(keyword, reply_text, rtype='exact'):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO replies (keyword, reply_text, type) VALUES (?, ?, ?)",
              (keyword, reply_text, rtype))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return rid

def delete_reply(rid):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM replies WHERE id=?", (rid,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_all_replies():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, keyword, reply_text, type FROM replies ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return rows

def get_reply_count():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM replies")
    count = c.fetchone()[0]
    conn.close()
    return count
