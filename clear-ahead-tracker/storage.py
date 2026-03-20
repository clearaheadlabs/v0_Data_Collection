"""SQLite storage wrapper — schema v2 (all DATA.md signals)."""

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
DB_PATH = Path(__file__).parent / "data" / "tracker.db"

# ── New columns added per table in v2 ────────────────────────────────────────
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "context_switches": [
        ("bundle_id",    "TEXT"),
        ("app_category", "TEXT"),
    ],
    "keystroke_metrics": [
        ("typing_speed_cpm",  "REAL"),
        ("modifier_count",    "INTEGER"),
        ("burst_count",       "INTEGER"),
        ("rhythm_variance_ms","REAL"),
        ("mouse_distance_px", "REAL"),
        ("mouse_click_left",  "INTEGER"),
        ("mouse_click_right", "INTEGER"),
        ("mouse_click_double","INTEGER"),
        ("mouse_scroll_units","REAL"),
        ("mouse_idle_seconds","REAL"),
    ],
    "calendar_events": [
        ("attendee_count",  "INTEGER"),
        ("is_meeting",      "INTEGER"),
        ("calendar_source", "TEXT"),
    ],
    "system_metrics": [
        ("system_cpu_percent", "REAL"),
        ("system_memory_mb",   "INTEGER"),
        ("battery_percent",    "REAL"),
        ("battery_charging",   "INTEGER"),
        ("disk_read_mb",       "REAL"),
        ("disk_write_mb",      "REAL"),
        ("net_sent_mb",        "REAL"),
        ("net_recv_mb",        "REAL"),
        ("vpn_active",         "INTEGER"),
        ("wifi_signal_dbm",    "REAL"),
        ("audio_volume",       "INTEGER"),
        ("audio_muted",        "INTEGER"),
        ("brightness_percent", "REAL"),
    ],
}


