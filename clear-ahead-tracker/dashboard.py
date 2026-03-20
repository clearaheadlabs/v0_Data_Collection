"""Flask dashboard — served at http://localhost:7331"""

import csv
import io
import logging
import threading
from datetime import datetime

from flask import Flask, Response, jsonify, render_template_string, request

logger = logging.getLogger(__name__)

# ── Shared CSS + nav ──────────────────────────────────────────────────────────
_BASE_CSS = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f5f5f7; color: #1d1d1f; }
.topbar { background: white; border-bottom: 1px solid #e5e5ea;
          padding: 0 2rem; display: flex; align-items: center; gap: 2rem; height: 52px;
          position: sticky; top: 0; z-index: 10; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.topbar .brand { font-weight: 700; font-size: 1rem; color: #1d1d1f; text-decoration: none; }
nav a { font-size: .875rem; color: #6e6e73; text-decoration: none; padding: .25rem 0;
        border-bottom: 2px solid transparent; }
nav a.active, nav a:hover { color: #0071e3; border-bottom-color: #0071e3; }
nav { display: flex; gap: 1.5rem; }
.page { padding: 2rem; max-width: 1200px; margin: 0 auto; }
h2 { font-size: 1.1rem; font-weight: 600; margin: 1.5rem 0 .75rem; }
h2:first-child { margin-top: 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
        gap: 1rem; margin-bottom: 1.5rem; }
.card { background: white; border-radius: 12px; padding: 1.2rem;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.card .label { font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
               color: #6e6e73; margin-bottom: .35rem; }
.card .value { font-size: 2rem; font-weight: 700; line-height: 1; }
.card .sub   { font-size: .78rem; color: #6e6e73; margin-top: .3rem; }
.tbl-wrap { background: white; border-radius: 12px; overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 1.5rem; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: .65rem 1rem; text-align: left; border-bottom: 1px solid #f2f2f2;
         font-size: .85rem; }
th { font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
     color: #6e6e73; background: #fafafa; font-weight: 600; }
tr:last-child td { border-bottom: none; }
.empty { color: #aeaeb2; text-align: center; padding: 2rem !important; }
.badge { display: inline-block; padding: .15rem .5rem; border-radius: 4px;
         font-size: .72rem; font-weight: 600; }
.badge-clean  { background: #e8f8e8; color: #1a7f37; }
.badge-crash  { background: #fff3cd; color: #856404; }
.badge-active { background: #dff0ff; color: #0071e3; }
.bar  { height: 7px; background: #0071e3; border-radius: 3px; display: inline-block; min-width: 3px; }
.btn  { display: inline-block; padding: .55rem 1.3rem; background: #0071e3;
        color: white; border-radius: 8px; text-decoration: none; font-size: .875rem;
        font-weight: 500; }
.btn:hover { background: #0077ed; }
.ts  { font-size: .72rem; color: #aeaeb2; margin-top: 1.5rem; }
.dur { color: #6e6e73; font-size: .8rem; }
</style>
"""

_NAV = """
<div class="topbar">
  <a class="brand" href="/">Clear Ahead</a>
  <nav>
    <a href="/" class="{{ 'active' if page == 'today' }}">Today</a>
    <a href="/log" class="{{ 'active' if page == 'log' }}">Data Log</a>
    <a href="/sessions" class="{{ 'active' if page == 'sessions' }}">Sessions</a>
  </nav>
  <span style="margin-left:auto;font-size:.8rem;color:#aeaeb2;">Auto-refresh 30s</span>
</div>
"""

# ── Today page ────────────────────────────────────────────────────────────────
_TODAY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clear Ahead — Today</title>
<meta http-equiv="refresh" content="30">
""" + _BASE_CSS + """
</head>
<body>
""" + _NAV + """
<div class="page">
<div class="grid">
  <div class="card">
    <div class="label">Calendar Events Today</div>
    <div class="value">{{ s.calendar_events }}</div>
  </div>
  <div class="card">
    <div class="label">Context Switches Today</div>
    <div class="value">{{ s.context_switches }}</div>
  </div>
  <div class="card">
    <div class="label">Keystrokes Today</div>
    <div class="value">{{ "{:,}".format(s.keystroke_total) }}</div>
  </div>
  <div class="card">
    <div class="label">Tracker CPU</div>
    <div class="value">{{ "%.1f"|format(s.cpu_percent) }}%</div>
    <div class="sub">RAM: {{ s.memory_mb }} MB</div>
  </div>
</div>

<h2>Top 5 Apps Today</h2>
<div class="tbl-wrap"><table>
  <thead><tr><th>#</th><th>Application</th><th>Switches</th><th>Share</th></tr></thead>
  <tbody>
  {% set total = s.top_apps | sum(attribute='cnt') %}
  {% for app in s.top_apps %}
  <tr>
    <td>{{ loop.index }}</td>
    <td><strong>{{ app.to_app }}</strong></td>
    <td>{{ app.cnt }}</td>
    <td>
      {% if total > 0 %}{% set pct = (app.cnt / total * 100) | round(1) %}
      <div class="bar" style="width:{{ [pct*1.8,180]|min }}px"></div>
      &nbsp;{{ pct }}%
      {% endif %}
    </td>
  </tr>
  {% else %}
  <tr><td colspan="4" class="empty">No app switches recorded yet</td></tr>
  {% endfor %}
  </tbody>
</table></div>

<h2>Sessions Today</h2>
<div class="tbl-wrap"><table>
  <thead><tr><th>ID</th><th>Started</th><th>Ended</th><th>Duration</th><th>Status</th></tr></thead>
  <tbody>
  {% for s2 in s.sessions_today %}
  <tr>
    <td>#{{ s2.id }}</td>
    <td>{{ s2.started_at[11:19] }}</td>
    <td>{{ s2.ended_at[11:19] if s2.ended_at else "—" }}</td>
    <td class="dur">
      {% if s2.duration_seconds %}
        {% set h = s2.duration_seconds // 3600 %}
        {% set m = (s2.duration_seconds % 3600) // 60 %}
        {% set sec = s2.duration_seconds % 60 %}
        {% if h %}{{ h }}h {% endif %}{{ m }}m {{ sec }}s
      {% else %}running…{% endif %}
    </td>
    <td>
      {% if s2.end_reason == 'clean' %}<span class="badge badge-clean">clean</span>
      {% elif s2.end_reason == 'crash' %}<span class="badge badge-crash">crash</span>
      {% else %}<span class="badge badge-active">active</span>{% endif %}
    </td>
  </tr>
  {% else %}
  <tr><td colspan="5" class="empty">No sessions today</td></tr>
  {% endfor %}
  </tbody>
</table></div>

<a class="btn" href="/export/csv">Export All Data (CSV)</a>
<p class="ts">Last updated: {{ now }}</p>
</div></body></html>
"""

# ── Data Log page ─────────────────────────────────────────────────────────────
_LOG_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clear Ahead — Data Log</title>
<meta http-equiv="refresh" content="30">
""" + _BASE_CSS + """
<style>
.tabs { display:flex; gap:.5rem; margin-bottom:1rem; }
.tab  { padding:.45rem 1rem; border-radius:7px; font-size:.85rem; font-weight:500;
        cursor:pointer; background:white; border:1px solid #e5e5ea; color:#6e6e73;
        text-decoration:none; }
.tab.on { background:#0071e3; color:white; border-color:#0071e3; }
</style>
</head>
<body>
""" + _NAV + """
<div class="page">
<div class="tabs">
  <a class="tab {{ 'on' if tab=='switches' }}" href="/log?tab=switches">App Switches</a>
  <a class="tab {{ 'on' if tab=='keystrokes' }}" href="/log?tab=keystrokes">Keystrokes</a>
  <a class="tab {{ 'on' if tab=='calendar' }}" href="/log?tab=calendar">Calendar</a>
</div>

{% if tab == 'switches' %}
<h2>Recent App Switches <span style="font-size:.8rem;font-weight:400;color:#aeaeb2">(last 100)</span></h2>
<div class="tbl-wrap"><table>
  <thead><tr><th>Time</th><th>From</th><th>To</th><th>Duration in From</th><th>Session</th></tr></thead>
  <tbody>
  {% for r in rows %}
  <tr>
    <td>{{ r.timestamp[:19] }}</td>
    <td style="color:#6e6e73">{{ r.from_app or "—" }}</td>
    <td><strong>{{ r.to_app }}</strong></td>
    <td class="dur">
      {% if r.duration_seconds %}
        {% set m = r.duration_seconds // 60 %}{% set s = r.duration_seconds % 60 %}
        {% if m %}{{ m }}m {% endif %}{{ s }}s
      {% else %}—{% endif %}
    </td>
    <td style="color:#aeaeb2">#{{ r.session_id }}</td>
  </tr>
  {% else %}
  <tr><td colspan="5" class="empty">No data yet</td></tr>
  {% endfor %}
  </tbody>
</table></div>

{% elif tab == 'keystrokes' %}
<h2>Keystroke Metrics <span style="font-size:.8rem;font-weight:400;color:#aeaeb2">(1-min buckets, last 100)</span></h2>
<div class="tbl-wrap"><table>
  <thead><tr><th>Time</th><th>Keystrokes</th><th>Avg Latency</th><th>Backspaces</th><th>Session</th></tr></thead>
  <tbody>
  {% for r in rows %}
  <tr>
    <td>{{ r.timestamp[:19] }}</td>
    <td><strong>{{ r.keystroke_count }}</strong></td>
    <td class="dur">{{ "%.0f"|format(r.avg_latency_ms) }} ms</td>
    <td>{{ r.backspace_count }}</td>
    <td style="color:#aeaeb2">#{{ r.session_id }}</td>
  </tr>
  {% else %}
  <tr><td colspan="5" class="empty">No data yet</td></tr>
  {% endfor %}
  </tbody>
</table></div>

{% elif tab == 'calendar' %}
<h2>Calendar Events <span style="font-size:.8rem;font-weight:400;color:#aeaeb2">(last 50)</span></h2>
<div class="tbl-wrap"><table>
  <thead><tr><th>Title</th><th>Start</th><th>End</th><th>Duration</th></tr></thead>
  <tbody>
  {% for r in rows %}
  <tr>
    <td><strong>{{ r.title }}</strong></td>
    <td>{{ r.start_time[:16] }}</td>
    <td>{{ r.end_time[:16] }}</td>
    <td class="dur">{{ r.duration_minutes }} min</td>
  </tr>
  {% else %}
  <tr><td colspan="4" class="empty">No calendar events synced yet</td></tr>
  {% endfor %}
  </tbody>
</table></div>
{% endif %}

<p class="ts">Last updated: {{ now }}</p>
</div></body></html>
"""

# ── Sessions page ─────────────────────────────────────────────────────────────
_SESSIONS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clear Ahead — Sessions</title>
<meta http-equiv="refresh" content="60">
""" + _BASE_CSS + """
</head>
<body>
""" + _NAV + """
<div class="page">
<h2>All Sessions</h2>
<div class="tbl-wrap"><table>
  <thead><tr><th>ID</th><th>Date</th><th>Started</th><th>Ended</th><th>Duration</th><th>Status</th></tr></thead>
  <tbody>
  {% for s in sessions %}
  <tr>
    <td>#{{ s.id }}</td>
    <td>{{ s.started_at[:10] }}</td>
    <td>{{ s.started_at[11:19] }}</td>
    <td>{{ s.ended_at[11:19] if s.ended_at else "—" }}</td>
    <td class="dur">
      {% if s.duration_seconds %}
        {% set h = s.duration_seconds // 3600 %}
        {% set m = (s.duration_seconds % 3600) // 60 %}
        {% set sec = s.duration_seconds % 60 %}
        {% if h %}{{ h }}h {% endif %}{{ m }}m {{ sec }}s
      {% else %}running…{% endif %}
    </td>
    <td>
      {% if s.end_reason == 'clean' %}<span class="badge badge-clean">clean</span>
      {% elif s.end_reason == 'crash' %}<span class="badge badge-crash">crash</span>
      {% else %}<span class="badge badge-active">active</span>{% endif %}
    </td>
  </tr>
  {% else %}
  <tr><td colspan="6" class="empty">No sessions recorded yet</td></tr>
  {% endfor %}
  </tbody>
</table></div>
<a class="btn" href="/export/csv">Export All Data (CSV)</a>
<p class="ts">Last updated: {{ now }}</p>
</div></body></html>
"""


class Dashboard:
    def __init__(self, storage, port: int = 7331):
        self.storage = storage
        self.port = port
        self.app = Flask(__name__)
        self._thread: threading.Thread | None = None
        self._register_routes()

    def _register_routes(self):
        storage = self.storage

        @self.app.route("/")
        def index():
            s = storage.get_today_summary()
            return render_template_string(
                _TODAY_HTML,
                s=s,
                page="today",
                now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )

        @self.app.route("/log")
        def log():
            tab = request.args.get("tab", "switches")
            if tab == "switches":
                rows = storage.get_recent_switches(100)
            elif tab == "keystrokes":
                rows = storage.get_recent_keystrokes(100)
            else:
                tab = "calendar"
                rows = storage.get_calendar_events(50)
            return render_template_string(
                _LOG_HTML,
                rows=rows,
                tab=tab,
                page="log",
                now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )

        @self.app.route("/sessions")
        def sessions():
            return render_template_string(
                _SESSIONS_HTML,
                sessions=storage.get_all_sessions(),
                page="sessions",
                now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )

        @self.app.route("/api/summary")
        def api_summary():
            return jsonify(storage.get_today_summary())

        @self.app.route("/export/csv")
        def export_csv():
            data = storage.get_all_for_export()
            buf = io.StringIO()
            writer = csv.writer(buf)
            for table_name, rows in data.items():
                if not rows:
                    continue
                writer.writerow([f"=== {table_name} ==="])
                writer.writerow(rows[0].keys())
                for row in rows:
                    writer.writerow(row.values())
                writer.writerow([])
            filename = f"clear_ahead_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            return Response(
                buf.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

    def start(self):
        self._thread = threading.Thread(
            target=lambda: self.app.run(
                host="127.0.0.1",
                port=self.port,
                debug=False,
                use_reloader=False,
            ),
            daemon=True,
            name="dashboard",
        )
        self._thread.start()
        logger.info(f"Dashboard running at http://127.0.0.1:{self.port}")
