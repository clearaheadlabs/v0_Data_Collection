# Clear Ahead Behavioral Tracker
**v0.1 — March 2026**

Passive macOS behavior data collector. No inference, no recommendations — pure signal capture to validate what's technically feasible to track from a personal computer.

---

## What It Does

Runs silently in the background. Captures behavioral signals from your Mac every minute/5 minutes and stores everything locally in a SQLite database. A lightweight web dashboard lets you see what's been collected.

---

## What It Records

| Signal | Detail |
|---|---|
| **App switches** | Which app is active, how long, bundle ID, category |
| **Keystroke timing** | Count, speed (CPM), avg latency, backspaces, modifier keys, burst pauses, rhythm variance — never content |
| **Mouse** | Movement distance, click count by type, scroll, idle time |
| **Calendar** | Events from iCal, duration, attendee count, meeting vs focus |
| **System** | CPU (system + tracker), RAM, battery, disk I/O, network bytes |
| **Network** | Bytes sent/received, VPN active, WiFi signal strength |
| **Audio** | Speaker volume, mute state |
| **Sessions** | Every on/off cycle logged with start, end, duration, clean vs crash |

---

## What It Does NOT Record

- Keystroke content (what you type)
- Screenshots or screen recording
- Browser history or URLs
- Email, message, or document content
- Clipboard
- Webcam or microphone audio

---

## How to Run

Double-click **`Clear Ahead Tracker.app`** — no Terminal needed.

- Menu bar shows `● CPU%` while running
- Click menu bar → **Open Dashboard** or **Quit Tracker**
- Dashboard at `http://127.0.0.1:7331`

---

## Dashboard Pages

| Page | What's there |
|---|---|
| **Today** | Summary cards, top apps, today's sessions |
| **Data Log** | Raw tables — app switches, keystrokes, calendar |
| **Sessions** | Every run with start/end/duration/status |
| **Signal Status** | Live status of all 28 signals (active / no permission / unavailable) |

---

## Database

SQLite at `data/tracker.db`. Open with **SQLite Viewer** extension in VS Code or DB Browser for SQLite.

Tables: `sessions`, `context_switches`, `keystroke_metrics`, `system_metrics`, `calendar_events`

Every row has a `session_id` — each app launch is one session.

---

## Permissions Required

| Permission | For |
|---|---|
| **Accessibility** | Keyboard timing + mouse tracking (CGEventTap) |
| **Calendar** | iCal event sync (EventKit) |

Grant in System Settings → Privacy & Security. Without them, those signals are skipped — everything else still runs.

---

## Current Signal Coverage

Run `python3 tests/test_signals.py` to see live status of all 28 signals.

- **13/28 active** without any permissions granted
- **26/28 active** once Accessibility + Calendar are granted
- **2/28 unavailable**: display brightness (private IOKit), WiFi signal (only when on WiFi)

---

## Limitations

- Requires macOS 12+
- Python 3.11+ with Anaconda (`/opt/anaconda3`)
- Display brightness not accessible without disabling SIP
- App category mapping covers ~60 common apps; unknown apps tagged `other`
- System metrics collected every 5 min (not real-time)
- No cloud sync — all data local only
