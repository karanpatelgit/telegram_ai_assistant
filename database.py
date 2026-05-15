
Copy

"""
database.py — Persistent SQLite database
=========================================
Uses a VOLUME-mounted path so data survives container restarts/redeploys.
 
Docker: mount  -v /your/host/path:/data
Railway/Render: add a persistent disk mounted at /data
 
Falls back to /app/data if /data is not available.
"""
 
import os
import sqlite3
import logging
from datetime import datetime
 
logger = logging.getLogger(__name__)
 
# ── Persistent path ────────────────────────────────────────────────
# Priority: /data (mounted volume) → /app/data → ./data
def _get_db_path():
    for base in ["/data", "/app/data", "./data"]:
        try:
            os.makedirs(base, exist_ok=True)
            test = os.path.join(base, ".write_test")
            with open(test, "w") as f:
                f.write("ok")
            os.remove(test)
            path = os.path.join(base, "bot.db")
            logger.info(f"✅ Database path: {path}")
            return path
        except Exception:
            continue
    # Last resort — same directory as script
    return "bot.db"
 
DB_PATH = _get_db_path()
 
 
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
 
 
def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    c = conn.cursor()
 
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            date     TEXT NOT NULL,
            task     TEXT NOT NULL,
            time     TEXT DEFAULT '09:00',
            status   TEXT DEFAULT 'Pending',
            category TEXT DEFAULT 'general',
            created  TEXT DEFAULT (datetime('now'))
        )
    """)
 
    c.execute("""
        CREATE TABLE IF NOT EXISTS exams (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            subject  TEXT NOT NULL,
            date     TEXT NOT NULL,
            time     TEXT DEFAULT '09:00',
            notes    TEXT DEFAULT '',
            created  TEXT DEFAULT (datetime('now'))
        )
    """)
    # Add notes column if upgrading from old schema (safe to run every time)
    try:
        c.execute("ALTER TABLE exams ADD COLUMN notes TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass  # Column already exists
 
    c.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            note    TEXT NOT NULL,
            tags    TEXT DEFAULT '',
            created TEXT DEFAULT (datetime('now'))
        )
    """)
 
    c.execute("""
        CREATE TABLE IF NOT EXISTS revisions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            topic      TEXT NOT NULL,
            subject    TEXT DEFAULT 'General',
            next_date  TEXT NOT NULL,
            interval   INTEGER DEFAULT 1,
            created    TEXT DEFAULT (datetime('now'))
        )
    """)
 
    c.execute("""
        CREATE TABLE IF NOT EXISTS content (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            type     TEXT,
            content  TEXT,
            platform TEXT,
            created  TEXT DEFAULT (datetime('now'))
        )
    """)
 
    c.execute("""
        CREATE TABLE IF NOT EXISTS inbox (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            text      TEXT NOT NULL,
            created   TEXT DEFAULT (datetime('now')),
            processed INTEGER DEFAULT 0
        )
    """)
 
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            key     TEXT PRIMARY KEY,
            value   TEXT NOT NULL,
            updated TEXT DEFAULT (datetime('now'))
        )
    """)
 
    c.execute("""
        CREATE TABLE IF NOT EXISTS analytics (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            event   TEXT NOT NULL,
            created TEXT DEFAULT (datetime('now'))
        )
    """)
 
    conn.commit()
    conn.close()
    logger.info("✅ Database initialized")
 
 
# ── Tasks ──────────────────────────────────────────────────────────
 
def add_task(date, task, time="09:00", category="general"):
    conn = get_conn()
    conn.execute(
        "INSERT INTO tasks (date, task, time, category) VALUES (?,?,?,?)",
        (date, task, time, category)
    )
    conn.commit()
    conn.close()
 
def get_tasks(date=None):
    conn = get_conn()
    if date:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE date=? ORDER BY time", (date,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM tasks ORDER BY date, time").fetchall()
    conn.close()
    return [tuple(r) for r in rows]
 
def complete_task(task_id):
    conn = get_conn()
    conn.execute("UPDATE tasks SET status='Done' WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
 
def delete_task(task_id):
    conn = get_conn()
    conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
 
 
# ── Exams ──────────────────────────────────────────────────────────
 
def add_exam(subject, date, time="09:00"):
    conn = get_conn()
    conn.execute(
        "INSERT INTO exams (subject, date, time) VALUES (?,?,?)",
        (subject, date, time)
    )
    conn.commit()
    conn.close()
 
def get_exams():
    conn = get_conn()
    # Returns: (id, subject, date, time, notes, created)
    rows = conn.execute(
        "SELECT id, subject, date, time, COALESCE(notes,'') FROM exams ORDER BY date"
    ).fetchall()
    conn.close()
    return [tuple(r) for r in rows]
 
def delete_exam(exam_id):
    conn = get_conn()
    conn.execute("DELETE FROM exams WHERE id=?", (exam_id,))
    conn.commit()
    conn.close()
 
 
# ── Notes ──────────────────────────────────────────────────────────
 
def add_note(note, tags=""):
    conn = get_conn()
    conn.execute("INSERT INTO notes (note, tags) VALUES (?,?)", (note, tags))
    conn.commit()
    conn.close()
 
def get_notes():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM notes ORDER BY created DESC").fetchall()
    conn.close()
    return [tuple(r) for r in rows]
 
def search_notes(query):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM notes WHERE note LIKE ? OR tags LIKE ?",
        (f"%{query}%", f"%{query}%")
    ).fetchall()
    conn.close()
    return [tuple(r) for r in rows]
 
def delete_note(note_id):
    conn = get_conn()
    conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
    conn.commit()
    conn.close()
 
 
# ── Revisions ──────────────────────────────────────────────────────
 
def add_revision(topic, subject="General", days=3):
    from datetime import timedelta
    next_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_conn()
    conn.execute(
        "INSERT INTO revisions (topic, subject, next_date, interval) VALUES (?,?,?,?)",
        (topic, subject, next_date, days)
    )
    conn.commit()
    conn.close()
 
def get_all_revisions():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM revisions ORDER BY next_date").fetchall()
    conn.close()
    return [tuple(r) for r in rows]
 
def get_due_revisions(date: str):
    """Return revisions whose next_date is on or before the given date."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, topic, subject, next_date, interval FROM revisions WHERE next_date <= ?",
        (date,)
    ).fetchall()
    conn.close()
    return [tuple(r) for r in rows]
 
