"""App switching monitor using NSWorkspace."""

import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from AppKit import NSWorkspace
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False
    logger.warning("AppKit not available – app monitoring disabled")


class AppMonitor:
    """Tracks which application is in focus and how long."""

    def __init__(self, storage, session_id: int):
        self.storage = storage
        self.session_id = session_id
        self._current_app: Optional[str] = None
        self._current_start: Optional[datetime] = None
        self._lock = threading.Lock()
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
        """Signal stop and flush the last open app window."""
        self._stop_event.set()
        self._close_current_app()  # write final duration before exit
        if self._thread:
            self._thread.join(timeout=3)

    def get_current_app(self) -> Optional[str]:
        return self._current_app

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self):
        workspace = NSWorkspace.sharedWorkspace()
        while not self._stop_event.is_set():
            try:
                active = workspace.frontmostApplication()
                app_name = str(active.localizedName()) if active else None
                if app_name and app_name != self._current_app:
                    self._on_app_switch(app_name)
            except Exception as e:
                logger.debug(f"AppMonitor poll error: {e}")
            self._stop_event.wait(1.0)

    def _on_app_switch(self, new_app: str):
        now = datetime.now()
        with self._lock:
            from_app = self._current_app
            duration = 0

            if from_app is not None and self._current_start is not None:
                duration = int((now - self._current_start).total_seconds())

            try:
                self.storage.insert_context_switch(
                    self.session_id, now, from_app, new_app, duration
                )
            except Exception as e:
                logger.error(f"AppMonitor storage error: {e}")

            logger.debug(f"App switch: {from_app} → {new_app} (was active {duration}s)")
            self._current_app = new_app
            self._current_start = now

    def _close_current_app(self):
        """Record final duration for the last active app before shutdown."""
        now = datetime.now()
        with self._lock:
            if self._current_app is None or self._current_start is None:
                return
            duration = int((now - self._current_start).total_seconds())
            try:
                # Record as a switch to the sentinel value "<<tracker stopped>>"
                # so the duration of the last app is preserved.
                self.storage.insert_context_switch(
                    self.session_id, now, self._current_app, "<<tracker stopped>>", duration
                )
                logger.debug(
                    f"AppMonitor: closing last window — {self._current_app} was active {duration}s"
                )
            except Exception as e:
                logger.error(f"AppMonitor close_current error: {e}")
            self._current_app = None
            self._current_start = None
