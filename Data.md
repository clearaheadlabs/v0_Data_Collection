# Clear Ahead Data Collection - Quick Reference

## What Can We Capture? (Signal Inventory)

### 🖥️ Application & Window Behavior
- Active app name, bundle ID, version
- App switch events (from → to, timestamp, duration in previous)
- Window titles (optional, privacy-sensitive)
- CPU/memory per app
- App category (communication, development, browser, etc.)

### ⌨️ Keyboard (Timing Only - NO Content)
- Inter-key latency (time between keystrokes)
- Typing speed (WPM, CPM)
- Backspace/delete count (error correction rate)
- Typing rhythm variance (consistency)
- Pause duration between typing bursts
- Modifier key usage (Cmd/Ctrl frequency)

### 🖱️ Mouse/Trackpad
- Movement distance per minute
- Movement velocity & acceleration (jerkiness)
- Click count, click type (left/right/double)
- Scroll speed & direction
- Idle time (keyboard & mouse separately)

### 📅 Calendar (iCal EventKit)
- Event title, start/end time, duration
- Attendee count (meeting vs solo)
- Back-to-back patterns (<5min gaps)
- Meeting density (per day, per week)
- Focus blocks (non-meeting time ≥2hrs)

### 💻 System State
- CPU usage (system-wide + tracker process)
- Memory usage (system + tracker)
- Battery level, charging state (if laptop)
- Disk I/O activity
- Display brightness, Night Shift status
- Audio volume, muted state, mic active

### 🌐 Network (Basic)
- Connection type (WiFi/Ethernet/Cellular)
- WiFi signal strength
- Bytes sent/received per minute
- VPN active status

### 🧠 Cognitive Load Proxies (Derived)
- Context switch rate (switches per hour)
- Sustained focus duration (time in app without switching)
- Typing speed degradation (vs personal baseline)
- Error correction rate (backspace ratio)
- Multitasking intensity (rapid switching)
- Calendar fragmentation (gaps between meetings)

### 🚫 Privacy Red Lines (Never Capture)
- ❌ Keystroke content (what you type)
- ❌ Screenshots or screen recording
- ❌ Webcam or microphone audio
- ❌ Clipboard content
- ❌ Browser history (unless from window titles, optional)
- ❌ Document content
- ❌ Email/message content

---

## Database Schema (5 Core Tables)

### 1. `events_raw` - Immutable Event Log
```sql
id, timestamp, event_type, metadata_json, session_id
```
**Purpose:** All discrete events (switches, clicks, keystrokes)  
**Retention:** Keep forever or partition by month

### 2. `calendar_events`
```sql
id, event_id, title, start_time, end_time, duration_minutes, 
attendee_count, is_meeting, calendar_source
```
**Purpose:** All calendar data from iCal  
**Sync:** Every 5 minutes

### 3. `input_metrics_1min` - Aggregated
```sql
id, timestamp, keystroke_count, avg_inter_key_latency_ms, 
typing_speed_cpm, backspace_count, mouse_movement_distance_px, 
mouse_click_count, active_app
```
**Purpose:** Keyboard/mouse metrics per 1-minute window  
**Why aggregate:** Don't store 300 keystrokes/min individually

### 4. `system_metrics_5min` - Aggregated
```sql
id, timestamp, system_cpu_percent, tracker_cpu_percent, 
tracker_memory_mb, battery_level_percent
```
**Purpose:** System state every 5 minutes  
**Frequency:** Lower than input (less critical)

### 5. `work_sessions` - High-Level Summary
```sql
id, session_id, started_at, ended_at, duration_minutes, 
active_time_minutes, idle_time_minutes, context_switch_count, 
meeting_count, avg_typing_speed_cpm
```
**Purpose:** Daily session summaries for quick analysis

---

## Data Quality Rules (Implement at Collection)

### ✅ Validation Before Insert
- Timestamp not in future or >30 days old
- CPU/battery percentages between 0-100
- Inter-key latency < 60 seconds (reject impossible values)
- Required fields present (event_type, timestamp)

### 🔍 Duplicate Detection
- Reject events <100ms apart with same event_type
- Prevents sensor noise from creating garbage data

### 📊 Outlier Flagging
- Calculate Z-score vs baseline (mean ± 3 std dev)
- Flag but don't reject (might be real extreme day)
- Review flagged outliers weekly

### 🕐 Timestamp Alignment
- Round to nearest minute/5-min for aggregation
- Ensures consistent time bins for ML features

### 📦 Aggregation Strategy
- **Keystrokes/mouse:** Aggregate every 1 minute, then insert
- **System metrics:** Aggregate every 5 minutes
- **Calendar:** Sync every 5 minutes (poll API)
- **App switches:** Store immediately (low frequency)

---

## Storage Best Practices

### Store Both Raw & Normalized Values
```sql
typing_speed_cpm INT,          -- Raw value (interpretable)
typing_speed_z_score FLOAT,    -- Normalized to YOUR baseline
```
**Why:** Raw = human-readable, Z-score = ML-comparable

### Use JSON for Flexibility
```sql
metadata JSON  -- Store non-critical fields here
```
**Example:** `{"window_title": "Chrome", "tab_count": 12}`  
**Benefit:** Add new fields without schema changes

### Index Timestamps
```sql
INDEX idx_timestamp (timestamp)
```
**Why:** 90% of queries filter by time range

### Partition by Month (Optional, for >6 months data)
```sql
PARTITION BY RANGE (YEAR(timestamp) * 100 + MONTH(timestamp))
```
**Benefit:** Fast deletes, faster queries

---

