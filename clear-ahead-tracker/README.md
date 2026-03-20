# Clear Ahead Behavioral Tracker

macOS passive behavior data collector. No content captured — timing and metadata only.

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
# Full app with menubar indicator
python tracker.py

# Headless (no menubar, good for testing)
python tracker.py --no-menubar
```

## Dashboard

Open http://127.0.0.1:7331 in any browser.

- Refreshes every 30 seconds
- Shows today's counts: calendar events, context switches, keystrokes
- Live CPU/RAM usage of the tracker itself
- Top 5 apps by switch count
- **Export All Data (CSV)** button downloads everything

## Permissions Required

macOS will prompt for these the first time:

| Permission | Used for |
|---|---|
| Calendar | EventKit reads iCal events |
| Accessibility | CGEventTap for keystroke timing |

If denied, that monitor silently skips — the rest keeps running.

## Privacy

- **Keystrokes**: only count and inter-key latency per minute. Key identity/content is never stored.
- **Mouse**: last-active timestamp only (idle detection).
- **Apps**: app name only (via NSWorkspace.frontmostApplication).
- **Calendar**: event title, start/end times, duration.
- **No network calls**: all data stays in `data/tracker.db`.

## Database

SQLite at `data/tracker.db`. Tables:

- `calendar_events` — synced from iCal (±1 day past, +7 days future)
- `context_switches` — every app switch with duration
- `keystroke_metrics` — per-minute bucket (count, avg latency ms, backspace count)
- `system_metrics` — tracker CPU/RAM every 5 minutes

## Performance Targets

- CPU: < 5%
- RAM: < 150 MB
- App polling: 1-second resolution
- Keystroke flush: every 60 seconds
