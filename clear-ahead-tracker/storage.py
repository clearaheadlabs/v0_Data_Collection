"""SQLite storage wrapper for the Clear Ahead tracker."""

import sqlite3
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

DB_PATH = Path(__file__).parent / "data" / "tracker.db"


class Storage:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY,
                title TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                duration_minutes INTEGER
            );

            CREATE TABLE IF NOT EXISTS context_switches (
                id INTEGER PRIMARY KEY,
                timestamp TIMESTAMP,
                from_app TEXT,
                to_app TEXT,
                duration_seconds INTEGER
            );

            CREATE TABLE IF NOT EXISTS keystroke_metrics (
                id INTEGER PRIMARY KEY,
                timestamp TIMESTAMP,
                keystroke_count INTEGER,
                avg_latency_ms REAL,
                backspace_count INTEGER
            );

            CREATE TABLE IF NOT EXISTS system_metrics (
                id INTEGER PRIMARY KEY,
                timestamp TIMESTAMP,
                cpu_percent REAL,
                memory_mb INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_cs_timestamp ON context_switches(timestamp);
            CREATE INDEX IF NOT EXISTS idx_km_timestamp ON keystroke_metrics(timestamp);
            CREATE INDEX IF NOT EXISTS idx_sm_timestamp ON system_metrics(timestamp);
            CREATE INDEX IF NOT EXISTS idx_ce_start ON calendar_events(start_time);
        """)
        conn.commit()
        conn.close()

    def insert_calendar_event(self, title: str, start_time: datetime,
                               end_time: datetime, duration_minutes: int):
        c = self._conn()
        c.execute(
            "INSERT OR IGNORE INTO calendar_events (title, start_time, end_time, duration_minutes) "
            "VALUES (?, ?, ?, ?)",
            (title, start_time.isoformat(), end_time.isoformat(), duration_minutes),
        )
        c.commit()

    def upsert_calendar_event(self, title: str, start_time: datetime,
                               end_time: datetime, duration_minutes: int):
        c = self._conn()
        c.execute(
            "INSERT OR REPLACE INTO calendar_events (title, start_time, end_time, duration_minutes) "
            "VALUES (?, ?, ?, ?)",
            (title, start_time.isoformat(), end_time.isoformat(), duration_minutes),
        )
        c.commit()

    def insert_context_switch(self, timestamp: datetime, from_app: Optional[str],
                               to_app: str, duration_seconds: int):
        c = self._conn()
        c.execute(
            "INSERT INTO context_switches (timestamp, from_app, to_app, duration_seconds) "
            "VALUES (?, ?, ?, ?)",
            (timestamp.isoformat(), from_app, to_app, duration_seconds),
        )
        c.commit()

    def insert_keystroke_metrics(self, timestamp: datetime, keystroke_count: int,
                                  avg_latency_ms: float, backspace_count: int):
        c = self._conn()
        c.execute(
            "INSERT INTO keystroke_metrics (timestamp, keystroke_count, avg_latency_ms, backspace_count) "
            "VALUES (?, ?, ?, ?)",
            (timestamp.isoformat(), keystroke_count, avg_latency_ms, backspace_count),
        )
        c.commit()

    def insert_system_metrics(self, timestamp: datetime, cpu_percent: float,
                               memory_mb: int):
        c = self._conn()
        c.execute(
            "INSERT INTO system_metrics (timestamp, cpu_percent, memory_mb) "
            "VALUES (?, ?, ?)",
            (timestamp.isoformat(), cpu_percent, memory_mb),
        )
        c.commit()

    def get_today_summary(self) -> dict:
        c = self._conn()
        today = datetime.now().date().isoformat()

        cal_count = c.execute(
            "SELECT COUNT(*) FROM calendar_events WHERE date(start_time) = ?", (today,)
        ).fetchone()[0]

        switch_count = c.execute(
            "SELECT COUNT(*) FROM context_switches WHERE date(timestamp) = ?", (today,)
        ).fetchone()[0]

        top_apps = c.execute(
            """SELECT to_app, COUNT(*) as cnt FROM context_switches
               WHERE date(timestamp) = ?
               GROUP BY to_app ORDER BY cnt DESC LIMIT 5""",
            (today,),
        ).fetchall()

        ks_row = c.execute(
            """SELECT SUM(keystroke_count) FROM keystroke_metrics
               WHERE date(timestamp) = ?""",
            (today,),
        ).fetchone()
        keystroke_total = ks_row[0] or 0

        sys_row = c.execute(
            """SELECT cpu_percent, memory_mb FROM system_metrics
               ORDER BY timestamp DESC LIMIT 1"""
        ).fetchone()

        return {
            "calendar_events": cal_count,
            "context_switches": switch_count,
            "top_apps": [dict(r) for r in top_apps],
            "keystroke_total": keystroke_total,
            "cpu_percent": sys_row["cpu_percent"] if sys_row else 0,
            "memory_mb": sys_row["memory_mb"] if sys_row else 0,
        }

    def get_all_for_export(self) -> dict:
        c = self._conn()
        return {
            "calendar_events": [dict(r) for r in c.execute("SELECT * FROM calendar_events ORDER BY start_time").fetchall()],
            "context_switches": [dict(r) for r in c.execute("SELECT * FROM context_switches ORDER BY timestamp").fetchall()],
            "keystroke_metrics": [dict(r) for r in c.execute("SELECT * FROM keystroke_metrics ORDER BY timestamp").fetchall()],
            "system_metrics": [dict(r) for r in c.execute("SELECT * FROM system_metrics ORDER BY timestamp").fetchall()],
        }
