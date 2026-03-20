# Clear Ahead Labs - MVP Build Instructions
## Passive Behavior Data Collection System for macOS

**Goal:** Validate that passive work behavior tracking is technically feasible, reliable, and performant on macOS. Capture maximum behavioral signals to build dataset for future inference models.

**Time Budget:** 2 hours (focus on breadth of signal capture, not polish)

**Core Question Being Answered:**  
Can we reliably capture comprehensive passive behavior data from a personal computer without destroying performance or requiring invasive permissions?

---

## Part 1: What Signals We're Capturing

### Tier 1: Definitely Achievable (Core MVP)

**Calendar Events** (via EventKit API)
- Event title, start time, end time, duration
- Event type (meeting vs focus block vs tentative)
- Attendee count (indicates meeting size)
- Back-to-back patterns (gap between events)
- Calendar source (work vs personal if multiple calendars)

**Application Usage** (via NSWorkspace)
- Active application name
- Application switch events (timestamp of each switch)
- Time spent per application
- Application category inference (communication vs development vs browser vs other)
- Window count per app (if available)

**Context Switching Metrics** (derived from app usage)
- Number of app switches per hour
- Average time in app before switching
- Switch patterns (rapid switching vs sustained focus)
- Return-to-app frequency (switching back and forth between same apps)

**System Idle Detection** (via CGEventSource)
- Keyboard idle time (time since last keystroke)
- Mouse idle time (time since last mouse movement)
- Combined idle (indicates true AFK vs active)
- Idle events >2min, >5min, >15min (different thresholds)

**Keystroke Timing Patterns** (via CGEvent tap - NO CONTENT)
- Inter-key latency (time between keystrokes)
- Typing speed (keys per minute in active windows)
- Backspace rate (correction frequency without knowing what was typed)
- Pause patterns (gaps >2 seconds between typing bursts)
- **CRITICAL:** Never capture keystroke content, only timing metadata

**Mouse Behavior** (via CGEvent monitoring)
- Mouse movement distance per minute
- Movement velocity (fast jerky vs smooth slow)
- Click frequency
- Scroll events (scroll speed, direction changes)
- Mouse idle duration between movements

**System Resource Usage** (via ProcessInfo / Activity Monitor APIs)
- CPU usage of tracker process itself
- Memory footprint of tracker
- Battery impact (if laptop)
- System-wide CPU/memory for context (is machine under load?)

---

### Tier 2: Stretch Goals (If Time Permits)

**Window Title Tracking** (requires accessibility permissions)
- Active window title (might reveal document names, web page titles)
- Could infer context (working on "budget_2025.xlsx" vs "Twitter - Chrome")
- Privacy risk: might reveal sensitive content in titles
- **Decision:** Include but make optional, default OFF

**Network Activity** (System extension required - probably skip for MVP)
- Bytes sent/received
- Active network connections
- Could indicate video calls, large downloads, etc.
- **Decision:** Skip for 2-hour MVP, too complex

**Screen Brightness / Volume** (as fatigue proxy)
- Screen brightness changes might correlate with eye strain
- Volume adjustments might indicate meeting participation
- **Decision:** Nice-to-have, low priority

---

### Tier 3: Explicitly Excluded (Privacy Red Lines)

❌ **Keystroke content** - Never capture what is typed  
❌ **Screenshots** - No visual recording  
❌ **Screen recording** - No video capture  
❌ **Webcam access** - No camera monitoring  
❌ **Microphone recording** - No audio capture  
❌ **Clipboard content** - No copy/paste tracking  
❌ **Browser history** - No URL tracking (unless from window titles, which is optional)  
❌ **Document content** - Never read file contents  
❌ **Email/message content** - Never read communications  

**Why these are excluded:**  
These cross from "behavioral signals" to "surveillance." The goal is measuring cognitive load, not monitoring work output or personal activity.

---

## Part 2: Technical Architecture

### Core Components

**1. Background Daemon (Swift/Python)**
- Runs continuously when user is logged in
- Registers for NSWorkspace notifications
- Sets up CGEvent taps for keystroke/mouse monitoring
- Polls calendar API every 5 minutes
- Writes all events to local SQLite database
- **NO network access** - all data stays local