## Export Format for Analysis

### Use Parquet (Not CSV)
```python
df.to_parquet('clear_ahead_week1.parquet', compression='snappy')
```

**Why Parquet:**
- ✅ 10x smaller than CSV (compressed)
- ✅ 10x faster to load (columnar format)
- ✅ Preserves data types (no parsing errors)
- ✅ Industry standard for ML pipelines

### Include Metadata File
```json
{
  "export_date": "2024-03-20",
  "date_range": {"start": "2024-03-01", "end": "2024-03-07"},
  "row_count": 2016,
  "columns": ["timestamp", "typing_speed_cpm", "context_switches", ...],
  "data_quality": {
    "missing_intervals": 12,
    "outlier_rate": 0.03,
    "uptime_percent": 98.5
  }
}
```

---

## ML-Ready Feature Matrix

### Problem: Different Sampling Rates
- Keystrokes: 100-300/min
- App switches: 5-20/hour
- Calendar: 5-10/day
- System: Every 5 minutes

### Solution: Time-Aligned 5-Min Bins
```python
def create_feature_matrix(start, end, interval='5min'):
    timestamps = pd.date_range(start, end, freq=interval)
    
    features = pd.DataFrame({
        'timestamp': timestamps,
        'keystroke_count_5min': aggregate_keystrokes(timestamps),
        'app_switches_5min': count_switches(timestamps),
        'in_meeting': is_in_meeting(timestamps),
        'cpu_percent_avg': average_cpu(timestamps),
        'typing_speed_z': normalize_typing_speed(timestamps)
    })
    
    return features  # Every row = 5 minutes, all features aligned
```

**Result:** 288 rows/day, ready for sklearn/PyTorch

---

## Data Quality Dashboard (Build This)

### Daily Metrics to Track
```python
{
  'date': '2024-03-20',
  'events_collected': 4521,
  'expected_events': ~4800,  # Based on 16-hour workday
  'coverage_percent': 94.2,
  'missing_intervals': 12,  # Out of 192 5-min intervals
  'duplicate_rate': 0.8%,
  'outlier_rate': 2.1%,
  'tracker_uptime': 98.5%,
  'calendar_sync_lag': 3.2  # minutes
}
```

### Alert Thresholds
- ⚠️ Coverage <80% → Data collection failure
- ⚠️ Duplicate rate >5% → Sensor malfunction
- ⚠️ Outlier rate >10% → Validation broken
- ⚠️ Calendar lag >30min → API issue

---

## What to Tell Claude Code

**Add to your MVP prompt:**

```
Implement data quality from day one:

1. Database Schema:
   - Use the 5-table schema (events_raw, calendar_events, 
     input_metrics_1min, system_metrics_5min, work_sessions)
   - Add indexes on all timestamp columns
   - Store both raw and normalized values where applicable

2. Data Validation:
   - Validate timestamps (not future, not ancient)
   - Range check all percentages (0-100)
   - Reject inter-key latency >60sec
   - Detect duplicates (<100ms apart, same type)

3. Aggregation:
   - Buffer keystrokes/mouse in memory
   - Aggregate to 1-min bins before inserting
   - System metrics every 5 minutes
   - Calendar sync every 5 minutes

4. Export Function:
   - Export to Parquet format
   - Include metadata JSON file
   - Generate daily data quality report

5. Quality Monitoring:
   - Track events collected vs expected
   - Count missing intervals
   - Calculate duplicate/outlier rates
   - Log validation failures
```

---

## After 1 Week: Verify Data Quality

```python
import pandas as pd

# Load data
df = pd.read_parquet('clear_ahead_week1.parquet')

# Basic checks
print(f"Total rows: {len(df)}")
print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
print(f"Columns: {len(df.columns)}")

# Expected: ~2000 rows (7 days × 288 5-min intervals)
# If much less → gaps in collection

# Check for nulls
print(df.isnull().sum())

# Check correlations (are signals related?)
print(df.corr())

# Visualize a day
df[df['timestamp'].dt.date == '2024-03-20'].plot(
    x='timestamp', 
    y=['typing_speed_cpm', 'context_switches_5min', 'in_meeting']
)
```

**If clean → start building models**  
**If messy → check data quality report for root cause**

---

## Key Principles (Remember These)

### 1. Aggregate Early
Don't store raw keystrokes → aggregate to 1-min bins immediately

### 2. Validate Everything  
Reject garbage at collection time, not during analysis

### 3. Store Raw + Normalized
`typing_speed_cpm` AND `typing_speed_z_score`

### 4. Time-Align for ML
Create 5-min feature matrix where every row = same interval

### 5. Parquet for Export
10x better than CSV in every way

### 6. Monitor Quality Daily
Missing intervals, duplicates, outliers, uptime

### 7. Privacy First
Never capture content, only behavioral timing patterns

---

## Quick Start Checklist

- [ ] Claude Code implements 5-table schema
- [ ] Validation rules in place (timestamp, range checks)
- [ ] Duplicate detection working
- [ ] 1-min aggregation for input metrics
- [ ] 5-min aggregation for system metrics
- [ ] Parquet export function
- [ ] Data quality report generator
- [ ] Run tracker for 1 week
- [ ] Export and verify data quality
- [ ] Check for gaps, outliers, nulls
- [ ] If clean → start building inference models

---

**Total Data Points per Day:** ~2000-5000 events  
**Storage per Month:** ~5-10 MB (Parquet compressed)  
**Signals Captured:** 50-100 distinct behavioral metrics  
**ML-Ready:** Yes, with 5-min time-aligned feature matrix