def reschedule_revision(rev_id: int, new_interval: int):
    """Push next_date forward by new_interval days from today."""
    from datetime import timedelta
    next_date = (datetime.now() + timedelta(days=new_interval)).strftime("%Y-%m-%d")
    conn = get_conn()
    conn.execute(
        "UPDATE revisions SET next_date=?, interval=? WHERE id=?",
        (next_date, new_interval, rev_id)
    )
    conn.commit()
    conn.close()
 
 
# ── Content ────────────────────────────────────────────────────────
 
def add_content(ctype, content, platform=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO content (type, content, platform) VALUES (?,?,?)",
        (ctype, content, platform)
    )
    conn.commit()
    conn.close()
 
def get_content():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM content ORDER BY created DESC").fetchall()
    conn.close()
    return [tuple(r) for r in rows]
 
 
# ── Inbox ──────────────────────────────────────────────────────────
 
def add_inbox(text):
    conn = get_conn()
    conn.execute("INSERT INTO inbox (text) VALUES (?)", (text,))
    conn.commit()
    conn.close()
 
def get_inbox(processed=0):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM inbox WHERE processed=? ORDER BY created DESC",
        (processed,)
    ).fetchall()
    conn.close()
    return [tuple(r) for r in rows]
 
def process_inbox_item(inbox_id):
    conn = get_conn()
    conn.execute("UPDATE inbox SET processed=1 WHERE id=?", (inbox_id,))
    conn.commit()
    conn.close()
 
 
# ── Memory ────────────────────────────────────────────────────────
 
def set_memory(key, value):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO memory (key, value, updated) VALUES (?,?,datetime('now'))",
        (key, value)
    )
    conn.commit()
    conn.close()
 
def get_memory(key):
    conn = get_conn()
    row = conn.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None
 
def get_all_memory():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM memory ORDER BY key").fetchall()
    conn.close()
    return [tuple(r) for r in rows]
 
 
# ── Analytics ────────────────────────────────────────────────────
 
def log_analytics(event):
    conn = get_conn()
    conn.execute("INSERT INTO analytics (event) VALUES (?)", (event,))
    conn.commit()
    conn.close()
 
def get_analytics_summary():
    conn = get_conn()
    rows = conn.execute(
        "SELECT event, COUNT(*) as count FROM analytics GROUP BY event ORDER BY count DESC"
    ).fetchall()
    conn.close()
    return [tuple(r) for r in rows]
 
 
# ── Init on import ────────────────────────────────────────────────
init_db()


# ── Init on import ────────────────────────────────────────────────
init_db()
