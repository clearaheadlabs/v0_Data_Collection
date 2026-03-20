"""App switching monitor — NSWorkspace with bundle ID and category tagging."""

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

# ── App category map (bundle ID → category, then name fallback) ───────────────
_BUNDLE_CATEGORIES: dict[str, str] = {
    "com.apple.Safari":                  "browser",
    "com.google.Chrome":                 "browser",
    "org.mozilla.firefox":               "browser",
    "company.thebrowser.Browser":        "browser",   # Arc
    "com.brave.Browser":                 "browser",
    "com.microsoft.edgemac":             "browser",
    "com.apple.mail":                    "communication",
    "com.tinyspeck.slackmacgap":         "communication",
    "com.discord":                       "communication",
    "com.apple.MobileSMS":               "communication",  # Messages
    "us.zoom.xos":                       "communication",
    "com.microsoft.teams":               "communication",
    "com.apple.FaceTime":                "communication",
    "ru.keepcoder.Telegram":             "communication",
    "net.whatsapp.WhatsApp":             "communication",
    "com.apple.dt.Xcode":                "development",
    "com.microsoft.VSCode":              "development",
    "com.jetbrains.pycharm":             "development",
    "com.jetbrains.intellij":            "development",
    "com.apple.Terminal":                "development",
    "com.googlecode.iterm2":             "development",
    "com.todesktop.230313mzl4w4u92":     "development",   # Cursor
    "com.apple.finder":                  "files",
    "com.figma.Desktop":                 "design",
    "com.bohemiancoding.sketch3":        "design",
    "com.adobe.Photoshop":               "design",
    "com.adobe.illustrator":             "design",
    "com.notion.id":                     "productivity",
    "md.obsidian":                       "productivity",
    "com.apple.Notes":                   "productivity",
    "com.apple.iCal":                    "productivity",
    "com.apple.reminders":               "productivity",
    "com.apple.Numbers":                 "productivity",
    "com.apple.Pages":                   "productivity",
    "com.apple.Keynote":                 "productivity",
    "com.microsoft.Word":                "productivity",
    "com.microsoft.Excel":               "productivity",
    "com.microsoft.Powerpoint":          "productivity",
    "com.spotify.client":                "media",
    "com.apple.Music":                   "media",
    "org.videolan.vlc":                  "media",
    "com.apple.systempreferences":       "system",
    "com.apple.ActivityMonitor":         "system",
}

_NAME_CATEGORIES: dict[str, str] = {
    "Safari": "browser", "Chrome": "browser", "Firefox": "browser",
    "Arc": "browser", "Brave": "browser", "Edge": "browser",
    "Mail": "communication", "Slack": "communication", "Discord": "communication",
    "Messages": "communication", "Zoom": "communication", "Teams": "communication",
    "Telegram": "communication", "WhatsApp": "communication",
    "Xcode": "development", "Code": "development", "PyCharm": "development",
    "Terminal": "development", "iTerm2": "development", "Cursor": "development",
    "Finder": "files",
    "Figma": "design", "Sketch": "design", "Photoshop": "design",
    "Notion": "productivity", "Obsidian": "productivity", "Notes": "productivity",
    "Calendar": "productivity", "Reminders": "productivity",
    "Numbers": "productivity", "Pages": "productivity", "Keynote": "productivity",
    "Spotify": "media", "Music": "media", "VLC": "media",
    "System Settings": "system", "Activity Monitor": "system",
}


def categorize(bundle_id: str, app_name: str) -> str:
    if bundle_id and bundle_id in _BUNDLE_CATEGORIES:
        return _BUNDLE_CATEGORIES[bundle_id]
    for key, cat in _NAME_CATEGORIES.items():
        if key.lower() in app_name.lower():
            return cat
    return "other"


class AppMonitor:
    def __init__(self, storage, session_id: int, registry=None):
        self.storage = storage
        self.session_id = session_id
        self.registry = registry
        self._current_app: Optional[str] = None
        self._current_bundle: Optional[str] = None
        self._current_start: Optional[datetime] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if not HAS_APPKIT:
            logger.info("AppMonitor: AppKit unavailable, skipping")
            if self.registry:
                for sig in ("app_switches", "app_bundle_id", "app_category"):
                    self.registry.set_status(sig, "unavailable", "AppKit not installed")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="app-monitor")
        self._thread.start()
        logger.info("AppMonitor started")

    def stop(self):
        self._stop_event.set()
        self._close_current_app()
        if self._thread:
            self._thread.join(timeout=3)

    def get_current_app(self) -> Optional[str]:
        return self._current_app

    def _run(self):
        workspace = NSWorkspace.sharedWorkspace()
        while not self._stop_event.is_set():
            try:
                active = workspace.frontmostApplication()
                if active:
                    app_name  = str(active.localizedName() or "")
                    bundle_id = str(active.bundleIdentifier() or "")
                    if app_name and app_name != self._current_app:
                        self._on_app_switch(app_name, bundle_id)
            except Exception as e:
                logger.debug(f"AppMonitor poll error: {e}")
            self._stop_event.wait(1.0)

    def _on_app_switch(self, new_app: str, bundle_id: str):
        now = datetime.now()
        category = categorize(bundle_id, new_app)
        with self._lock:
            from_app = self._current_app
            duration = 0
            if from_app is not None and self._current_start is not None:
                duration = int((now - self._current_start).total_seconds())
            try:
                self.storage.insert_context_switch(
                    self.session_id, now, from_app, new_app, duration,
                    bundle_id=bundle_id, app_category=category,
                )
                if self.registry:
                    self.registry.record("app_switches")
                    self.registry.record("app_bundle_id")
                    self.registry.record("app_category")
            except Exception as e:
                logger.error(f"AppMonitor storage error: {e}")
            logger.debug(f"App: {from_app} → {new_app} [{category}] ({duration}s)")
            self._current_app    = new_app
            self._current_bundle = bundle_id
            self._current_start  = now

    def _close_current_app(self):
        now = datetime.now()
        with self._lock:
            if self._current_app is None or self._current_start is None:
                return
            duration = int((now - self._current_start).total_seconds())
            try:
                self.storage.insert_context_switch(
                    self.session_id, now, self._current_app, "<<tracker stopped>>",
                    duration, bundle_id="", app_category="",
                )
            except Exception as e:
                logger.error(f"AppMonitor close error: {e}")
            self._current_app = None
            self._current_start = None
