#!/usr/bin/env python3
"""
Clear Ahead — Signal Availability Test Suite
=============================================
Checks every data signal from DATA.md for availability, permissions,
and basic functionality. Run standalone:

    python tests/test_signals.py

Does NOT start the full tracker — only probes each signal individually.
"""

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# Allow imports from parent directory
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Result type ───────────────────────────────────────────────────────────────
OK           = "✅ PASS"
NO_PERM      = "⚠️  NO PERMISSION"
UNAVAILABLE  = "ℹ️  UNAVAILABLE"
FAIL         = "❌ FAIL"
SKIP         = "⬜ SKIP"

@dataclass
class Result:
    signal_id:   str
    name:        str
    category:    str
    status:      str          # OK / NO_PERM / UNAVAILABLE / FAIL / SKIP
    detail:      str = ""
    sample:      str = ""     # representative value captured

# ── Individual signal probes ──────────────────────────────────────────────────

def probe_quartz() -> bool:
    try:
        import Quartz
        return True
    except ImportError:
        return False

def probe_appkit() -> bool:
    try:
        import AppKit
        return True
    except ImportError:
        return False

def probe_eventkit() -> bool:
    try:
        import EventKit
        return True
    except ImportError:
        return False


def check_app_switches() -> Result:
    if not probe_appkit():
        return Result("app_switches", "App Switches", "App Behavior", UNAVAILABLE, "AppKit not importable")
    try:
        from AppKit import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        app = ws.frontmostApplication()
        name = str(app.localizedName()) if app else "(none)"
        return Result("app_switches", "App Switches", "App Behavior", OK, "NSWorkspace accessible", f"current={name}")
    except Exception as e:
        return Result("app_switches", "App Switches", "App Behavior", FAIL, str(e))


def check_app_bundle_id() -> Result:
    if not probe_appkit():
        return Result("app_bundle_id", "App Bundle ID", "App Behavior", UNAVAILABLE, "AppKit not importable")
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        bid = str(app.bundleIdentifier()) if app else ""
        return Result("app_bundle_id", "App Bundle ID", "App Behavior", OK, "bundleIdentifier() accessible", f"bid={bid}")
    except Exception as e:
        return Result("app_bundle_id", "App Bundle ID", "App Behavior", FAIL, str(e))


def check_app_category() -> Result:
    try:
        from monitors.apps import categorize
        cat = categorize("com.apple.Safari", "Safari")
        return Result("app_category", "App Category", "App Behavior", OK, "Category mapping functional", f"Safari→{cat}")
    except Exception as e:
        return Result("app_category", "App Category", "App Behavior", FAIL, str(e))


def check_event_tap(signal_id: str, name: str, category: str) -> Result:
    if not probe_quartz():
        return Result(signal_id, name, category, UNAVAILABLE, "Quartz not importable")
    try:
        import Quartz
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            (1 << 10),  # key down only
            lambda *a: a[-2],
            None,
        )
        if tap is None:
            return Result(signal_id, name, category, NO_PERM,
                          "CGEventTapCreate returned None",
                          "→ System Settings › Privacy & Security › Accessibility → add this app")
        Quartz.CGEventTapEnable(tap, False)
        return Result(signal_id, name, category, OK, "CGEventTap creatable (Accessibility granted)")
    except Exception as e:
        return Result(signal_id, name, category, FAIL, str(e))


def check_mouse_distance() -> Result:
    if not probe_quartz():
        return Result("mouse_distance", "Mouse Movement Distance", "Mouse", UNAVAILABLE, "Quartz not importable")
    try:
        import Quartz
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return Result("mouse_distance", "Mouse Movement Distance", "Mouse", OK,
                      "CGEventGetLocation accessible", f"pos=({loc.x:.0f},{loc.y:.0f})")
    except Exception as e:
        return Result("mouse_distance", "Mouse Movement Distance", "Mouse", FAIL, str(e))


def check_calendar_access() -> Result:
    if not probe_eventkit():
        return Result("calendar_events", "Calendar Events", "Calendar", UNAVAILABLE, "EventKit not importable")
    try:
        import EventKit
        status = EventKit.EKEventStore.authorizationStatusForEntityType_(EventKit.EKEntityTypeEvent)
        # 0=NotDetermined, 1=Restricted, 2=Denied, 3=Authorized, 4=FullAccess (macOS 14+)
        STATUS_MAP = {0: "not determined", 1: "restricted", 2: "denied", 3: "authorized", 4: "full_access"}
        status_str = STATUS_MAP.get(status, str(status))
        if status in (3, 4):
            return Result("calendar_events", "Calendar Events", "Calendar", OK,
                          f"Authorization: {status_str}")
        elif status == 0:
            return Result("calendar_events", "Calendar Events", "Calendar", NO_PERM,
                          "Not yet requested — will prompt on first run")
        else:
            return Result("calendar_events", "Calendar Events", "Calendar", NO_PERM,
                          f"Authorization: {status_str} — grant in System Settings › Privacy › Calendars")
    except Exception as e:
        return Result("calendar_events", "Calendar Events", "Calendar", FAIL, str(e))


