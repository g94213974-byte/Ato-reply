import sqlite3
import os
import json
import logging

logger = logging.getLogger(__name__)

DB_PATH = "bot_database.db"


def get_conn():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables"""
    conn = get_conn()
    c = conn.cursor()
    
    # Settings table
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    
    # Global replies table
    c.execute("""CREATE TABLE IF NOT EXISTS replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT NOT NULL,
        reply TEXT NOT NULL,
        match_type TEXT DEFAULT 'contains'
    )""")
    
    # User-specific replies table
    c.execute("""CREATE TABLE IF NOT EXISTS user_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        keyword TEXT NOT NULL,
        reply TEXT NOT NULL,
        match_type TEXT DEFAULT 'exact'
    )""")
    
    # Ignore keywords table (NEW)
    c.execute("""CREATE TABLE IF NOT EXISTS ignore_keywords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT NOT NULL,
        match_type TEXT DEFAULT 'contains'
    )""")
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")


# ===== SETTINGS =====

def get_setting(key, default=''):
    """Get a setting value"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row['value'] if row else default


def set_setting(key, value):
    """Set a setting value"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)""", (key, value))
    conn.commit()
    conn.close()


# ===== GLOBAL REPLIES =====

def add_reply(keyword, reply, match_type='contains'):
    """Add a global reply"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO replies (keyword, reply, match_type) VALUES (?, ?, ?)""", 
              (keyword, reply, match_type))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return rid


def delete_reply(rid):
    """Delete a global reply by ID"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM replies WHERE id=?", (rid,))
    conn.commit()
    affected = c.rowcount > 0
    conn.close()
    return affected


def get_all_replies():
    """Get all global replies"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, keyword, reply, match_type FROM replies ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return [(r['id'], r['keyword'], r['reply'], r['match_type']) for r in rows]


def get_reply_count():
    """Get count of global replies"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM replies")
    row = c.fetchone()
    conn.close()
    return row['cnt'] if row else 0


# ===== USER-SPECIFIC REPLIES =====

def add_user_reply(user_id, keyword, reply, match_type='exact'):
    """Add a user-specific reply"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO user_replies (user_id, keyword, reply, match_type) VALUES (?, ?, ?, ?)""",
              (user_id, keyword, reply, match_type))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return rid


def delete_user_reply(rid):
    """Delete a user-specific reply by ID"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM user_replies WHERE id=?", (rid,))
    conn.commit()
    affected = c.rowcount > 0
    conn.close()
    return affected


def get_user_specific_replies(user_id):
    """Get all replies specific to a user"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT id, user_id, keyword, reply, match_type FROM user_replies 
                 WHERE user_id=? ORDER BY id""", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [(r['id'], r['user_id'], r['keyword'], r['reply'], r['match_type']) for r in rows]


def get_all_user_replies():
    """Get all user-specific replies"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, user_id, keyword, reply, match_type FROM user_replies ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return [(r['id'], r['user_id'], r['keyword'], r['reply'], r['match_type']) for r in rows]


def get_user_reply_count():
    """Get count of user-specific replies"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM user_replies")
    row = c.fetchone()
    conn.close()
    return row['cnt'] if row else 0


# ===== IGNORE KEYWORDS (NEW) =====

def add_ignore_keyword(keyword, match_type='contains'):
    """
    Add a keyword that the bot will completely ignore.
    
    Args:
        keyword: The keyword to ignore
        match_type: 'exact' or 'contains'
    
    Returns:
        ID of the new ignore keyword entry
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO ignore_keywords (keyword, match_type) VALUES (?, ?)""", 
              (keyword, match_type))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    logger.info(f"Ignore keyword added: '{keyword}' ({match_type}) - ID: {rid}")
    return rid


def delete_ignore_keyword(rid):
    """
    Delete an ignore keyword by ID.
    
    Args:
        rid: The ID of the ignore keyword to delete
    
    Returns:
        True if deleted, False if not found
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM ignore_keywords WHERE id=?", (rid,))
    conn.commit()
    affected = c.rowcount > 0
    conn.close()
    if affected:
        logger.info(f"Ignore keyword deleted: ID {rid}")
    else:
        logger.warning(f"Ignore keyword not found: ID {rid}")
    return affected


def get_ignore_keywords():
    """
    Get all ignore keywords.
    
    Returns:
        List of tuples (id, keyword, match_type)
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, keyword, match_type FROM ignore_keywords ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return [(r['id'], r['keyword'], r['match_type']) for r in rows]


def get_ignore_keyword_count():
    """Get count of ignore keywords"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM ignore_keywords")
    row = c.fetchone()
    conn.close()
    return row['cnt'] if row else 0


def is_ignored(message_text):
    """
    Check if a message should be ignored.
    
    Args:
        message_text: The text of the message to check
    
    Returns:
        tuple (bool, str) - (is_ignored, matched_keyword)
    """
    if not message_text:
        return False, ""
    
    msg_lower = message_text.lower().strip()
    ignore_keywords = get_ignore_keywords()
    
    for rid, keyword, match_type in ignore_keywords:
        kw = keyword.lower().strip()
        if match_type == "exact" and msg_lower == kw:
            logger.info(f"Message ignored (exact match): '{message_text}' matched '{kw}'")
            return True, keyword
        elif match_type == "contains" and kw in msg_lower:
            logger.info(f"Message ignored (contains): '{message_text}' matched '{kw}'")
            return True, keyword
    
    return False, ""


# ===== DATABASE MAINTENANCE =====

def get_db_stats():
    """Get database statistics"""
    conn = get_conn()
    c = conn.cursor()
    
    stats = {}
    
    c.execute("SELECT COUNT(*) as cnt FROM replies")
    row = c.fetchone()
    stats['global_replies'] = row['cnt'] if row else 0
    
    c.execute("SELECT COUNT(*) as cnt FROM user_replies")
    row = c.fetchone()
    stats['user_replies'] = row['cnt'] if row else 0
    
    c.execute("SELECT COUNT(*) as cnt FROM ignore_keywords")
    row = c.fetchone()
    stats['ignore_keywords'] = row['cnt'] if row else 0
    
    c.execute("SELECT COUNT(*) as cnt FROM settings")
    row = c.fetchone()
    stats['settings'] = row['cnt'] if row else 0
    
    conn.close()
    
    # Get database file size
    try:
        stats['db_size_kb'] = round(os.path.getsize(DB_PATH) / 1024, 2)
    except:
        stats['db_size_kb'] = 0
    
    return stats


def reset_database():
    """⚠️ DANGER: Clears all data from the database (except settings)"""
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("DELETE FROM replies")
    c.execute("DELETE FROM user_replies")
    c.execute("DELETE FROM ignore_keywords")
    
    conn.commit()
    conn.close()
    logger.warning("Database reset completed! All replies and ignore keywords cleared.")
    return True


def backup_database():
    """Create a backup of the database"""
    backup_path = f"bot_database_backup_{int(time.time())}.db"
    try:
        import shutil
        shutil.copy2(DB_PATH, backup_path)
        logger.info(f"Database backed up to: {backup_path}")
        return backup_path
    except Exception as e:
        logger.error(f"Database backup failed: {e}")
        return None
