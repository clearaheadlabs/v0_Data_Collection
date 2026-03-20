"""App switching monitor using NSWorkspace."""

import logging
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from AppKit import NSWorkspace, NSWorkspaceDidActivateApplicationNotification
    from Foundation import NSNotificationCenter
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False
    logger.warning("AppKit not available – app monitoring disabled")


class AppMonitor:
    """Tracks which application is in focus and how long."""

    def __init__(self, storage):
        self.storage = storage
        self._current_app: Optional[str] = None
        self._current_start: Optional[datetime] = None
        self._observer = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        if not HAS_APPKIT:
            logger.info("AppMonitor: AppKit unavailable, skipping")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="app-monitor")
        self._thread.start()
        logger.info("AppMonitor started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def get_current_app(self) -> Optional[str]:
        return self._current_app

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self):
        """Poll for active app changes. Polling is simpler than NSRunLoop
        notification plumbing from a background thread."""
        workspace = NSWorkspace.sharedWorkspace()
        while not self._stop_event.is_set():
            try:
                active = workspace.frontmostApplication()
                app_name = str(active.localizedName()) if active else None
                if app_name and app_name != self._current_app:
                    self._on_app_switch(app_name)
            except Exception as e:
                logger.debug(f"AppMonitor poll error: {e}")
            self._stop_event.wait(1.0)  # 1-second resolution

    def _on_app_switch(self, new_app: str):
        now = datetime.now()
        from_app = self._current_app
        duration = 0

        if from_app and self._current_start:
            duration = int((now - self._current_start).total_seconds())
            try:
                self.storage.insert_context_switch(now, from_app, new_app, duration)
            except Exception as e:
                logger.error(f"AppMonitor storage error: {e}")
        elif from_app is None and self._current_start is None:
            # First switch — record with 0 duration
            try:
                self.storage.insert_context_switch(now, None, new_app, 0)
            except Exception as e:
                logger.error(f"AppMonitor storage error: {e}")

        logger.debug(f"App switch: {from_app} → {new_app} (was active {duration}s)")
        self._current_app = new_app
        self._current_start = now