def check_calendar_attendees() -> Result:
    base = check_calendar_access()
    if base.status != OK:
        return Result("calendar_attendees", "Attendee Count", "Calendar", base.status, base.detail)
    return Result("calendar_attendees", "Attendee Count", "Calendar", OK,
                  "EKEvent.attendees() available when authorized")


def check_calendar_type() -> Result:
    base = check_calendar_access()
    if base.status != OK:
        return Result("calendar_type", "Meeting vs Solo", "Calendar", base.status, base.detail)
    return Result("calendar_type", "Meeting vs Solo", "Calendar", OK,
                  "Derived from attendee_count > 0")


def check_psutil_cpu() -> Result:
    try:
        import psutil
        val = psutil.cpu_percent(interval=0.1)
        return Result("system_cpu", "System CPU", "System", OK, "psutil.cpu_percent()", f"{val:.1f}%")
    except Exception as e:
        return Result("system_cpu", "System CPU", "System", FAIL, str(e))


def check_tracker_cpu() -> Result:
    try:
        import psutil
        proc = psutil.Process()
        proc.cpu_percent(interval=None)
        time.sleep(0.1)
        val = proc.cpu_percent(interval=None)
        return Result("tracker_cpu", "Tracker CPU", "System", OK, "psutil.Process().cpu_percent()", f"{val:.1f}%")
    except Exception as e:
        return Result("tracker_cpu", "Tracker CPU", "System", FAIL, str(e))


def check_tracker_memory() -> Result:
    try:
        import psutil
        mb = int(psutil.Process().memory_info().rss / 1024 / 1024)
        return Result("tracker_memory", "Tracker Memory", "System", OK, "psutil.Process().memory_info()", f"{mb} MB")
    except Exception as e:
        return Result("tracker_memory", "Tracker Memory", "System", FAIL, str(e))


def check_system_memory() -> Result:
    try:
        import psutil
        vm = psutil.virtual_memory()
        used_mb = int(vm.used / 1024 / 1024)
        return Result("system_memory", "System Memory", "System", OK, "psutil.virtual_memory()", f"{used_mb} MB used")
    except Exception as e:
        return Result("system_memory", "System Memory", "System", FAIL, str(e))


def check_battery() -> Result:
    try:
        import psutil
        batt = psutil.sensors_battery()
        if batt is None:
            return Result("battery_level", "Battery Level", "System", UNAVAILABLE,
                          "No battery detected — desktop Mac or API unsupported")
        charging = "charging" if batt.power_plugged else "on battery"
        return Result("battery_level", "Battery Level", "System", OK,
                      "psutil.sensors_battery()", f"{batt.percent:.0f}% ({charging})")
    except Exception as e:
        return Result("battery_level", "Battery Level", "System", FAIL, str(e))


def check_disk_io() -> Result:
    try:
        import psutil
        d = psutil.disk_io_counters()
        return Result("disk_io", "Disk I/O", "System", OK, "psutil.disk_io_counters()",
                      f"read={d.read_bytes//1024//1024}MB write={d.write_bytes//1024//1024}MB cumulative")
    except Exception as e:
        return Result("disk_io", "Disk I/O", "System", FAIL, str(e))


def check_network_bytes() -> Result:
    try:
        import psutil
        n = psutil.net_io_counters()
        return Result("network_bytes", "Network Bytes", "Network", OK, "psutil.net_io_counters()",
                      f"sent={n.bytes_sent//1024//1024}MB recv={n.bytes_recv//1024//1024}MB cumulative")
    except Exception as e:
        return Result("network_bytes", "Network Bytes", "Network", FAIL, str(e))


def check_vpn() -> Result:
    try:
        import psutil
        ifaces = list(psutil.net_if_stats().keys())
        vpn = any(i.startswith("utun") for i in ifaces)
        return Result("vpn_status", "VPN Status", "Network", OK,
                      "Checks for utun interfaces", f"active={vpn} interfaces={ifaces[:5]}")
    except Exception as e:
        return Result("vpn_status", "VPN Status", "Network", FAIL, str(e))


