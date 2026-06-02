import sqlite3
from config import DB_FILE

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT NOT NULL,
        reply_text TEXT NOT NULL,
        reply_type TEXT NOT NULL DEFAULT 'exact',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')
    
    defaults = {
        'welcome_enabled': '1',
        'welcome_message': '👋 Welcome! আমি একটি অটো রিপ্লাই বট। কিভাবে সাহায্য করতে পারি?',
        'welcome_photo': '',
        'block_photo_enabled': '1',
        'antispam_enabled': '1',
        'typing_enabled': '1',
        'typing_duration': '300',
        # ===== নতুন ডিফল্ট রিপ্লাই সেটিংস =====
        'default_reply_enabled': '1',
        'default_reply_text': '🤖 আমি এখনো আপনার প্রশ্ন বুঝতে পারিনি। দয়া করে সঠিকভাবে লিখুন অথবা আমাদের মেনু দেখুন।',
    }
    
    for key, value in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    
    conn.commit()
    conn.close()

def get_setting(key, default=''):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def add_reply(keyword, reply_text, reply_type):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO replies (keyword, reply_text, reply_type) VALUES (?, ?, ?)",
              (keyword, reply_text, reply_type))
    conn.commit()
    reply_id = c.lastrowid
    conn.close()
    return reply_id

def delete_reply(reply_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM replies WHERE id = ?", (reply_id,))
    conn.commit()
    conn.close()
    return c.rowcount > 0

def get_all_replies():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, keyword, reply_text, reply_type FROM replies ORDER BY id")
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