**2. Data Storage (SQLite)**
```sql
-- Schema design

CREATE TABLE calendar_events (
    id INTEGER PRIMARY KEY,
    event_id TEXT,
    title TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_minutes INTEGER,
    attendee_count INTEGER,
    calendar_source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE app_usage (
    id INTEGER PRIMARY KEY,
    app_name TEXT,
    app_bundle_id TEXT,
    window_title TEXT,  -- optional, privacy-sensitive
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    duration_seconds INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE keystroke_metrics (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    inter_key_latency_ms INTEGER,  -- time since last keystroke
    typing_speed_kpm INTEGER,       -- keys per minute (5min rolling avg)
    backspace_count INTEGER,        -- in last 5 min
    active_app TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE mouse_metrics (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    movement_distance_pixels INTEGER,  -- in last minute
    click_count INTEGER,                -- in last minute
    scroll_events INTEGER,              -- in last minute
    idle_duration_seconds INTEGER,      -- time since last movement
    active_app TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE context_switches (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    from_app TEXT,
    to_app TEXT,
    time_in_previous_app_seconds INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE system_metrics (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    tracker_cpu_percent REAL,
    tracker_memory_mb INTEGER,
    system_cpu_percent REAL,
    system_memory_available_mb INTEGER,
    battery_level_percent INTEGER,  -- if laptop
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE idle_events (
    id INTEGER PRIMARY KEY,
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    duration_seconds INTEGER,
    idle_type TEXT,  -- 'keyboard', 'mouse', 'combined'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**3. Status Widget (SwiftUI Menubar App)**
- Shows green/red indicator (tracker running or not)
- Displays current resource usage (CPU %, Memory MB)
- Quick stats: "Captured 47 events today"
- Click to open detailed dashboard
- Manual start/stop control

**4. Dashboard View (Simple HTML + JavaScript or SwiftUI)**
- Summary view showing data collected today:
  - Calendar events timeline
  - Top 5 apps by time spent
  - Context switches per hour (chart)
  - Typing activity heatmap (when you were typing)
  - Idle time distribution
  - Resource usage over time
- Raw data export button (CSV/JSON)
- Date range selector to view historical data

---

## Part 3: Implementation Approach

### Option A: Swift + SwiftUI (Native macOS)
**Pros:**
- Best performance, native APIs
- Proper menubar integration
- Can request permissions properly
- Most reliable for long-term background running

**Cons:**
- Requires Xcode, Swift knowledge
- More complex than Python
- 2 hours might be tight for full implementation

**Recommended Stack:**
- Swift for daemon (EventKit, NSWorkspace, CGEvent)
- SwiftUI for menubar widget
- SQLite via SQLite.swift library
- SwiftUI for dashboard (or export to web view)

---

### Option B: Python (Faster to Prototype)
**Pros:**
- Faster to write
- Easy data processing
- Can use existing libraries
- Good for 2-hour MVP

**Cons:**
- Background running is clunkier
- Permissions might be trickier
- Less native feel

**Recommended Stack:**
- Python 3.11+
- `PyObjC` for macOS APIs (NSWorkspace, EventKit)
- `Quartz` for CGEvent taps
- `sqlite3` for storage
- `rumps` for menubar icon
- Flask for dashboard (local web server)

---

### Recommendation for 2-Hour MVP: **Python**

Prioritize proving data collection works over polish. Python lets you move fastest.

---

## Part 4: Build Steps (2-Hour Timeline)

### Phase 1: Setup & Permissions (15 minutes)

**Install dependencies:**
```bash
pip install pyobjc-framework-Cocoa
pip install pyobjc-framework-EventKit
pip install pyobjc-framework-Quartz
pip install rumps  # menubar app
pip install flask  # dashboard
```

**Request necessary permissions:**
macOS will prompt for:
- ✅ Calendar access (EventKit)
- ✅ Accessibility access (for CGEvent tap)
- ✅ Screen Recording permission (might be needed for window titles - make optional)

**Create basic project structure:**
```
clear-ahead-tracker/
├── tracker.py          # Main daemon
├── calendar_sync.py    # EventKit calendar reading
├── app_monitor.py      # NSWorkspace app tracking
├── input_monitor.py    # CGEvent keystroke/mouse tracking
├── storage.py          # SQLite wrapper
├── menubar.py          # Status widget
├── dashboard.py        # Flask web UI
├── requirements.txt
└── data/
    └── tracker.db      # SQLite database
```

---

### Phase 2: Calendar Data Collection (20 minutes)

**Goal:** Pull all calendar events from iCal/Calendar.app

**Code outline (calendar_sync.py):**
```python
from EventKit import EKEventStore, EKEntityTypeEvent
from datetime import datetime, timedelta

