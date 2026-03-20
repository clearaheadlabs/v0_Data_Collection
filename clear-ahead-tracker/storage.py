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
        self._migrate()

    # ── Connection management ─────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                isolation_level=None,  # autocommit off; we call commit() explicitly
            )
            self._local.conn.execute("PRAGMA journal_mode=WAL")  # safe concurrent writes
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    # ── Schema init ───────────────────────────────────────────────────────────

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            -- Each continuous run of the tracker is one session.
            -- ended_at IS NULL means the session is still running or crashed.
            CREATE TABLE IF NOT EXISTS sessions (
                id           INTEGER PRIMARY KEY,
                started_at   TIMESTAMP NOT NULL,
                ended_at     TIMESTAMP,
                end_reason   TEXT,          -- 'clean' | 'crash'
                duration_seconds INTEGER
            );

            CREATE TABLE IF NOT EXISTS calendar_events (
                id               INTEGER PRIMARY KEY,
                session_id       INTEGER REFERENCES sessions(id),
                title            TEXT,
                start_time       TIMESTAMP,
                end_time         TIMESTAMP,
                duration_minutes INTEGER
            );

            CREATE TABLE IF NOT EXISTS context_switches (
                id               INTEGER PRIMARY KEY,
                session_id       INTEGER REFERENCES sessions(id),
                timestamp        TIMESTAMP,
                from_app         TEXT,
                to_app           TEXT,
                duration_seconds INTEGER
            );

            CREATE TABLE IF NOT EXISTS keystroke_metrics (
                id               INTEGER PRIMARY KEY,
                session_id       INTEGER REFERENCES sessions(id),
                timestamp        TIMESTAMP,
                keystroke_count  INTEGER,
                avg_latency_ms   REAL,
                backspace_count  INTEGER
            );

            CREATE TABLE IF NOT EXISTS system_metrics (
                id               INTEGER PRIMARY KEY,
                session_id       INTEGER REFERENCES sessions(id),
                timestamp        TIMESTAMP,
                cpu_percent      REAL,
                memory_mb        INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_started  ON sessions(started_at);
            CREATE INDEX IF NOT EXISTS idx_cs_timestamp      ON context_switches(timestamp);
            CREATE INDEX IF NOT EXISTS idx_km_timestamp      ON keystroke_metrics(timestamp);
            CREATE INDEX IF NOT EXISTS idx_sm_timestamp      ON system_metrics(timestamp);
            CREATE INDEX IF NOT EXISTS idx_ce_start          ON calendar_events(start_time);
        """)
        conn.commit()
        conn.close()

    def _migrate(self):
        """Add session_id column + indexes to tables created before sessions were introduced."""
        conn = sqlite3.connect(str(self.db_path))
        for table in ("calendar_events", "context_switches", "keystroke_metrics", "system_metrics"):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "session_id" not in cols:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN session_id INTEGER REFERENCES sessions(id)"
                )
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table[:2]}_session ON {table}(session_id)"
                )
        conn.commit()
        conn.close()

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def open_session(self) -> int:
        """Create a new session row and return its id."""
        c = self._conn()
        cur = c.execute(
            "INSERT INTO sessions (started_at) VALUES (?)",
            (datetime.now().isoformat(),),
        )
        c.commit()
        return cur.lastrowid

    def close_session(self, session_id: int, reason: str = "clean"):
        """Mark session as ended with duration."""
        c = self._conn()
        row = c.execute(
            "SELECT started_at FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return
        started = datetime.fromisoformat(row["started_at"])
        ended = datetime.now()
        duration = int((ended - started).total_seconds())
        c.execute(
            "UPDATE sessions SET ended_at = ?, end_reason = ?, duration_seconds = ? WHERE id = ?",
            (ended.isoformat(), reason, duration, session_id),
        )
        c.commit()

    def recover_crashed_sessions(self):
        """On startup, find sessions that never got an ended_at and mark them crashed.
        Uses the timestamp of the last event in that session as the best-guess end time.
        """
        c = self._conn()
        open_sessions = c.execute(
            "SELECT id, started_at FROM sessions WHERE ended_at IS NULL"
        ).fetchall()

        for sess in open_sessions:
            sid = sess["id"]
            # Find the latest event timestamp across all event tables for this session
            last_ts = None
            for table, col in [
                ("context_switches", "timestamp"),
                ("keystroke_metrics", "timestamp"),
                ("system_metrics", "timestamp"),
            ]:
                row = c.execute(
                    f"SELECT MAX({col}) as ts FROM {table} WHERE session_id = ?", (sid,)
                ).fetchone()
                if row and row["ts"]:
                    ts = row["ts"]
                    if last_ts is None or ts > last_ts:
                        last_ts = ts

            ended_at = last_ts or sess["started_at"]
            started = datetime.fromisoformat(sess["started_at"])
            ended = datetime.fromisoformat(ended_at)
            duration = int((ended - started).total_seconds())

            c.execute(
                "UPDATE sessions SET ended_at = ?, end_reason = ?, duration_seconds = ? WHERE id = ?",
                (ended_at, "crash", duration, sid),
            )

        c.commit()
        if open_sessions:
            import logging
            logging.getLogger(__name__).warning(
                f"Recovered {len(open_sessions)} crashed session(s)"
            )

    # ── Inserts ───────────────────────────────────────────────────────────────

    def upsert_calendar_event(self, session_id: int, title: str, start_time: datetime,
                               end_time: datetime, duration_minutes: int):
        c = self._conn()
        c.execute(
            """INSERT INTO calendar_events (session_id, title, start_time, end_time, duration_minutes)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT DO NOTHING""",
            (session_id, title, start_time.isoformat(), end_time.isoformat(), duration_minutes),
        )
        c.commit()

    def insert_context_switch(self, session_id: int, timestamp: datetime,
                               from_app: Optional[str], to_app: str, duration_seconds: int):
        c = self._conn()
        c.execute(
            """INSERT INTO context_switches (session_id, timestamp, from_app, to_app, duration_seconds)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, timestamp.isoformat(), from_app, to_app, duration_seconds),
        )
        c.commit()

    def insert_keystroke_metrics(self, session_id: int, timestamp: datetime,
                                  keystroke_count: int, avg_latency_ms: float,
                                  backspace_count: int):
        c = self._conn()
        c.execute(
            """INSERT INTO keystroke_metrics (session_id, timestamp, keystroke_count, avg_latency_ms, backspace_count)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, timestamp.isoformat(), keystroke_count, avg_latency_ms, backspace_count),
        )
        c.commit()

    def insert_system_metrics(self, session_id: int, timestamp: datetime,
                               cpu_percent: float, memory_mb: int):
        c = self._conn()
        c.execute(
            """INSERT INTO system_metrics (session_id, timestamp, cpu_percent, memory_mb)
               VALUES (?, ?, ?, ?)""",
            (session_id, timestamp.isoformat(), cpu_percent, memory_mb),
        )
        c.commit()

    # ── Queries ───────────────────────────────────────────────────────────────

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
            "SELECT SUM(keystroke_count) FROM keystroke_metrics WHERE date(timestamp) = ?",
            (today,),
        ).fetchone()
        keystroke_total = ks_row[0] or 0

        sys_row = c.execute(
            "SELECT cpu_percent, memory_mb FROM system_metrics ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()

        sessions_today = c.execute(
            """SELECT id, started_at, ended_at, end_reason, duration_seconds
               FROM sessions WHERE date(started_at) = ? ORDER BY started_at""",
            (today,),
        ).fetchall()

        return {
            "calendar_events": cal_count,
            "context_switches": switch_count,
            "top_apps": [dict(r) for r in top_apps],
            "keystroke_total": keystroke_total,
            "cpu_percent": sys_row["cpu_percent"] if sys_row else 0,
            "memory_mb": sys_row["memory_mb"] if sys_row else 0,
            "sessions_today": [dict(r) for r in sessions_today],
        }

    def get_all_sessions(self) -> list:
        c = self._conn()
        return [dict(r) for r in c.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC"
        ).fetchall()]

    def get_recent_switches(self, limit: int = 100) -> list:
        c = self._conn()
        return [dict(r) for r in c.execute(
            """SELECT cs.*, s.started_at as session_start
               FROM context_switches cs
               LEFT JOIN sessions s ON cs.session_id = s.id
               WHERE cs.to_app != '<<tracker stopped>>'
               ORDER BY cs.timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()]

    def get_recent_keystrokes(self, limit: int = 100) -> list:
        c = self._conn()
        return [dict(r) for r in c.execute(
            "SELECT * FROM keystroke_metrics ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()]

    def get_calendar_events(self, limit: int = 50) -> list:
        c = self._conn()
        return [dict(r) for r in c.execute(
            "SELECT * FROM calendar_events ORDER BY start_time DESC LIMIT ?", (limit,)
        ).fetchall()]

    def get_all_for_export(self) -> dict:
        c = self._conn()
        return {
            "sessions": [dict(r) for r in c.execute("SELECT * FROM sessions ORDER BY started_at").fetchall()],
            "calendar_events": [dict(r) for r in c.execute("SELECT * FROM calendar_events ORDER BY start_time").fetchall()],
            "context_switches": [dict(r) for r in c.execute("SELECT * FROM context_switches ORDER BY timestamp").fetchall()],
            "keystroke_metrics": [dict(r) for r in c.execute("SELECT * FROM keystroke_metrics ORDER BY timestamp").fetchall()],
            "system_metrics": [dict(r) for r in c.execute("SELECT * FROM system_metrics ORDER BY timestamp").fetchall()],
        }
