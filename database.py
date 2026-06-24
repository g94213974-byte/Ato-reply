# database.py
import sqlite3
import os

DB_PATH = "database.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT NOT NULL,
        reply_text TEXT NOT NULL,
        match_type TEXT DEFAULT 'contains'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        keyword TEXT NOT NULL,
        reply_text TEXT NOT NULL,
        match_type TEXT DEFAULT 'exact',
        created_at INTEGER DEFAULT (strftime('%s','now'))
    )''')
    conn.commit()
    conn.close()

def get_setting(key, default=''):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def add_reply(keyword, reply_text, match_type='contains'):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO replies (keyword, reply_text, match_type) VALUES (?, ?, ?)", 
              (keyword, reply_text, match_type))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return rid

def delete_reply(rid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM replies WHERE id=?", (rid,))
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected > 0

def get_all_replies():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, keyword, reply_text, match_type FROM replies ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return [(r['id'], r['keyword'], r['reply_text'], r['match_type']) for r in rows]

def get_reply_count():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM replies")
    count = c.fetchone()[0]
    conn.close()
    return count

# === USER-SPECIFIC REPLIES ===
def add_user_reply(user_id, keyword, reply_text, match_type='exact'):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO user_replies (user_id, keyword, reply_text, match_type) VALUES (?, ?, ?, ?)",
              (user_id, keyword, reply_text, match_type))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return rid

def get_user_specific_replies(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, user_id, keyword, reply_text, match_type FROM user_replies WHERE user_id=?",
              (user_id,))
    rows = c.fetchall()
    conn.close()
    return [(r['id'], r['user_id'], r['keyword'], r['reply_text'], r['match_type']) for r in rows]

def get_all_user_replies():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, user_id, keyword, reply_text, match_type FROM user_replies ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return [(r['id'], r['user_id'], r['keyword'], r['reply_text'], r['match_type']) for r in rows]

def delete_user_reply(rid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM user_replies WHERE id=?", (rid,))
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected > 0

def get_user_reply_count():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM user_replies")
    count = c.fetchone()[0]
    conn.close()
    return count
