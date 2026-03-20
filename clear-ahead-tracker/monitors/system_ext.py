"""Extended system metrics: battery, disk, network, audio, brightness, WiFi, VPN."""

import logging
import subprocess
import threading
from datetime import datetime
from typing import Optional

import psutil

logger = logging.getLogger(__name__)

_AIRPORT = (
    "/System/Library/PrivateFrameworks/Apple80211.framework"
    "/Versions/Current/Resources/airport"
)


class SystemExtMonitor:
    """Collects system-wide metrics every 5 minutes and stores them."""

    INTERVAL = 300

    def __init__(self, storage, session_id: int, registry=None):
        self.storage = storage
        self.session_id = session_id
        self.registry = registry
        self._proc = psutil.Process()
        self._last_net = None
        self._last_disk = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        # Prime the cpu_percent counter
        psutil.cpu_percent(interval=None)
        self._proc.cpu_percent(interval=None)
        self._last_net  = psutil.net_io_counters()
        self._last_disk = psutil.disk_io_counters()
        self._thread = threading.Thread(target=self._run, daemon=True, name="system-ext")
        self._thread.start()
        logger.info("SystemExtMonitor started")

    def stop(self):
        self._stop_event.set()

    def _run(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(self.INTERVAL)
            if self._stop_event.is_set():
                break
            self._collect()

    def _collect(self):
        ts = datetime.now()
        kwargs: dict = {"session_id": self.session_id, "timestamp": ts}

        # ── Tracker process ───────────────────────────────────────────
        try:
            kwargs["cpu_percent"]    = self._proc.cpu_percent(interval=1)
            kwargs["memory_mb"]      = int(self._proc.memory_info().rss / 1024 / 1024)
            if self.registry:
                self.registry.record("tracker_cpu")
                self.registry.record("tracker_memory")
        except Exception as e:
            if self.registry:
                self.registry.set_status("tracker_cpu", "failed", str(e))

        # ── System CPU ────────────────────────────────────────────────
        try:
            kwargs["system_cpu_percent"] = psutil.cpu_percent(interval=None)
            if self.registry:
                self.registry.record("system_cpu")
        except Exception as e:
            if self.registry:
                self.registry.set_status("system_cpu", "failed", str(e))

        # ── System memory ─────────────────────────────────────────────
        try:
            vm = psutil.virtual_memory()
            kwargs["system_memory_mb"] = int(vm.used / 1024 / 1024)
            if self.registry:
                self.registry.record("system_memory")
        except Exception as e:
            if self.registry:
                self.registry.set_status("system_memory", "failed", str(e))

        # ── Battery ───────────────────────────────────────────────────
        try:
            batt = psutil.sensors_battery()
            if batt:
                kwargs["battery_percent"]  = batt.percent
                kwargs["battery_charging"] = batt.power_plugged
                if self.registry:
                    self.registry.record("battery_level")
            else:
                if self.registry:
                    self.registry.set_status("battery_level", "unavailable", "No battery detected (desktop Mac)")
        except Exception as e:
            if self.registry:
                self.registry.set_status("battery_level", "failed", str(e))

        # ── Disk I/O (delta since last call) ──────────────────────────
        try:
            curr_disk = psutil.disk_io_counters()
            if self._last_disk:
                kwargs["disk_read_mb"]  = round((curr_disk.read_bytes  - self._last_disk.read_bytes)  / 1024 / 1024, 2)
                kwargs["disk_write_mb"] = round((curr_disk.write_bytes - self._last_disk.write_bytes) / 1024 / 1024, 2)
            self._last_disk = curr_disk
            if self.registry:
                self.registry.record("disk_io")
        except Exception as e:
            if self.registry:
                self.registry.set_status("disk_io", "failed", str(e))

        # ── Network bytes (delta) ─────────────────────────────────────
        try:
            curr_net = psutil.net_io_counters()
            if self._last_net:
                kwargs["net_sent_mb"] = round((curr_net.bytes_sent - self._last_net.bytes_sent) / 1024 / 1024, 3)
                kwargs["net_recv_mb"] = round((curr_net.bytes_recv - self._last_net.bytes_recv) / 1024 / 1024, 3)
            self._last_net = curr_net
            if self.registry:
                self.registry.record("network_bytes")
        except Exception as e:
            if self.registry:
                self.registry.set_status("network_bytes", "failed", str(e))

        # ── VPN (look for utun interfaces) ────────────────────────────
        try:
            ifaces = psutil.net_if_stats().keys()
            kwargs["vpn_active"] = any(i.startswith("utun") for i in ifaces)
            if self.registry:
                self.registry.record("vpn_status")
        except Exception as e:
            if self.registry:
                self.registry.set_status("vpn_status", "failed", str(e))

        # ── WiFi signal (airport CLI) ─────────────────────────────────
        wifi = self._get_wifi_signal()
        if wifi is not None:
            kwargs["wifi_signal_dbm"] = wifi

        # ── Audio volume ──────────────────────────────────────────────
        vol, muted = self._get_audio()
        if vol is not None:
            kwargs["audio_volume"] = vol
            kwargs["audio_muted"]  = muted

        # ── Display brightness ────────────────────────────────────────
        brightness = self._get_brightness()
        if brightness is not None:
            kwargs["brightness_percent"] = brightness

        # ── Persist ───────────────────────────────────────────────────
        try:
            self.storage.insert_system_metrics(**kwargs)
            logger.debug(f"SystemExt: cpu={kwargs.get('system_cpu_percent',0):.1f}% "
                         f"bat={kwargs.get('battery_percent','—')}")
        except Exception as e:
            logger.error(f"SystemExtMonitor storage error: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_wifi_signal(self) -> Optional[float]:
        try:
            r = subprocess.run([_AIRPORT, "-I"], capture_output=True, text=True, timeout=3)
            for line in r.stdout.splitlines():
                if "agrCtlRSSI" in line:
                    dbm = float(line.split(":")[1].strip())
                    if self.registry:
                        self.registry.record("wifi_signal")
                    return dbm
        except FileNotFoundError:
            if self.registry:
                self.registry.set_status("wifi_signal", "unavailable", "airport CLI not found")
        except Exception as e:
            if self.registry:
                self.registry.set_status("wifi_signal", "failed", str(e))
        return None

    def _get_audio(self) -> tuple[Optional[int], Optional[bool]]:
        try:
            vol_r = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True, timeout=3,
            )
            mute_r = subprocess.run(
                ["osascript", "-e", "output muted of (get volume settings)"],
                capture_output=True, text=True, timeout=3,
            )
            vol   = int(vol_r.stdout.strip())
            muted = mute_r.stdout.strip().lower() == "true"
            if self.registry:
                self.registry.record("audio_volume")
            return vol, muted
        except Exception as e:
            if self.registry:
                self.registry.set_status("audio_volume", "failed", str(e))
            return None, None

    def _get_brightness(self) -> Optional[float]:
        """Try ioreg to read display brightness (0-1 scale → 0-100)."""
        try:
            r = subprocess.run(
                ["ioreg", "-c", "IODisplayBrightnessControl", "-r", "-d", "1"],
                capture_output=True, text=True, timeout=3,
            )
            for line in r.stdout.splitlines():
                if '"brightness"' in line.lower() or "\"IODisplayBrightness\"" in line:
                    # Format: "IODisplayBrightness" = 0.75
                    parts = line.split("=")
                    if len(parts) == 2:
                        val = float(parts[1].strip())
                        result = round(val * 100, 1) if val <= 1.0 else round(val, 1)
                        if self.registry:
                            self.registry.record("display_brightness")
                        return result
        except Exception:
            pass
        # Fallback: osascript (unreliable but worth trying)
        try:
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get value of slider "Display" of '
                 'group 1 of window 1 of application process "Control Center"'],
                capture_output=True, text=True, timeout=3,
            )
            val = float(r.stdout.strip())
            if self.registry:
                self.registry.record("display_brightness")
            return round(val * 100, 1)
        except Exception as e:
            if self.registry:
                self.registry.set_status("display_brightness", "unavailable",
                                         "Requires IOKit private access or SIP disabled")
        return None
