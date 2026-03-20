"""Central registry tracking live status of every data signal."""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

ACTIVE       = "active"
NO_PERMISSION = "no_permission"
UNAVAILABLE  = "unavailable"
FAILED       = "failed"
STARTING     = "starting"

# ── Signal catalogue (all signals we intend to capture) ──────────────────────
_CATALOGUE = [
    # (id, name, category, description)
    # App Behavior
    ("app_switches",       "App Switches",             "App Behavior", "Active app changes via NSWorkspace"),
    ("app_bundle_id",      "App Bundle ID",             "App Behavior", "CFBundleIdentifier from NSRunningApplication"),
    ("app_category",       "App Category",              "App Behavior", "Mapped category: browser, editor, communication, etc."),
    # Keyboard
    ("keystroke_count",    "Keystroke Count",           "Keyboard",     "Keystrokes per minute (no content captured)"),
    ("inter_key_latency",  "Inter-Key Latency",         "Keyboard",     "Average ms between consecutive keystrokes"),
    ("typing_speed_cpm",   "Typing Speed (CPM)",        "Keyboard",     "Characters per minute in the flush window"),
    ("backspace_rate",     "Backspace Rate",            "Keyboard",     "Delete/backspace key frequency"),
    ("modifier_key_freq",  "Modifier Key Frequency",    "Keyboard",     "Cmd/Ctrl/Alt/Shift usage count per minute"),
    ("typing_bursts",      "Typing Burst Pauses",       "Keyboard",     "Count of pauses >2 s between typing runs"),
    ("rhythm_variance",    "Typing Rhythm Variance",    "Keyboard",     "Std-dev of inter-key intervals (ms)"),
    # Mouse
    ("mouse_distance",     "Mouse Movement Distance",   "Mouse",        "Pixels moved per flush window"),
    ("mouse_clicks",       "Mouse Clicks",              "Mouse",        "Left / right / double click counts"),
    ("mouse_scroll",       "Scroll Activity",           "Mouse",        "Scroll-wheel delta units"),
    ("mouse_idle",         "Mouse Idle Time",           "Mouse",        "Seconds since last mouse or keyboard event"),
    # Calendar
    ("calendar_events",    "Calendar Events",           "Calendar",     "Events synced from iCal via EventKit"),
    ("calendar_attendees", "Attendee Count",            "Calendar",     "Number of attendees per event"),
    ("calendar_type",      "Meeting vs Solo",           "Calendar",     "Classified as meeting (≥1 attendee) or focus"),
    # System
    ("system_cpu",         "System CPU",                "System",       "System-wide CPU %"),
    ("tracker_cpu",        "Tracker CPU",               "System",       "This process CPU %"),
    ("tracker_memory",     "Tracker Memory",            "System",       "This process RAM MB"),
    ("system_memory",      "System Memory",             "System",       "System-wide RAM usage MB"),
    ("battery_level",      "Battery Level",             "System",       "Battery % and charging state"),
    ("disk_io",            "Disk I/O",                  "System",       "Cumulative read/write MB"),
    ("audio_volume",       "Audio Volume",              "System",       "Speaker volume & mute state via osascript"),
    ("display_brightness", "Display Brightness",        "System",       "Screen brightness level via IOKit/osascript"),
    # Network
    ("network_bytes",      "Network Bytes",             "Network",      "Bytes sent/received since last interval"),
    ("vpn_status",         "VPN Status",                "Network",      "Whether a VPN/utun interface is active"),
    ("wifi_signal",        "WiFi Signal Strength",      "Network",      "RSSI dBm via airport CLI"),
]


@dataclass
class SignalInfo:
    id: str
    name: str
    category: str
    description: str
    status: str = STARTING
    last_event: Optional[datetime] = None
    events_today: int = 0
    error: Optional[str] = None
    _today: str = field(default_factory=lambda: datetime.now().date().isoformat(), repr=False)


class SignalRegistry:
    def __init__(self):
        self._signals: dict[str, SignalInfo] = {}
        self._lock = threading.Lock()
        for sig_id, name, category, desc in _CATALOGUE:
            self._signals[sig_id] = SignalInfo(
                id=sig_id, name=name, category=category, description=desc
            )

    # ── Monitor API ───────────────────────────────────────────────────────────

    def set_status(self, signal_id: str, status: str, error: Optional[str] = None):
        with self._lock:
            if signal_id in self._signals:
                self._signals[signal_id].status = status
                self._signals[signal_id].error = error

    def record(self, signal_id: str, count: int = 1):
        """Mark a successful capture; bumps events_today and sets status=active."""
        with self._lock:
            sig = self._signals.get(signal_id)
            if sig is None:
                return
            today = datetime.now().date().isoformat()
            if sig._today != today:
                sig.events_today = 0
                sig._today = today
            sig.events_today += count
            sig.last_event = datetime.now()
            sig.status = ACTIVE
            sig.error = None

    # ── Dashboard / test API ──────────────────────────────────────────────────

    def get_all(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "id":           s.id,
                    "name":         s.name,
                    "category":     s.category,
                    "description":  s.description,
                    "status":       s.status,
                    "last_event":   s.last_event.strftime("%H:%M:%S") if s.last_event else None,
                    "events_today": s.events_today,
                    "error":        s.error,
                }
                for s in sorted(
                    self._signals.values(), key=lambda x: (x.category, x.name)
                )
            ]

    def summary(self) -> dict:
        with self._lock:
            statuses = [s.status for s in self._signals.values()]
        return {
            "total":         len(statuses),
            "active":        statuses.count(ACTIVE),
            "no_permission": statuses.count(NO_PERMISSION),
            "unavailable":   statuses.count(UNAVAILABLE),
            "failed":        statuses.count(FAILED),
            "starting":      statuses.count(STARTING),
        }