def check_wifi_signal() -> Result:
    airport = (
        "/System/Library/PrivateFrameworks/Apple80211.framework"
        "/Versions/Current/Resources/airport"
    )
    if not os.path.exists(airport):
        return Result("wifi_signal", "WiFi Signal Strength", "Network", UNAVAILABLE, "airport CLI not found")
    try:
        r = subprocess.run([airport, "-I"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if "agrCtlRSSI" in line:
                dbm = line.split(":")[1].strip()
                return Result("wifi_signal", "WiFi Signal Strength", "Network", OK,
                              "airport CLI accessible", f"{dbm} dBm")
        return Result("wifi_signal", "WiFi Signal Strength", "Network", UNAVAILABLE,
                      "airport ran but no RSSI — not connected to WiFi?")
    except Exception as e:
        return Result("wifi_signal", "WiFi Signal Strength", "Network", FAIL, str(e))


def check_audio() -> Result:
    try:
        r = subprocess.run(
            ["osascript", "-e", "output volume of (get volume settings)"],
            capture_output=True, text=True, timeout=5,
        )
        vol = int(r.stdout.strip())
        return Result("audio_volume", "Audio Volume", "System", OK, "osascript volume settings", f"volume={vol}")
    except Exception as e:
        return Result("audio_volume", "Audio Volume", "System", FAIL, str(e))


def check_brightness() -> Result:
    try:
        r = subprocess.run(
            ["ioreg", "-c", "IODisplayBrightnessControl", "-r", "-d", "1"],
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.splitlines():
            if "brightness" in line.lower() and "=" in line:
                val_str = line.split("=")[1].strip()
                val = float(val_str)
                pct = round(val * 100, 1) if val <= 1.0 else round(val, 1)
                return Result("display_brightness", "Display Brightness", "System", OK,
                              "ioreg IODisplayBrightnessControl", f"{pct}%")
        return Result("display_brightness", "Display Brightness", "System", UNAVAILABLE,
                      "ioreg ran but no brightness value found — may require SIP disabled or external display")
    except Exception as e:
        return Result("display_brightness", "Display Brightness", "System", UNAVAILABLE, str(e))


# ── Full probe list ───────────────────────────────────────────────────────────
def run_all() -> list[Result]:
    # Event-tap signals share a single probe (same permission)
    tap_ok = check_event_tap("_tap", "_", "_").status == OK

    def tap_result(sig_id, name, category) -> Result:
        if tap_ok:
            return Result(sig_id, name, category, OK, "CGEventTap active (Accessibility granted)")
        return check_event_tap(sig_id, name, category)

    return [
        # App Behavior
        check_app_switches(),
        check_app_bundle_id(),
        check_app_category(),
        # Keyboard (all require Accessibility / CGEventTap)
        tap_result("keystroke_count",   "Keystroke Count",         "Keyboard"),
        tap_result("inter_key_latency", "Inter-Key Latency",       "Keyboard"),
        tap_result("typing_speed_cpm",  "Typing Speed (CPM)",      "Keyboard"),
        tap_result("backspace_rate",    "Backspace Rate",           "Keyboard"),
        tap_result("modifier_key_freq", "Modifier Key Frequency",  "Keyboard"),
        tap_result("typing_bursts",     "Typing Burst Pauses",     "Keyboard"),
        tap_result("rhythm_variance",   "Typing Rhythm Variance",  "Keyboard"),
        # Mouse (also CGEventTap)
        check_mouse_distance(),
        tap_result("mouse_clicks",  "Mouse Clicks",       "Mouse"),
        tap_result("mouse_scroll",  "Scroll Activity",    "Mouse"),
        tap_result("mouse_idle",    "Mouse Idle Time",    "Mouse"),
        # Calendar
        check_calendar_access(),
        check_calendar_attendees(),
        check_calendar_type(),
        # System
        check_psutil_cpu(),
        check_tracker_cpu(),
        check_tracker_memory(),
        check_system_memory(),
        check_battery(),
        check_disk_io(),
        check_audio(),
        check_brightness(),
        # Network
        check_network_bytes(),
        check_vpn(),
        check_wifi_signal(),
    ]


# ── Pretty printer ────────────────────────────────────────────────────────────
def print_report(results: list[Result]):
    COLS = {
        OK:          "\033[92m",
        NO_PERM:     "\033[93m",
        UNAVAILABLE: "\033[94m",
        FAIL:        "\033[91m",
        SKIP:        "\033[90m",
    }
    RESET = "\033[0m"

    current_cat = None
    print(f"\n{'='*70}")
    print(f"  Clear Ahead — Signal Test Report    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")

    for r in results:
        if r.category != current_cat:
            current_cat = r.category
            print(f"\n  ── {r.category} {'─'*(50-len(r.category))}")

        color  = COLS.get(r.status, "")
        status = f"{color}{r.status}{RESET}"
        name   = r.name.ljust(32)
        detail = f"  [{r.detail}]" if r.detail else ""
        sample = f"  → {r.sample}" if r.sample else ""
        print(f"  {status}  {name}{detail}{sample}")

    print(f"\n{'─'*70}")
    counts = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    total = len(results)
    print(f"  Total signals: {total}")
    print(f"  {OK}:          {counts.get(OK, 0)}")
    print(f"  {NO_PERM}:  {counts.get(NO_PERM, 0)}")
    print(f"  {UNAVAILABLE}:  {counts.get(UNAVAILABLE, 0)}")
    print(f"  {FAIL}:         {counts.get(FAIL, 0)}")
    print(f"{'='*70}\n")

    pass_count = counts.get(OK, 0)
    print(f"  Coverage: {pass_count}/{total} signals active ({pass_count/total*100:.0f}%)\n")


if __name__ == "__main__":
    print("Running signal probes — this may take a few seconds…")
    results = run_all()
    print_report(results)
    # Exit with non-zero if any hard failures
    hard_fail = sum(1 for r in results if r.status == FAIL)
    sys.exit(1 if hard_fail > 0 else 0)
