"""Input monitor: full keyboard timing + mouse metrics via CGEventTap.

Privacy guarantee: NEVER captures key identity or content.
Tracks timing, counts, and movement only.
"""

import logging
import math
import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import Quartz
    HAS_QUARTZ = True
except ImportError:
    HAS_QUARTZ = False
    logger.warning("Quartz not available – input monitoring disabled")

# ── CGEvent type constants ────────────────────────────────────────────────────
_KEY_DOWN      = 10   # kCGEventKeyDown
_MOUSE_MOVE    = 5    # kCGEventMouseMoved
_LMOUSE_DOWN   = 1    # kCGEventLeftMouseDown
_RMOUSE_DOWN   = 3    # kCGEventRightMouseDown
_SCROLL        = 22   # kCGEventScrollWheel
_FLAGS_CHANGED = 12   # kCGEventFlagsChanged (modifier keys)

# Virtual key codes
_VK_BACKSPACE = 51

# Modifier flag masks
_MOD_CMD     = 0x100000
_MOD_CTRL    = 0x040000
_MOD_ALT     = 0x080000
_MOD_SHIFT   = 0x020000
_MOD_MASK    = _MOD_CMD | _MOD_CTRL | _MOD_ALT | _MOD_SHIFT

# Typing burst threshold: gap > this = new burst
_BURST_GAP_S = 2.0


