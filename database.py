def get_all_ignore_replies():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, keyword FROM ignore_replies ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return rows

def add_ignore_reply(keyword):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO ignore_replies (keyword) VALUES (?)", (keyword,))
        conn.commit()
    except:
        pass
    conn.close()

def delete_ignore_reply(rid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM ignore_replies WHERE id = ?", (rid,))
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected > 0

def is_ignored_keyword(text):
    """Check if text contains any ignored keyword"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT keyword FROM ignore_replies")
    rows = c.fetchall()
    conn.close()
    text_lower = text.lower()
    for row in rows:
        if row[0].lower() in text_lower:
            return True
    return False
