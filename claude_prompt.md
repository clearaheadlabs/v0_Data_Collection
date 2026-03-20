Build a macOS passive behavior tracker that collects behavioral signals to validate whether comprehensive passive monitoring is technically feasible.
Core Goal
Prove we can reliably capture behavioral data from a personal computer without destroying performance. No inference, no recommendations yet - just pure data collection.
What to Build
A Python-based macOS application that:

Runs continuously in background
Collects these signals:

Calendar events (from iCal via EventKit)
App switching (which app is active, when it changes)
Keystroke timing patterns (inter-key latency, typing speed - NO content)
Mouse behavior (movement, clicks, idle time)
System resource usage (CPU/RAM of tracker itself)


Stores everything locally in SQLite
Shows simple dashboard (localhost web page) displaying:

How many events captured today
Top 5 apps by usage
Context switches count
Resource usage of tracker
Export button (download CSV)


Menubar indicator showing tracker is running + current CPU/RAM usage

Technical Stack

Python 3.11+
PyObjC for macOS APIs (EventKit, NSWorkspace, Quartz)
rumps for menubar app
Flask for dashboard
sqlite3 for storage

Key Constraints

Privacy first: Never capture keystroke content, only timing
Performance target: <5% CPU, <150MB RAM
Local only: No network calls, all data stays on disk
Graceful degradation: If permission denied, continue with available signals

Database Schema (Simple)
sql-- Calendar events
CREATE TABLE calendar_events (
    id INTEGER PRIMARY KEY,
    title TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_minutes INTEGER
);

-- App switches
CREATE TABLE context_switches (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    from_app TEXT,
    to_app TEXT,
    duration_seconds INTEGER
);

-- Keystroke metrics (aggregated per minute)
CREATE TABLE keystroke_metrics (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    keystroke_count INTEGER,
    avg_latency_ms REAL,
    backspace_count INTEGER
);

-- System metrics (every 5 minutes)
CREATE TABLE system_metrics (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    cpu_percent REAL,
    memory_mb INTEGER
);
File Structure
clear-ahead-tracker/
├── tracker.py          # Main daemon
├── monitors/
│   ├── calendar.py     # EventKit calendar sync
│   ├── apps.py         # NSWorkspace app tracking
│   ├── input.py        # CGEvent keystroke/mouse monitoring
├── storage.py          # SQLite wrapper
├── dashboard.py        # Flask web UI
├── menubar.py          # Status indicator
└── data/
    └── tracker.db
MVP Success Criteria
✅ Runs for 8 hours without crashing
✅ Captures calendar events from iCal
✅ Tracks app switches accurately
✅ Records keystroke timing (not content)
✅ Uses <5% CPU, <150MB RAM
✅ Dashboard shows collected data
✅ Can export to CSV
What NOT to Build
❌ No recommendations yet
❌ No inference/ML models
❌ No personalization
❌ No cloud sync
❌ No fancy UI - simple is fine
First Steps

Set up Python project with dependencies
Build calendar sync (EventKit API)
Build app monitor (NSWorkspace)
Build input monitor (CGEvent for timing only)
Wire everything together in main daemon
Add simple Flask dashboard
Test: run for 30 minutes, check data collection works

Testing
After building, run the tracker for 30 minutes and verify:

SQLite database created with data
Calendar events visible in dashboard
App switches logged
Resource usage acceptable
No crashes or permission errors

Permissions Needed
macOS will prompt for:

Calendar access (EventKit)
Accessibility access (for CGEvent monitoring)

Handle gracefully if denied - continue with available signals.

Start by building the calendar sync module, then app monitoring, then tie it together.