class InputMonitor:
    """Captures all keyboard and mouse behavioral signals.

    Flushes aggregated 1-min buckets to storage — no raw events stored.
    Requires Accessibility permission for CGEventTap.
    """

    FLUSH_INTERVAL = 60  # seconds

    def __init__(self, storage, session_id: int, registry=None):
        self.storage = storage
        self.session_id = session_id
        self.registry = registry

        # ── Keyboard state ────────────────────────────────────────────
        self._key_times: deque[float] = deque(maxlen=1000)
        self._backspace_count = 0
        self._modifier_count = 0
        self._key_lock = threading.Lock()
        self._flush_start = time.monotonic()

        # ── Mouse state ───────────────────────────────────────────────
        self._last_mouse_pos: Optional[tuple[float, float]] = None
        self._mouse_distance = 0.0
        self._click_left = 0
        self._click_right = 0
        self._click_double = 0
        self._scroll_units = 0.0
        self._last_input_time: Optional[float] = None  # keyboard OR mouse
        self._mouse_lock = threading.Lock()

        self._tap = None
        self._tap_ok = False
        self._stop_event = threading.Event()
        self._flush_thread: Optional[threading.Thread] = None
        self._tap_thread: Optional[threading.Thread] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        if not HAS_QUARTZ:
            logger.info("InputMonitor: Quartz unavailable, skipping")
            if self.registry:
                for sig in ("keystroke_count","inter_key_latency","typing_speed_cpm",
                            "backspace_rate","modifier_key_freq","typing_bursts",
                            "rhythm_variance","mouse_distance","mouse_clicks",
                            "mouse_scroll","mouse_idle"):
                    self.registry.set_status(sig, "unavailable", "Quartz not installed")
            return

        self._tap_thread = threading.Thread(target=self._install_tap, daemon=True, name="input-tap")
        self._tap_thread.start()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True, name="input-flush")
        self._flush_thread.start()
        logger.info("InputMonitor started")

    def stop(self):
        self._flush_metrics()
        self._stop_event.set()
        if self._tap and HAS_QUARTZ:
            try:
                Quartz.CGEventTapEnable(self._tap, False)
            except Exception:
                pass

    # ── Event tap installation ────────────────────────────────────────────────

    def _install_tap(self):
        mask = (
            (1 << _KEY_DOWN)
            | (1 << _MOUSE_MOVE)
            | (1 << _LMOUSE_DOWN)
            | (1 << _RMOUSE_DOWN)
            | (1 << _SCROLL)
            | (1 << _FLAGS_CHANGED)
        )

        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._event_callback,
            None,
        )

        if self._tap is None:
            msg = "Accessibility permission required — grant in System Settings → Privacy → Accessibility"
            logger.warning(f"InputMonitor: {msg}")
            if self.registry:
                for sig in ("keystroke_count","inter_key_latency","typing_speed_cpm",
                            "backspace_rate","modifier_key_freq","typing_bursts",
                            "rhythm_variance","mouse_distance","mouse_clicks",
                            "mouse_scroll","mouse_idle"):
                    self.registry.set_status(sig, "no_permission", msg)
            return

        self._tap_ok = True
        src = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), src, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        logger.info("InputMonitor: event tap installed")
        Quartz.CFRunLoopRun()

    # ── Callback ──────────────────────────────────────────────────────────────

    def _event_callback(self, proxy, event_type, event, refcon):
        try:
            t = time.monotonic()

            if event_type == _KEY_DOWN:
                vk = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                with self._key_lock:
                    self._key_times.append(t)
                    if vk == _VK_BACKSPACE:
                        self._backspace_count += 1
                with self._mouse_lock:
                    self._last_input_time = t

            elif event_type == _FLAGS_CHANGED:
                flags = Quartz.CGEventGetFlags(event)
                if flags & _MOD_MASK:
                    with self._key_lock:
                        self._modifier_count += 1

            elif event_type == _MOUSE_MOVE:
                pos = Quartz.CGEventGetLocation(event)
                x, y = float(pos.x), float(pos.y)
                with self._mouse_lock:
                    if self._last_mouse_pos is not None:
                        dx = x - self._last_mouse_pos[0]
                        dy = y - self._last_mouse_pos[1]
                        self._mouse_distance += math.sqrt(dx * dx + dy * dy)
                    self._last_mouse_pos = (x, y)
                    self._last_input_time = t

            elif event_type == _LMOUSE_DOWN:
                click_state = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGMouseEventClickState)
                with self._mouse_lock:
                    if click_state == 2:
                        self._click_double += 1
                    else:
                        self._click_left += 1
                    self._last_input_time = t

            elif event_type == _RMOUSE_DOWN:
                with self._mouse_lock:
                    self._click_right += 1
                    self._last_input_time = t

            elif event_type == _SCROLL:
                delta = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGScrollWheelEventDeltaAxis1)
                with self._mouse_lock:
                    self._scroll_units += abs(delta)
                    self._last_input_time = t

        except Exception as e:
            logger.debug(f"InputMonitor callback error: {e}")

        return event

    # ── Flush ─────────────────────────────────────────────────────────────────

    def _flush_loop(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(self.FLUSH_INTERVAL)
            if not self._stop_event.is_set():
                self._flush_metrics()

    def _flush_metrics(self):
        now = time.monotonic()
        elapsed_minutes = max((now - self._flush_start) / 60.0, 1/60.0)
        self._flush_start = now

        # ── Collect keyboard state ────────────────────────────────────
        with self._key_lock:
            times      = list(self._key_times)
            count      = len(times)
            backspaces = self._backspace_count
            modifiers  = self._modifier_count
            self._key_times.clear()
            self._backspace_count = 0
            self._modifier_count = 0

        # ── Collect mouse state ───────────────────────────────────────
        with self._mouse_lock:
            distance     = self._mouse_distance
            click_left   = self._click_left
            click_right  = self._click_right
            click_double = self._click_double
            scroll       = self._scroll_units
            last_input   = self._last_input_time
            self._mouse_distance  = 0.0
            self._click_left      = 0
            self._click_right     = 0
            self._click_double    = 0
            self._scroll_units    = 0.0

        # Nothing to write if no activity
        if count == 0 and distance < 1 and click_left == 0:
            return

        # ── Keyboard calculations ─────────────────────────────────────
        intervals = []
        burst_count = 0
        in_gap = False
        for i in range(1, len(times)):
            gap = times[i] - times[i - 1]
            if gap < _BURST_GAP_S:
                intervals.append(gap * 1000)  # ms
            else:
                burst_count += 1
                in_gap = True

        avg_latency      = sum(intervals) / len(intervals) if intervals else 0.0
        typing_speed_cpm = (count / elapsed_minutes) if elapsed_minutes > 0 else 0.0

        if len(intervals) >= 2:
            mean = avg_latency
            variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
            rhythm_variance = math.sqrt(variance)
        else:
            rhythm_variance = 0.0

        # ── Idle time ─────────────────────────────────────────────────
        idle_seconds = (now - last_input) if last_input is not None else (elapsed_minutes * 60)

        # ── Record to registry ────────────────────────────────────────
        if self.registry and self._tap_ok:
            if count > 0:
                self.registry.record("keystroke_count")
                self.registry.record("inter_key_latency")
                self.registry.record("typing_speed_cpm")
                self.registry.record("backspace_rate")
                self.registry.record("rhythm_variance")
                if burst_count > 0:
                    self.registry.record("typing_bursts")
            if modifiers > 0:
                self.registry.record("modifier_key_freq")
            if distance > 0 or click_left > 0 or click_right > 0:
                self.registry.record("mouse_distance")
                self.registry.record("mouse_clicks")
            if scroll > 0:
                self.registry.record("mouse_scroll")
            self.registry.record("mouse_idle")

        # ── Persist ───────────────────────────────────────────────────
        try:
            self.storage.insert_input_metrics(
                session_id        = self.session_id,
                timestamp         = datetime.now(),
                keystroke_count   = count,
                avg_latency_ms    = avg_latency,
                backspace_count   = backspaces,
                typing_speed_cpm  = typing_speed_cpm,
                modifier_count    = modifiers,
                burst_count       = burst_count,
                rhythm_variance_ms= rhythm_variance,
                mouse_distance_px = distance,
                mouse_click_left  = click_left,
                mouse_click_right = click_right,
                mouse_click_double= click_double,
                mouse_scroll_units= scroll,
                mouse_idle_seconds= idle_seconds,
            )
            logger.debug(
                f"InputMonitor: {count} keys, {typing_speed_cpm:.0f} CPM, "
                f"{distance:.0f}px moved, {click_left+click_right} clicks"
            )
        except Exception as e:
            logger.error(f"InputMonitor storage error: {e}")
