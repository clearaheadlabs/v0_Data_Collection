#!/usr/bin/env python3
"""Clear Ahead Behavioral Tracker — main daemon.

Usage:
    python tracker.py              # run with menubar (default)
    python tracker.py --no-menubar # headless mode (terminal only)
"""

import argparse
import logging
import signal
import sys
import threading
import time
from datetime import datetime

import psutil

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("tracker")

from storage import Storage
from monitors.calendar import CalendarMonitor
from monitors.apps import AppMonitor
from monitors.input import InputMonitor
from dashboard import Dashboard
from menubar import MenubarApp

DASHBOARD_PORT = 7331
SYSTEM_METRICS_INTERVAL = 300  # 5 minutes


def collect_system_metrics(storage: Storage, session_id: int, stop_event: threading.Event):
    """Background thread: record tracker's own CPU/RAM every 5 minutes."""
    proc = psutil.Process()
    # Initial reading — cpu_percent needs a prior call to calibrate
    proc.cpu_percent(interval=None)
    while not stop_event.is_set():
        stop_event.wait(SYSTEM_METRICS_INTERVAL)
        if stop_event.is_set():
            break
        try:
            cpu = proc.cpu_percent(interval=1)
            mem_mb = int(proc.memory_info().rss / 1024 / 1024)
            storage.insert_system_metrics(session_id, datetime.now(), cpu, mem_mb)
            logger.info(f"System metrics — CPU: {cpu:.1f}%  RAM: {mem_mb} MB")
        except Exception as e:
            logger.error(f"System metrics error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Clear Ahead Tracker")
    parser.add_argument("--no-menubar", action="store_true", help="Run headless")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Clear Ahead Behavioral Tracker starting…")
    logger.info("=" * 60)

    storage = Storage()

    # ── Recover any sessions that crashed without closing ─────────────
    storage.recover_crashed_sessions()

    # ── Open a new session for this run ──────────────────────────────
    session_id = storage.open_session()
    logger.info(f"Session {session_id} opened at {datetime.now().isoformat()}")

    stop_event = threading.Event()

    # ── Start monitors ────────────────────────────────────────────────
    calendar_monitor = CalendarMonitor(storage, session_id)
    app_monitor = AppMonitor(storage, session_id)
    input_monitor = InputMonitor(storage, session_id)

    calendar_monitor.start()
    app_monitor.start()
    input_monitor.start()

    # ── System metrics collector ──────────────────────────────────────
    sys_thread = threading.Thread(
        target=collect_system_metrics,
        args=(storage, session_id, stop_event),
        daemon=True,
        name="sys-metrics",
    )
    sys_thread.start()

    # ── Dashboard ─────────────────────────────────────────────────────
    dashboard = Dashboard(storage, port=DASHBOARD_PORT)
    dashboard.start()
    logger.info(f"Dashboard → http://127.0.0.1:{DASHBOARD_PORT}")

    # ── Graceful shutdown ─────────────────────────────────────────────
    def shutdown(reason: str = "clean"):
        logger.info(f"Shutting down (reason={reason})…")
        stop_event.set()

        # Stop monitors — each flushes its buffer before returning
        input_monitor.stop()   # flushes keystroke buffer
        app_monitor.stop()     # writes final app duration
        calendar_monitor.stop()

        # Mark session closed
        storage.close_session(session_id, reason=reason)
        logger.info(f"Session {session_id} closed. All data saved.")

    def signal_handler(_signum, _frame):
        shutdown("clean")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info(f"All components started. Session ID: {session_id}. Press Ctrl+C to stop.")

    # ── Menubar (blocks on main thread) or headless ───────────────────
    if args.no_menubar:
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            shutdown("clean")
    else:
        menubar = MenubarApp(storage, dashboard_port=DASHBOARD_PORT, shutdown_fn=shutdown)
        menubar.run()  # blocks until quit; calls shutdown internally


if __name__ == "__main__":
    main()
