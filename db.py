"""SQLite event logging for the admin dashboard.

Tracks two kinds of events:
- 'generate': every POST /process submission (both success and failure)
- 'save_as' : every hit on /outputs/<filename>?dl=... — that's the URL the
              "Save image" button/link points at (as_attachment=True), so a
              request there means the user clicked it.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "analytics.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,      -- 'generate' or 'save_as'
    created_at TEXT NOT NULL,      -- ISO 8601 UTC timestamp
    video_title TEXT,
    video_url TEXT,
    start_time TEXT,
    end_time TEXT,
    success INTEGER,               -- 1/0, only meaningful for 'generate'
    filename TEXT                  -- downloaded filename, only for 'save_as'
);
"""


@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(SCHEMA)


def log_generate(video_title, video_url, start_time, end_time, success):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO events "
            "(event_type, created_at, video_title, video_url, start_time, end_time, success) "
            "VALUES ('generate', ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                video_title,
                video_url,
                start_time,
                end_time,
                int(bool(success)),
            ),
        )


def log_save_as(filename, video_title=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO events (event_type, created_at, filename, video_title) "
            "VALUES ('save_as', ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), filename, video_title),
        )


def get_stats(video_limit=200):
    with get_conn() as conn:
        generate_total = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='generate'"
        ).fetchone()[0]
        generate_success = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='generate' AND success=1"
        ).fetchone()[0]
        save_as_total = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='save_as'"
        ).fetchone()[0]
        videos = conn.execute(
            "SELECT video_title, video_url, start_time, end_time, created_at "
            "FROM events WHERE event_type='generate' AND success=1 "
            "ORDER BY created_at DESC LIMIT ?",
            (video_limit,),
        ).fetchall()
    return {
        "generate_total": generate_total,
        "generate_success": generate_success,
        "generate_failed": generate_total - generate_success,
        "save_as_total": save_as_total,
        "videos": videos,
    }