def fetch_calendar_events(days_back=1, days_forward=1):
    """
    Fetch calendar events from macOS Calendar.app
    """
    store = EKEventStore.alloc().init()
    
    # Request access (will prompt user first time)
    def access_granted(granted, error):
        if not granted:
            print("Calendar access denied!")
            return
    
    store.requestAccessToEntityType_completion_(
        EKEntityTypeEvent, 
        access_granted
    )
    
    # Define date range
    start_date = datetime.now() - timedelta(days=days_back)
    end_date = datetime.now() + timedelta(days=days_forward)
    
    # Fetch events
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        start_date, end_date, None
    )
    events = store.eventsMatchingPredicate_(predicate)
    
    # Extract data
    event_data = []
    for event in events:
        event_data.append({
            'event_id': event.eventIdentifier(),
            'title': event.title(),
            'start': event.startDate(),
            'end': event.endDate(),
            'duration_minutes': (event.endDate() - event.startDate()).total_seconds() / 60,
            'attendees': len(event.attendees()) if event.attendees() else 0,
            'calendar': event.calendar().title()
        })
    
    return event_data
```

**Test:** Run this, print events, confirm you can read your calendar.

---

### Phase 3: Application Tracking (25 minutes)

**Goal:** Track which app is active and when it changes

**Code outline (app_monitor.py):**
```python
from AppKit import NSWorkspace, NSWorkspaceDidActivateApplicationNotification
from Foundation import NSNotificationCenter
import time

class AppMonitor:
    def __init__(self, callback):
        self.callback = callback
        self.current_app = None
        self.app_start_time = time.time()
        
    def start(self):
        """
        Register for app activation notifications
        """
        workspace = NSWorkspace.sharedWorkspace()
        nc = NSWorkspaceNotificationCenter.defaultCenter()
        
        nc.addObserver_selector_name_object_(
            self,
            'app_switched:',
            NSWorkspaceDidActivateApplicationNotification,
            None
        )
        
        # Get initial active app
        active_app = workspace.frontmostApplication()
        self.current_app = active_app.localizedName()
        self.app_start_time = time.time()
        
    def app_switched_(self, notification):
        """
        Called when active app changes
        """
        new_app = notification.userInfo()['NSWorkspaceApplicationKey']
        app_name = new_app.localizedName()
        bundle_id = new_app.bundleIdentifier()
        
        # Calculate time in previous app
        now = time.time()
        duration = now - self.app_start_time
        
        # Record switch event
        self.callback({
            'from_app': self.current_app,
            'to_app': app_name,
            'duration_in_previous': duration,
            'timestamp': now
        })
        
        # Update state
        self.current_app = app_name
        self.app_start_time = now
```

**Test:** Run this, switch between apps, confirm you see switch events logged.

---

### Phase 4: Keystroke & Mouse Monitoring (30 minutes)

**Goal:** Capture timing patterns without content

**Code outline (input_monitor.py):**
```python
from Quartz import (
    CGEventTapCreate, kCGHeadInsertEventTap, kCGEventTapOptionDefault,
    CGEventMaskBit, kCGEventKeyDown, kCGEventMouseMoved, kCGEventLeftMouseDown,
    CFRunLoopGetCurrent, CFRunLoopAddSource, kCFRunLoopDefaultMode,
    CGEventTapEnable, CFMachPortCreateRunLoopSource
)
import time

class InputMonitor:
    def __init__(self):
        self.last_keystroke_time = None
        self.keystroke_count = 0
        self.backspace_count = 0
        self.last_mouse_time = None
        self.mouse_movement_distance = 0
        self.last_mouse_pos = None
        
    def keystroke_callback(self, proxy, event_type, event, refcon):
        """
        Called on every keystroke (timing only, NO content)
        """
        now = time.time()
        
        # Calculate inter-key latency
        if self.last_keystroke_time:
            latency_ms = (now - self.last_keystroke_time) * 1000
            # Store this
        
        self.keystroke_count += 1
        self.last_keystroke_time = now
        
        # Detect backspace (keycode 51 on macOS)
        keycode = event.getIntegerValueField_(kCGKeyboardEventKeycode)
        if keycode == 51:
            self.backspace_count += 1
        
        return event  # Pass through, don't block
    
    def mouse_callback(self, proxy, event_type, event, refcon):
        """
        Called on mouse events
        """
        now = time.time()
        
        if event_type == kCGEventMouseMoved:
            pos = event.locationInWindow()
            
            if self.last_mouse_pos:
                # Calculate distance moved
                dx = pos.x - self.last_mouse_pos.x
                dy = pos.y - self.last_mouse_pos.y
                distance = (dx**2 + dy**2)**0.5
                self.mouse_movement_distance += distance
            
            self.last_mouse_pos = pos
            self.last_mouse_time = now
        
        return event
    
    def start(self):
        """
        Create event tap and add to run loop
        """
        # Keystroke tap
        key_tap = CGEventTapCreate(
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            CGEventMaskBit(kCGEventKeyDown),
            self.keystroke_callback,
            None
        )
        
        # Mouse tap
        mouse_tap = CGEventTapCreate(
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            CGEventMaskBit(kCGEventMouseMoved) | CGEventMaskBit(kCGEventLeftMouseDown),
            self.mouse_callback,
            None
        )
        
        # Add to run loop
        run_loop_source_key = CFMachPortCreateRunLoopSource(None, key_tap, 0)
        run_loop_source_mouse = CFMachPortCreateRunLoopSource(None, mouse_tap, 0)
        
        loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(loop, run_loop_source_key, kCFRunLoopDefaultMode)
        CFRunLoopAddSource(loop, run_loop_source_mouse, kCFRunLoopDefaultMode)
        
        CGEventTapEnable(key_tap, True)
        CGEventTapEnable(mouse_tap, True)