class Storage:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()
        self._migrate()

    # ── Connection ────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            c = sqlite3.connect(str(self.db_path), check_same_thread=False, isolation_level=None)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.row_factory = sqlite3.Row
            self._local.conn = c
        return self._local.conn

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id               INTEGER PRIMARY KEY,
                started_at       TIMESTAMP NOT NULL,
                ended_at         TIMESTAMP,
                end_reason       TEXT,
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

            CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
            CREATE INDEX IF NOT EXISTS idx_cs_ts  ON context_switches(timestamp);
            CREATE INDEX IF NOT EXISTS idx_km_ts  ON keystroke_metrics(timestamp);
            CREATE INDEX IF NOT EXISTS idx_sm_ts  ON system_metrics(timestamp);
            CREATE INDEX IF NOT EXISTS idx_ce_st  ON calendar_events(start_time);
        """)
        conn.commit()
        conn.close()

    def _migrate(self):
        """Idempotently add new columns and session_id FK."""
        conn = sqlite3.connect(str(self.db_path))
        for table, new_cols in _MIGRATIONS.items():
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "session_id" not in existing:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN session_id INTEGER REFERENCES sessions(id)"
                )
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table[:3]}_sid ON {table}(session_id)"
                )
            for col, typ in new_cols:
                if col not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        conn.commit()
        conn.close()

    # ── Validation ────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_ts(ts: datetime) -> bool:
        now = datetime.now()
        age_days = (now - ts).days
        return 0 <= age_days <= 30 and ts <= now

    @staticmethod
    def _clamp(val, lo, hi):
        if val is None:
            return None
        return max(lo, min(hi, val))

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def open_session(self) -> int:
        c = self._conn()
        cur = c.execute("INSERT INTO sessions (started_at) VALUES (?)", (datetime.now().isoformat(),))
        c.commit()
        return cur.lastrowid

    def close_session(self, session_id: int, reason: str = "clean"):
        c = self._conn()
        row = c.execute("SELECT started_at FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return
        ended = datetime.now()
        duration = int((ended - datetime.fromisoformat(row["started_at"])).total_seconds())
        c.execute(
            "UPDATE sessions SET ended_at=?, end_reason=?, duration_seconds=? WHERE id=?",
            (ended.isoformat(), reason, duration, session_id),
        )
        c.commit()

    def recover_crashed_sessions(self):
        c = self._conn()
        open_sess = c.execute("SELECT id, started_at FROM sessions WHERE ended_at IS NULL").fetchall()
        for sess in open_sess:
            sid = sess["id"]
            last_ts = None
            for tbl, col in [("context_switches","timestamp"),("keystroke_metrics","timestamp"),("system_metrics","timestamp")]:
                r = c.execute(f"SELECT MAX({col}) as ts FROM {tbl} WHERE session_id=?", (sid,)).fetchone()
                if r and r["ts"] and (last_ts is None or r["ts"] > last_ts):
                    last_ts = r["ts"]
            ended_at = last_ts or sess["started_at"]
            duration = int((datetime.fromisoformat(ended_at) - datetime.fromisoformat(sess["started_at"])).total_seconds())
            c.execute(
                "UPDATE sessions SET ended_at=?, end_reason=?, duration_seconds=? WHERE id=?",
                (ended_at, "crash", duration, sid),
            )
        c.commit()
        if open_sess:
            logger.warning(f"Recovered {len(open_sess)} crashed session(s)")

    # ── Inserts ───────────────────────────────────────────────────────────────

    def upsert_calendar_event(self, session_id: int, title: str, start_time: datetime,
                               end_time: datetime, duration_minutes: int,
                               attendee_count: int = 0, is_meeting: bool = False,
                               calendar_source: str = ""):
        if not self._validate_ts(start_time):
            return
        c = self._conn()
        c.execute(
            """INSERT INTO calendar_events
               (session_id, title, start_time, end_time, duration_minutes,
                attendee_count, is_meeting, calendar_source)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT DO NOTHING""",
            (session_id, title, start_time.isoformat(), end_time.isoformat(),
             duration_minutes, attendee_count, int(is_meeting), calendar_source),
        )
        c.commit()

    def insert_context_switch(self, session_id: int, timestamp: datetime,
                               from_app: Optional[str], to_app: str,
                               duration_seconds: int,
                               bundle_id: str = "", app_category: str = ""):
        if not self._validate_ts(timestamp):
            return
        c = self._conn()
        c.execute(
            """INSERT INTO context_switches
               (session_id, timestamp, from_app, to_app, duration_seconds, bundle_id, app_category)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, timestamp.isoformat(), from_app, to_app,
             duration_seconds, bundle_id, app_category),
        )
        c.commit()

    def insert_input_metrics(self, session_id: int, timestamp: datetime,
                              keystroke_count: int, avg_latency_ms: float,
                              backspace_count: int, typing_speed_cpm: float = 0,
                              modifier_count: int = 0, burst_count: int = 0,
                              rhythm_variance_ms: float = 0,
                              mouse_distance_px: float = 0,
                              mouse_click_left: int = 0, mouse_click_right: int = 0,
                              mouse_click_double: int = 0, mouse_scroll_units: float = 0,
                              mouse_idle_seconds: float = 0):
        if not self._validate_ts(timestamp):
            return
        # Validate latency
        if avg_latency_ms > 60_000:
            logger.debug("Rejected impossible inter-key latency")
            return
        c = self._conn()
        c.execute(
            """INSERT INTO keystroke_metrics
               (session_id, timestamp, keystroke_count, avg_latency_ms, backspace_count,
                typing_speed_cpm, modifier_count, burst_count, rhythm_variance_ms,
                mouse_distance_px, mouse_click_left, mouse_click_right, mouse_click_double,
                mouse_scroll_units, mouse_idle_seconds)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session_id, timestamp.isoformat(), keystroke_count, round(avg_latency_ms, 2),
             backspace_count, round(typing_speed_cpm, 1), modifier_count, burst_count,
             round(rhythm_variance_ms, 2), round(mouse_distance_px, 1),
             mouse_click_left, mouse_click_right, mouse_click_double,
             round(mouse_scroll_units, 1), round(mouse_idle_seconds, 1)),
        )
        c.commit()

    # Keep old name as alias for backward compat
    def insert_keystroke_metrics(self, session_id, timestamp, keystroke_count,
                                  avg_latency_ms, backspace_count):
        self.insert_input_metrics(session_id, timestamp, keystroke_count,
                                   avg_latency_ms, backspace_count)

    def insert_system_metrics(self, session_id: int, timestamp: datetime,
                               cpu_percent: float = 0, memory_mb: int = 0,
                               system_cpu_percent: float = 0, system_memory_mb: int = 0,
                               battery_percent: Optional[float] = None,
                               battery_charging: Optional[bool] = None,
                               disk_read_mb: float = 0, disk_write_mb: float = 0,
                               net_sent_mb: float = 0, net_recv_mb: float = 0,
                               vpn_active: Optional[bool] = None,
                               wifi_signal_dbm: Optional[float] = None,
                               audio_volume: Optional[int] = None,
                               audio_muted: Optional[bool] = None,
                               brightness_percent: Optional[float] = None):
        if not self._validate_ts(timestamp):
            return
        cpu_percent         = self._clamp(cpu_percent, 0, 100)
        system_cpu_percent  = self._clamp(system_cpu_percent, 0, 100)
        battery_percent     = self._clamp(battery_percent, 0, 100)
        audio_volume        = self._clamp(audio_volume, 0, 100)
        brightness_percent  = self._clamp(brightness_percent, 0, 100)
        c = self._conn()
        c.execute(
            """INSERT INTO system_metrics
               (session_id, timestamp, cpu_percent, memory_mb,
                system_cpu_percent, system_memory_mb,
                battery_percent, battery_charging,
                disk_read_mb, disk_write_mb, net_sent_mb, net_recv_mb,
                vpn_active, wifi_signal_dbm,
                audio_volume, audio_muted, brightness_percent)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session_id, timestamp.isoformat(), cpu_percent, memory_mb,
             system_cpu_percent, system_memory_mb,
             battery_percent, int(battery_charging) if battery_charging is not None else None,
             disk_read_mb, disk_write_mb, net_sent_mb, net_recv_mb,
             int(vpn_active) if vpn_active is not None else None,
             wifi_signal_dbm, audio_volume,
             int(audio_muted) if audio_muted is not None else None,
             brightness_percent),
        )
        c.commit()

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_today_summary(self) -> dict:
        c = self._conn()
        today = datetime.now().date().isoformat()

        cal_count    = c.execute("SELECT COUNT(*) FROM calendar_events WHERE date(start_time)=?", (today,)).fetchone()[0]
        switch_count = c.execute("SELECT COUNT(*) FROM context_switches WHERE date(timestamp)=?", (today,)).fetchone()[0]
        top_apps     = c.execute(
            """SELECT to_app, COUNT(*) as cnt FROM context_switches
               WHERE date(timestamp)=? GROUP BY to_app ORDER BY cnt DESC LIMIT 5""", (today,)
        ).fetchall()
        ks_row       = c.execute("SELECT SUM(keystroke_count) FROM keystroke_metrics WHERE date(timestamp)=?", (today,)).fetchone()
        sys_row      = c.execute("SELECT * FROM system_metrics ORDER BY timestamp DESC LIMIT 1").fetchone()
        sessions_today = c.execute(
            "SELECT id,started_at,ended_at,end_reason,duration_seconds FROM sessions WHERE date(started_at)=? ORDER BY started_at", (today,)
        ).fetchall()

        return {
            "calendar_events":  cal_count,
            "context_switches": switch_count,
            "top_apps":         [dict(r) for r in top_apps],
            "keystroke_total":  ks_row[0] or 0,
            "cpu_percent":      sys_row["cpu_percent"]    if sys_row else 0,
            "memory_mb":        sys_row["memory_mb"]      if sys_row else 0,
            "battery_percent":  sys_row["battery_percent"] if sys_row else None,
            "sessions_today":   [dict(r) for r in sessions_today],
        }

    def get_all_sessions(self) -> list:
        c = self._conn()
        return [dict(r) for r in c.execute("SELECT * FROM sessions ORDER BY started_at DESC").fetchall()]

    def get_recent_switches(self, limit: int = 100) -> list:
        c = self._conn()
        return [dict(r) for r in c.execute(
            """SELECT cs.* FROM context_switches cs
               WHERE cs.to_app != '<<tracker stopped>>'
               ORDER BY cs.timestamp DESC LIMIT ?""", (limit,)
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

    def get_recent_system(self, limit: int = 50) -> list:
        c = self._conn()
        return [dict(r) for r in c.execute(
            "SELECT * FROM system_metrics ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()]

    def get_all_for_export(self) -> dict:
        c = self._conn()
        return {
            "sessions":          [dict(r) for r in c.execute("SELECT * FROM sessions ORDER BY started_at").fetchall()],
            "calendar_events":   [dict(r) for r in c.execute("SELECT * FROM calendar_events ORDER BY start_time").fetchall()],
            "context_switches":  [dict(r) for r in c.execute("SELECT * FROM context_switches ORDER BY timestamp").fetchall()],
            "keystroke_metrics": [dict(r) for r in c.execute("SELECT * FROM keystroke_metrics ORDER BY timestamp").fetchall()],
            "system_metrics":    [dict(r) for r in c.execute("SELECT * FROM system_metrics ORDER BY timestamp").fetchall()],
        }
