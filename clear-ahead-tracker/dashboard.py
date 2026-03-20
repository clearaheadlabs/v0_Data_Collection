"""Flask dashboard — served at http://localhost:7331"""

import csv
import io
import logging
import threading
from datetime import datetime

from flask import Flask, Response, jsonify, render_template_string

logger = logging.getLogger(__name__)

_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clear Ahead Tracker</title>
<meta http-equiv="refresh" content="30">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f5f5f7; color: #1d1d1f; padding: 2rem; }
  h1   { font-size: 1.6rem; font-weight: 600; margin-bottom: 1.5rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 1rem; margin-bottom: 2rem; }
  .card { background: white; border-radius: 12px; padding: 1.2rem;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .card .label { font-size: .75rem; text-transform: uppercase; letter-spacing: .05em;
                 color: #6e6e73; margin-bottom: .4rem; }
  .card .value { font-size: 2rem; font-weight: 700; }
  .card .sub   { font-size: .8rem; color: #6e6e73; margin-top: .2rem; }
  table { width: 100%; border-collapse: collapse; background: white;
          border-radius: 12px; overflow: hidden;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 1.5rem; }
  th, td { padding: .75rem 1rem; text-align: left; border-bottom: 1px solid #f2f2f2; }
  th { font-size: .75rem; text-transform: uppercase; letter-spacing: .05em;
       color: #6e6e73; background: #fafafa; }
  tr:last-child td { border-bottom: none; }
  .btn { display: inline-block; padding: .6rem 1.4rem; background: #0071e3;
         color: white; border-radius: 8px; text-decoration: none; font-size: .9rem;
         font-weight: 500; margin-top: .5rem; }
  .btn:hover { background: #0077ed; }
  .ts  { font-size: .75rem; color: #aeaeb2; margin-top: 2rem; }
  .bar { height: 8px; background: #0071e3; border-radius: 4px; min-width: 4px; }
</style>
</head>
<body>
<h1>Clear Ahead — Behavioral Signal Tracker</h1>

<div class="grid">
  <div class="card">
    <div class="label">Calendar Events Today</div>
    <div class="value">{{ summary.calendar_events }}</div>
  </div>
  <div class="card">
    <div class="label">Context Switches Today</div>
    <div class="value">{{ summary.context_switches }}</div>
  </div>
  <div class="card">
    <div class="label">Keystrokes Today</div>
    <div class="value">{{ "{:,}".format(summary.keystroke_total) }}</div>
  </div>
  <div class="card">
    <div class="label">Tracker CPU</div>
    <div class="value">{{ "%.1f"|format(summary.cpu_percent) }}%</div>
    <div class="sub">RAM: {{ summary.memory_mb }} MB</div>
  </div>
</div>

<h2 style="font-size:1.1rem;font-weight:600;margin-bottom:.75rem;">Top 5 Apps Today</h2>
<table>
  <thead><tr><th>#</th><th>Application</th><th>Switches</th><th>Share</th></tr></thead>
  <tbody>
  {% set total = summary.top_apps | sum(attribute='cnt') %}
  {% for app in summary.top_apps %}
  <tr>
    <td>{{ loop.index }}</td>
    <td>{{ app.to_app }}</td>
    <td>{{ app.cnt }}</td>
    <td>
      {% if total > 0 %}
      {% set pct = (app.cnt / total * 100) | round(1) %}
      <div class="bar" style="width:{{ [pct*2, 200]|min }}px; display:inline-block;"></div>
      {{ pct }}%
      {% endif %}
    </td>
  </tr>
  {% else %}
  <tr><td colspan="4" style="color:#aeaeb2;text-align:center;padding:2rem;">No app switches recorded yet</td></tr>
  {% endfor %}
  </tbody>
</table>

<h2 style="font-size:1.1rem;font-weight:600;margin-bottom:.75rem;">Sessions Today</h2>
<table>
  <thead><tr><th>ID</th><th>Started</th><th>Ended</th><th>Duration</th><th>Status</th></tr></thead>
  <tbody>
  {% for s in summary.sessions_today %}
  <tr>
    <td>#{{ s.id }}</td>
    <td>{{ s.started_at[:19] }}</td>
    <td>{{ s.ended_at[:19] if s.ended_at else "—" }}</td>
    <td>
      {% if s.duration_seconds %}
        {% set h = s.duration_seconds // 3600 %}
        {% set m = (s.duration_seconds % 3600) // 60 %}
        {% set sec = s.duration_seconds % 60 %}
        {% if h %}{{ h }}h {% endif %}{{ m }}m {{ sec }}s
      {% else %}running…{% endif %}
    </td>
    <td>
      {% if s.end_reason == 'clean' %}✅ clean
      {% elif s.end_reason == 'crash' %}⚠️ crash
      {% else %}🟢 active{% endif %}
    </td>
  </tr>
  {% else %}
  <tr><td colspan="5" style="color:#aeaeb2;text-align:center;padding:2rem;">No sessions today</td></tr>
  {% endfor %}
  </tbody>
</table>

<a class="btn" href="/export/csv">Export All Data (CSV)</a>

<p class="ts">Last updated: {{ now }} &nbsp;·&nbsp; Auto-refreshes every 30 s</p>
</body>
</html>
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
            summary = storage.get_today_summary()
            return render_template_string(
                _HTML,
                summary=summary,
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
                writer.writerow([])  # blank separator

            filename = f"clear_ahead_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            return Response(
                buf.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

    def start(self):
        import os
        os.environ["WERKZEUG_RUN_MAIN"] = "true"  # suppress reloader banner
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
