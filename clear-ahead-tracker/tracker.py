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

# ── Local imports ─────────────────────────────────────────────────────────────
from storage import Storage
from monitors.calendar import CalendarMonitor
from monitors.apps import AppMonitor
from monitors.input import InputMonitor
from dashboard import Dashboard
from menubar import MenubarApp

DASHBOARD_PORT = 7331
SYSTEM_METRICS_INTERVAL = 300  # 5 minutes


def collect_system_metrics(storage: Storage, stop_event: threading.Event):
    """Background thread: record tracker's own CPU/RAM every 5 minutes."""
    proc = psutil.Process()
    while not stop_event.is_set():
        stop_event.wait(SYSTEM_METRICS_INTERVAL)
        try:
            cpu = proc.cpu_percent(interval=1)
            mem_mb = int(proc.memory_info().rss / 1024 / 1024)
            storage.insert_system_metrics(datetime.now(), cpu, mem_mb)
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
    stop_event = threading.Event()

    # ── Start monitors ────────────────────────────────────────────────
    calendar_monitor = CalendarMonitor(storage)
    app_monitor = AppMonitor(storage)
    input_monitor = InputMonitor(storage)

    calendar_monitor.start()
    app_monitor.start()
    input_monitor.start()

    # ── System metrics collector ──────────────────────────────────────
    sys_thread = threading.Thread(
        target=collect_system_metrics,
        args=(storage, stop_event),
        daemon=True,
        name="sys-metrics",
    )
    sys_thread.start()

    # ── Dashboard ─────────────────────────────────────────────────────
    dashboard = Dashboard(storage, port=DASHBOARD_PORT)
    dashboard.start()
    logger.info(f"Dashboard → http://127.0.0.1:{DASHBOARD_PORT}")

    # ── Graceful shutdown ─────────────────────────────────────────────
    def shutdown(signum, frame):
        logger.info("Shutdown signal received, stopping monitors…")
        stop_event.set()
        calendar_monitor.stop()
        app_monitor.stop()
        input_monitor.stop()
        logger.info("Clear Ahead Tracker stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("All components started. Press Ctrl+C to stop.")

    # ── Menubar (blocks on main thread) or headless ───────────────────
    if args.no_menubar:
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            shutdown(None, None)
    else:
        menubar = MenubarApp(storage, dashboard_port=DASHBOARD_PORT)
        menubar.run()  # blocks until quit


if __name__ == "__main__":
    main()