```

**Test:** Run this, type and move mouse, confirm events are captured.

**CRITICAL:** This requires Accessibility permissions. macOS will prompt.

---

### Phase 5: Data Storage Layer (15 minutes)

**Goal:** Save all collected data to SQLite

**Code outline (storage.py):**
```python
import sqlite3
from datetime import datetime

class DataStore:
    def __init__(self, db_path='data/tracker.db'):
        self.conn = sqlite3.connect(db_path)
        self.create_tables()
    
    def create_tables(self):
        """
        Create all tables from schema
        """
        cursor = self.conn.cursor()
        
        # Calendar events table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT,
                title TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                duration_minutes INTEGER,
                attendee_count INTEGER,
                calendar_source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # App usage table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS app_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name TEXT,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                duration_seconds INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Context switches
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS context_switches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP,
                from_app TEXT,
                to_app TEXT,
                time_in_previous_app_seconds INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Keystroke metrics (aggregated per minute)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS keystroke_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP,
                keystroke_count INTEGER,
                backspace_count INTEGER,
                avg_inter_key_latency_ms REAL,
                active_app TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Mouse metrics (aggregated per minute)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mouse_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP,
                movement_distance_pixels INTEGER,
                click_count INTEGER,
                active_app TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # System metrics (every 5 minutes)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP,
                tracker_cpu_percent REAL,
                tracker_memory_mb INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    def insert_calendar_event(self, event_data):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO calendar_events 
            (event_id, title, start_time, end_time, duration_minutes, attendee_count, calendar_source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            event_data['event_id'],
            event_data['title'],
            event_data['start'],
            event_data['end'],
            event_data['duration_minutes'],
            event_data['attendees'],
            event_data['calendar']
        ))
        self.conn.commit()
    
    def insert_context_switch(self, switch_data):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO context_switches 
            (timestamp, from_app, to_app, time_in_previous_app_seconds)
            VALUES (?, ?, ?, ?)
        ''', (
            datetime.now(),
            switch_data['from_app'],
            switch_data['to_app'],
            switch_data['duration_in_previous']
        ))
        self.conn.commit()
    
    # Add similar methods for other tables
    
    def get_summary_today(self):
        """
        Get summary stats for today
        """
        cursor = self.conn.cursor()
        today = datetime.now().date()
        
        # Count events
        cursor.execute('''
            SELECT COUNT(*) FROM calendar_events 
            WHERE DATE(start_time) = ?
        ''', (today,))
        event_count = cursor.fetchone()[0]
        
        # Count switches
        cursor.execute('''
            SELECT COUNT(*) FROM context_switches 
            WHERE DATE(timestamp) = ?
        ''', (today,))
        switch_count = cursor.fetchone()[0]
        
        # Top apps
        cursor.execute('''
            SELECT to_app, COUNT(*) as switches
            FROM context_switches 
            WHERE DATE(timestamp) = ?
            GROUP BY to_app
            ORDER BY switches DESC
            LIMIT 5
        ''', (today,))
        top_apps = cursor.fetchall()
        
        return {
            'events': event_count,
            'switches': switch_count,
            'top_apps': top_apps
        }
```

---

### Phase 6: Main Tracker Daemon (20 minutes)

**Goal:** Tie everything together in one running process

**Code outline (tracker.py):**
```python
import time
import threading
from calendar_sync import fetch_calendar_events
from app_monitor import AppMonitor
from input_monitor import InputMonitor
from storage import DataStore
import psutil
import os

class ClearAheadTracker:
    def __init__(self):
        self.db = DataStore()
        self.running = False
        
        # Monitors
        self.app_monitor = AppMonitor(self.on_app_switch)
        self.input_monitor = InputMonitor()
        
    def on_app_switch(self, switch_data):
        """
        Callback when app switches
        """
        print(f"App switch: {switch_data['from_app']} -> {switch_data['to_app']}")
        self.db.insert_context_switch(switch_data)
    
    def sync_calendar(self):
        """
        Sync calendar events (run every 5 minutes)
        """
        print("Syncing calendar...")
        events = fetch_calendar_events(days_back=1, days_forward=7)
        for event in events:
            self.db.insert_calendar_event(event)
        print(f"Synced {len(events)} events")
    
    def record_system_metrics(self):
        """
        Record tracker resource usage
        """
        process = psutil.Process(os.getpid())
        cpu_percent = process.cpu_percent(interval=1)
        memory_mb = process.memory_info().rss / 1024 / 1024
        
        print(f"Tracker using: {cpu_percent}% CPU, {memory_mb:.1f}MB RAM")
        
        # Save to DB
        # self.db.insert_system_metrics(...)
    
    def aggregate_input_metrics(self):
        """
        Every minute, aggregate keystroke/mouse data and save
        """
        # Get current metrics from input_monitor
        keystroke_count = self.input_monitor.keystroke_count
        backspace_count = self.input_monitor.backspace_count
        mouse_distance = self.input_monitor.mouse_movement_distance
        
        # Save to DB
        # self.db.insert_keystroke_metrics(...)
        # self.db.insert_mouse_metrics(...)
        
        # Reset counters
        self.input_monitor.keystroke_count = 0
        self.input_monitor.backspace_count = 0
        self.input_monitor.mouse_movement_distance = 0
    
    def start(self):
        """
        Start all monitoring
        """
        print("Starting Clear Ahead Tracker...")
        self.running = True
        
        # Start monitors
        self.app_monitor.start()
        self.input_monitor.start()
        
        # Initial calendar sync
        self.sync_calendar()
        
        # Background threads for periodic tasks
        def calendar_sync_loop():
            while self.running:
                time.sleep(300)  # Every 5 minutes
                self.sync_calendar()
        
        def metrics_loop():
            while self.running:
                time.sleep(60)  # Every minute
                self.aggregate_input_metrics()
                self.record_system_metrics()
        
        threading.Thread(target=calendar_sync_loop, daemon=True).start()
        threading.Thread(target=metrics_loop, daemon=True).start()
        
        print("Tracker running. Press Ctrl+C to stop.")
        
        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping tracker...")
            self.running = False

if __name__ == '__main__':
    tracker = ClearAheadTracker()
    tracker.start()
```

---

### Phase 7: Simple Dashboard (15 minutes)

**Goal:** View collected data in browser

**Code outline (dashboard.py):**
```python
from flask import Flask, render_template, jsonify
from storage import DataStore

app = Flask(__name__)
db = DataStore()

@app.route('/')
def index():
    """
    Main dashboard page
    """
    summary = db.get_summary_today()
    return render_template('dashboard.html', summary=summary)

@app.route('/api/summary')
def api_summary():
    """
    JSON API for summary data
    """
    return jsonify(db.get_summary_today())

@app.route('/api/events')
def api_events():
    """
    Get all calendar events
    """
    # Query DB for events
    # Return as JSON
    pass

@app.route('/api/switches')
def api_switches():
    """
    Get context switch timeline
    """
    pass

if __name__ == '__main__':
    app.run(debug=True, port=5000)
```

**HTML Template (templates/dashboard.html):**
```html
<!DOCTYPE html>
<html>
<head>
    <title>Clear Ahead Tracker Dashboard</title>
    <style>
        body { font-family: -apple-system, sans-serif; padding: 20px; }
        .stat { padding: 20px; background: #f0f0f0; margin: 10px; border-radius: 8px; }
        .stat h3 { margin: 0 0 10px 0; }
        .stat p { margin: 0; font-size: 24px; font-weight: bold; }
    </style>
</head>
<body>
    <h1>Clear Ahead Tracker Dashboard</h1>
    <p>Data collected today:</p>
    
    <div class="stat">
        <h3>Calendar Events</h3>
        <p>{{ summary.events }}</p>
    </div>
    
    <div class="stat">
        <h3>App Switches</h3>
        <p>{{ summary.switches }}</p>
    </div>
    
    <div class="stat">
        <h3>Top Apps</h3>
        <ul>
        {% for app, count in summary.top_apps %}
            <li>{{ app }}: {{ count }} switches</li>
        {% endfor %}
        </ul>
    </div>
    
    <div class="stat">
        <h3>Raw Data Export</h3>
        <button onclick="exportData()">Download CSV</button>
    </div>
    
    <script>
        // Auto-refresh every 10 seconds
        setInterval(() => location.reload(), 10000);
        
        function exportData() {
            window.location.href = '/api/export';
        }
    </script>
</body>
</html>
```

---

### Phase 8: Menubar Status Widget (15 minutes)

**Code outline (menubar.py):**
```python
import rumps
import subprocess

class TrackerMenuBar(rumps.App):
    def __init__(self):
        super(TrackerMenuBar, self).__init__("Clear Ahead", "🟢")
        self.menu = [
            "Status: Running",
            "CPU: 0.0%",
            "Memory: 0 MB",
            None,  # Separator
            "Open Dashboard",
            "Stop Tracking"
        ]
    
    def update_status(self, cpu, memory):
        """
        Update menu items with current stats
        """
        self.menu["CPU: 0.0%"].title = f"CPU: {cpu}%"
        self.menu["Memory: 0 MB"].title = f"Memory: {memory}MB"
    
    @rumps.clicked("Open Dashboard")
    def open_dashboard(self, _):
        """
        Open dashboard in browser
        """
        subprocess.call(['open', 'http://localhost:5000'])
    
    @rumps.clicked("Stop Tracking")
    def stop_tracking(self, _):
        """
        Stop the tracker
        """
        rumps.quit_application()

if __name__ == '__main__':
    app = TrackerMenuBar()
    app.run()
```

---

## Part 5: Testing Protocol

### Immediate Tests (During Build)

1. **Calendar Access:**
   - Run `python calendar_sync.py`
   - Confirm: Can read your events?
   - Expected: List of your actual calendar events printed

2. **App Tracking:**
   - Run `python app_monitor.py`
   - Switch between apps
   - Confirm: See switch events logged?

3. **Keystroke/Mouse:**
   - Run `python input_monitor.py`
   - Type and move mouse
   - Confirm: See timing events (but NO content)?
   - Expected: Inter-key latency values, mouse movement distance

4. **Database:**
   - Run tracker for 5 minutes
   - Check `data/tracker.db` exists
   - Query: `sqlite3 data/tracker.db "SELECT COUNT(*) FROM context_switches;"`
   - Expected: Non-zero count

5. **Dashboard:**
   - Start tracker
   - Open http://localhost:5000
   - Confirm: See today's data?

6. **Resource Usage:**
   - Run tracker for 30 minutes
   - Check Activity Monitor
   - Confirm: <5% CPU, <100MB RAM?

---

### Day-Long Validation Test

**After MVP is built, run for full workday:**

1. Start tracker at 9am
2. Work normally all day
3. Check dashboard at 5pm

**Questions to answer:**
- ✅ Did it run without crashing?
- ✅ How much CPU/RAM did it use?
- ✅ How many events captured? (expect 100-500 context switches, 5-10 calendar events, 1000s of keystrokes)
- ✅ Any data gaps? (times when nothing was captured)
- ✅ Can you export clean CSV?

**Success criteria:**
- Tracker runs for 8 hours without crashing
- Uses <5% CPU average, <150MB RAM
- Captures all expected events
- Data is queryable and exportable

**Failure modes to watch for:**
- Tracker crashes after X hours
- Memory leak (RAM grows over time)
- Missed events (gaps in timeline)
- Database corruption
- Permissions revoked mid-day

---

## Part 6: Data Export & Analysis

### Export Formats

**CSV Export (for Excel/Python analysis):**
```python
def export_to_csv():
    """
    Export all tables to CSV files
    """
    import csv
    
    # Export calendar events
    cursor.execute('SELECT * FROM calendar_events')
    with open('export_calendar.csv', 'w') as f:
        writer = csv.writer(f)
        writer.writerow(['id', 'event_id', 'title', 'start', 'end', 'duration', 'attendees'])
        writer.writerows(cursor.fetchall())
    
    # Export context switches
    cursor.execute('SELECT * FROM context_switches')
    with open('export_switches.csv', 'w') as f:
        writer = csv.writer(f)
        writer.writerow(['id', 'timestamp', 'from_app', 'to_app', 'duration'])
        writer.writerows(cursor.fetchall())
    
    # etc for other tables
```

**JSON Export (for web/API consumption):**
```python
def export_to_json():
    """
    Export all data as JSON
    """
    import json
    
    data = {
        'calendar_events': [],
        'context_switches': [],
        'keystroke_metrics': [],
        # etc
    }
    
    # Query each table, convert to dict
    # ...
    
    with open('export_data.json', 'w') as f:
        json.dump(data, f, indent=2)
```

### Initial Analysis Questions

**After collecting 1 week of data, answer:**

1. **Signal Quality:**
   - How noisy is keystroke timing data?
   - Does app switching correlate with calendar events?
   - Can you see patterns (morning focus, afternoon meetings)?

2. **Inference Viability:**
   - Can you visually identify "high load" vs "low load" periods?
   - Do context switches spike during stressful days?
   - Does typing speed drop in afternoon?

3. **Missing Signals:**
   - What behavioral signals do you wish you had?
   - What's noisier than expected?
   - What's more reliable than expected?

4. **Privacy Validation:**
   - Review actual data collected
   - Confirm: No sensitive content leaked?
   - Comfortable sharing this dataset?

---

## Part 7: Known Limitations & Gotchas

### macOS Permissions Hell

**Problem:** macOS is increasingly restrictive about what apps can monitor

**Required permissions:**
- ✅ Calendar (EventKit) - Will prompt on first run
- ⚠️ Accessibility (for CGEvent tap) - Must enable in System Preferences manually
- ⚠️ Screen Recording (for window titles) - Optional but helpful

**How to grant:**
1. Run tracker
2. macOS will prompt for Calendar
3. For Accessibility: System Preferences > Security & Privacy > Privacy > Accessibility
4. Add Terminal (if running from terminal) or your app

**If permissions denied:**
- Tracker won't be able to monitor keystrokes/mouse
- Will still get app switches and calendar
- Graceful degradation: log warning, continue without that signal

---

### Background Running Challenges

**Problem:** macOS kills background processes aggressively

**Solutions:**
1. Use `launchd` to run as daemon (keeps it alive)
2. Create a `.plist` file in `~/Library/LaunchAgents/`
3. Ensures tracker restarts if it crashes

**Example launchd plist:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.clearahead.tracker</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/path/to/tracker.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

---

### Performance Considerations

**Problem:** CGEvent taps are called on EVERY keystroke/mouse event (hundreds per minute)

**Solutions:**
- Aggregate data before saving (don't write to DB on every keystroke)
- Buffer events in memory, flush every 60 seconds
- Use batch inserts instead of individual INSERTs

**Example buffering:**
```python
class InputMonitor:
    def __init__(self):
        self.keystroke_buffer = []
        self.buffer_size = 100
        
    def keystroke_callback(self, event):
        self.keystroke_buffer.append({
            'timestamp': time.time(),
            'latency': calculate_latency()
        })
        
        # Flush buffer when full
        if len(self.keystroke_buffer) >= self.buffer_size:
            self.flush_buffer()
    
    def flush_buffer(self):
        # Batch insert to DB
        db.insert_many(self.keystroke_buffer)
        self.keystroke_buffer = []
```

---

### Data Volume Estimates

**Expected data generated per day:**

- Calendar events: ~10 events × 200 bytes = 2KB
- App switches: ~200 switches × 150 bytes = 30KB
- Keystroke metrics (per-minute aggregates): ~480 records × 100 bytes = 48KB
- Mouse metrics: ~480 records × 100 bytes = 48KB
- System metrics: ~100 records × 50 bytes = 5KB

**Total per day: ~133KB**  
**Total per month: ~4MB**  
**Total per year: ~48MB**

**This is tiny.** Storage is not a concern.

---

## Part 8: What This MVP Proves

### Primary Validation Questions

**✅ Can we reliably capture passive behavioral signals?**
- If tracker runs for 8 hours without crashing: YES
- If data has large gaps or missing events: NO

**✅ How many distinct signals can we collect?**
- Count: Calendar events, app switches, keystroke timing, mouse behavior, idle time
- Target: 5+ distinct signal types
- Stretch: 8+ signal types

**✅ What's the performance cost?**
- If <5% CPU, <150MB RAM: ACCEPTABLE
- If >10% CPU or >300MB RAM: PROBLEMATIC

**✅ Is the data actually useful?**
- Can you visually identify patterns?
- Does it correlate with your subjective experience?
- Could you build an inference model from this?

---

### Secondary Questions (Answered Through Use)

**Privacy architecture:**
- Review actual collected data
- Confirm no sensitive content leaked
- Feel comfortable with what's captured?

**Missing signals:**
- What do you wish you had?
- What's noisier than expected?
- What's more reliable than expected?

**User experience:**
- Is menubar status useful?
- Would you notice if tracker stopped?
- Does dashboard give you insights?

---

## Part 9: Next Steps After MVP

### If Validation Succeeds

**Week 2: Build Inference Layer**
- Simple rule-based cognitive load classifier
- Train on your own data (supervised learning)
- Test: Does inferred load match subjective experience?

**Week 3: Generate First Recommendation**
- "Your context switching is 2x normal — block 2-hour focus window tomorrow 9-11am"
- Test: Do you act on it? Does it help?

**Week 4: Expand Beta**
- Get 5 friends to run tracker
- Collect diverse dataset
- Validate: Signals generalize across people?

---

### If Validation Reveals Blockers

**Blocker 1: Performance too high**
→ Optimize: Reduce polling frequency, batch DB writes, profile code

**Blocker 2: Data is too noisy**
→ Refine: Add smoothing, filter outliers, aggregate differently

**Blocker 3: Missing critical signals**
→ Expand: Research what else is measurable, request additional permissions

**Blocker 4: Permissions barriers too high**
→ Pivot: Focus only on signals that don't require scary permissions (calendar + app switching only)

---

## Part 10: Development Checklist

### Pre-Build

- [ ] Install Python 3.11+
- [ ] Install dependencies (`pip install -r requirements.txt`)
- [ ] Create project directory structure
- [ ] Grant necessary macOS permissions

### Phase 1: Calendar (20 min)

- [ ] Implement `calendar_sync.py`
- [ ] Test: Can read your calendar events
- [ ] Save events to database
- [ ] Verify data in SQLite

### Phase 2: App Tracking (25 min)

- [ ] Implement `app_monitor.py`
- [ ] Test: See app switch events logged
- [ ] Save switches to database
- [ ] Verify context switch count

### Phase 3: Input Monitoring (30 min)

- [ ] Implement `input_monitor.py` (keystrokes)
- [ ] Implement mouse tracking
- [ ] Test: Timing data captured (no content)
- [ ] Aggregate per-minute, save to DB

### Phase 4: Storage (15 min)

- [ ] Implement `storage.py` with all tables
- [ ] Test: Insert sample data
- [ ] Test: Query data back
- [ ] Verify schema is correct

### Phase 5: Main Tracker (20 min)

- [ ] Implement `tracker.py` daemon
- [ ] Wire up all monitors
- [ ] Add periodic tasks (calendar sync, metrics)
- [ ] Test: Run for 10 minutes, no crashes

### Phase 6: Dashboard (15 min)

- [ ] Implement Flask app
- [ ] Create HTML template
- [ ] Add API endpoints
- [ ] Test: View data in browser

### Phase 7: Menubar Widget (15 min)

- [ ] Implement `menubar.py`
- [ ] Show running status
- [ ] Display CPU/RAM usage
- [ ] Add "Open Dashboard" button

### Phase 8: Testing (20 min)

- [ ] Run tracker for 30 minutes
- [ ] Check all signals being captured
- [ ] Verify database has data
- [ ] Check resource usage acceptable
- [ ] Export data to CSV

---

## Appendix: Full Signal Inventory

### Signals We're Capturing

| Signal Category | Specific Metrics | Capture Method | Privacy Level |
|----------------|------------------|----------------|---------------|
| **Calendar** | Event title, time, duration, attendees | EventKit API | Medium (titles might be sensitive) |
| **App Usage** | Active app, switch timestamp | NSWorkspace | Low (just app names) |
| **Context Switching** | Switch frequency, dwell time | Derived from app usage | Low |
| **Keystroke Timing** | Inter-key latency, typing speed, backspace rate | CGEvent tap (timing only) | Low (no content) |
| **Mouse Behavior** | Movement distance, click frequency, idle time | CGEvent monitoring | Low |
| **System Load** | Tracker CPU/RAM usage | Process API | Low |
| **Idle Time** | Keyboard/mouse idle duration | Event timestamps | Low |

### Inferred Metrics (Calculated from Raw Signals)

| Inferred Metric | Calculation | Interpretation |
|-----------------|-------------|----------------|
| **Focus Sessions** | Continuous app usage >20min with low switching | Deep work periods |
| **Fragmented Time** | Rapid switching (<5min per app) | Scattered attention |
| **Meeting Load** | Calendar events with attendees >1 | Collaborative time |
| **Typing Activity** | Keystroke count per hour | Active work intensity |
| **Cognitive Interruptions** | App switches during focus sessions | Disruptions |
| **Recovery Time** | Idle periods between intensive work | Breaks |

---

## Document Complete

**You now have:**
1. Complete signal inventory
2. Technical implementation plan
3. 2-hour build timeline
4. Testing protocol
5. Data export strategy
6. Known limitations
7. Next steps

**Ready to build?**

Run through the checklist, follow the phases in order, and you'll have a working passive tracker collecting real behavioral data from your workday.

**First command to run:**
```bash
mkdir clear-ahead-tracker
cd clear-ahead-tracker
pip install pyobjc-framework-Cocoa pyobjc-framework-EventKit pyobjc-framework-Quartz rumps flask
```

**Then start with Phase 1 (calendar_sync.py) and work your way through.**

Good luck! 🚀
