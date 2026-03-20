#!/usr/bin/env python3
"""Clear Ahead Behavioral Tracker — main daemon."""

import argparse
import logging
import signal
import sys
import threading
import time
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("tracker")

from storage import Storage
from signal_registry import SignalRegistry
from monitors.calendar import CalendarMonitor
from monitors.apps import AppMonitor
from monitors.input import InputMonitor
from monitors.system_ext import SystemExtMonitor
from dashboard import Dashboard
from menubar import MenubarApp

DASHBOARD_PORT = 7331


def main():
    parser = argparse.ArgumentParser(description="Clear Ahead Tracker")
    parser.add_argument("--no-menubar", action="store_true", help="Run headless")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Clear Ahead Behavioral Tracker starting…")
    logger.info("=" * 60)

    storage  = Storage()
    registry = SignalRegistry()

    storage.recover_crashed_sessions()
    session_id = storage.open_session()
    logger.info(f"Session {session_id} opened")

    # ── Monitors ──────────────────────────────────────────────────────
    calendar_monitor = CalendarMonitor(storage, session_id, registry)
    app_monitor      = AppMonitor(storage, session_id, registry)
    input_monitor    = InputMonitor(storage, session_id, registry)
    system_monitor   = SystemExtMonitor(storage, session_id, registry)

    calendar_monitor.start()
    app_monitor.start()
    input_monitor.start()
    system_monitor.start()

    # ── Dashboard ─────────────────────────────────────────────────────
    dashboard = Dashboard(storage, registry, port=DASHBOARD_PORT)
    dashboard.start()
    logger.info(f"Dashboard → http://127.0.0.1:{DASHBOARD_PORT}")

    # ── Shutdown ──────────────────────────────────────────────────────
    def shutdown(reason: str = "clean"):
        logger.info(f"Shutting down ({reason})…")
        input_monitor.stop()
        app_monitor.stop()
        calendar_monitor.stop()
        system_monitor.stop()
        storage.close_session(session_id, reason=reason)
        logger.info(f"Session {session_id} closed. All data saved.")

    def _sig(_s, _f):
        shutdown("clean")
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    logger.info(f"All components running. Session ID: {session_id}")

    if args.no_menubar:
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            shutdown("clean")
    else:
        menubar = MenubarApp(storage, dashboard_port=DASHBOARD_PORT, shutdown_fn=shutdown)
        menubar.run()


if __name__ == "__main__":
    main()
