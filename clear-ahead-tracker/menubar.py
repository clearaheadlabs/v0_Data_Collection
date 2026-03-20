"""Menubar status indicator using rumps."""

import logging
import threading
import time
import webbrowser

import psutil

logger = logging.getLogger(__name__)

try:
    import rumps
    HAS_RUMPS = True
except ImportError:
    HAS_RUMPS = False
    logger.warning("rumps not available – menubar indicator disabled")


class MenubarApp:
    """Shows tracker status in the macOS menu bar."""

    UPDATE_INTERVAL = 10  # seconds between stat refreshes

    def __init__(self, storage, dashboard_port: int = 7331):
        self.storage = storage
        self.dashboard_port = dashboard_port
        self._proc = psutil.Process()
        self._app: "rumps.App | None" = None

    def run(self):
        """Blocking call — runs the rumps event loop (must be on main thread)."""
        if not HAS_RUMPS:
            logger.info("MenubarApp: rumps unavailable, skipping")
            self._park_main_thread()
            return

        self._app = rumps.App(
            "🟢",
            title="●",
            quit_button="Quit Tracker",
        )
        self._app.menu = [
            rumps.MenuItem("Open Dashboard", callback=self._open_dashboard),
            rumps.separator,
            rumps.MenuItem("CPU: …", callback=None),
            rumps.MenuItem("RAM: …", callback=None),
            rumps.separator,
        ]

        # Background thread to refresh menu stats
        t = threading.Thread(target=self._refresh_loop, daemon=True, name="menubar-refresh")
        t.start()

        self._app.run()

    def _open_dashboard(self, _=None):
        webbrowser.open(f"http://127.0.0.1:{self.dashboard_port}")

    def _refresh_loop(self):
        while True:
            try:
                cpu = self._proc.cpu_percent(interval=1)
                mem_mb = int(self._proc.memory_info().rss / 1024 / 1024)
                if self._app:
                    self._app.title = f"● {cpu:.1f}%"
                    self._app.menu["CPU: …"].title = f"CPU: {cpu:.1f}%"
                    self._app.menu["RAM: …"].title = f"RAM: {mem_mb} MB"
            except Exception as e:
                logger.debug(f"MenubarApp refresh error: {e}")
            time.sleep(self.UPDATE_INTERVAL)

    @staticmethod
    def _park_main_thread():
        """When rumps is not available, keep main thread alive."""
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
