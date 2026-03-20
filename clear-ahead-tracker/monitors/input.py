"""Input monitor: keystroke timing + mouse activity via Quartz CGEvent.

Privacy guarantee: NEVER captures key identity or content.
Only records timing (inter-key interval) and count per minute.
"""

import logging
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

# CGEvent type constants (from CGEventTypes.h)
_KEY_DOWN = 10     # kCGEventKeyDown
_KEY_UP = 11       # kCGEventKeyUp
_MOUSE_MOVE = 5    # kCGEventMouseMoved
_LMOUSE_DOWN = 1   # kCGEventLeftMouseDown
_RMOUSE_DOWN = 3   # kCGEventRightMouseDown

# Virtual key code for backspace (Delete key)
_VK_BACKSPACE = 51


class InputMonitor:
    """Captures keystroke timing and mouse activity.

    Aggregates per-minute buckets and flushes to storage.
    Requires Accessibility permissions (System Settings → Privacy → Accessibility).
    """

    FLUSH_INTERVAL = 60  # seconds between DB writes

    def __init__(self, storage, session_id: int):
        self.storage = storage
        self.session_id = session_id

        # Keystroke state
        self._key_times: deque = deque(maxlen=500)
        self._backspace_count = 0
        self._key_lock = threading.Lock()

        # Mouse state
        self._last_mouse_time: Optional[float] = None
        self._mouse_lock = threading.Lock()

        self._tap = None
        self._stop_event = threading.Event()
        self._flush_thread: Optional[threading.Thread] = None
        self._tap_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        if not HAS_QUARTZ:
            logger.info("InputMonitor: Quartz unavailable, skipping")
            return

        # Install event tap on a background thread (needs its own CFRunLoop)
        self._tap_thread = threading.Thread(
            target=self._install_tap, daemon=True, name="input-tap"
        )
        self._tap_thread.start()

        # Flush aggregated metrics periodically
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="input-flush"
        )
        self._flush_thread.start()
        logger.info("InputMonitor started")

    def stop(self):
        """Flush any buffered keystrokes before stopping so nothing is lost."""
        self._flush_metrics()  # drain buffer first
        self._stop_event.set()
        if self._tap:
            try:
                Quartz.CGEventTapEnable(self._tap, False)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Event tap
    # ------------------------------------------------------------------

    def _install_tap(self):
        import Quartz

        mask = (
            (1 << _KEY_DOWN)
            | (1 << _MOUSE_MOVE)
            | (1 << _LMOUSE_DOWN)
            | (1 << _RMOUSE_DOWN)
        )

        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,  # passive – no modification
            mask,
            self._event_callback,
            None,
        )

        if self._tap is None:
            logger.warning(
                "InputMonitor: Could not create event tap. "
                "Grant Accessibility access in System Settings → Privacy → Accessibility."
            )
            return

        run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            run_loop_source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(self._tap, True)
        logger.info("InputMonitor: event tap installed")
        Quartz.CFRunLoopRun()  # blocks until tap is disabled

    def _event_callback(self, proxy, event_type, event, refcon):
        """Called from the CGEventTap on every matched event."""
        try:
            t = time.monotonic()

            if event_type == _KEY_DOWN:
                # Check if backspace (we only look at virtual key code, not content)
                vk = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventKeycode
                )
                with self._key_lock:
                    self._key_times.append(t)
                    if vk == _VK_BACKSPACE:
                        self._backspace_count += 1

            elif event_type in (_MOUSE_MOVE, _LMOUSE_DOWN, _RMOUSE_DOWN):
                with self._mouse_lock:
                    self._last_mouse_time = t

        except Exception as e:
            logger.debug(f"InputMonitor callback error: {e}")

        return event  # required by CGEventTap API

    # ------------------------------------------------------------------
    # Flush loop
    # ------------------------------------------------------------------

    def _flush_loop(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(self.FLUSH_INTERVAL)
            if not self._stop_event.is_set():  # skip scheduled flush if stop() already flushed
                self._flush_metrics()

    def _flush_metrics(self):
        with self._key_lock:
            times = list(self._key_times)
            count = len(times)
            backspaces = self._backspace_count
            self._key_times.clear()
            self._backspace_count = 0

        if count == 0:
            return

        # Compute average inter-key latency in ms
        if len(times) >= 2:
            intervals = [
                (times[i] - times[i - 1]) * 1000
                for i in range(1, len(times))
                if (times[i] - times[i - 1]) < 2.0  # ignore gaps > 2 s
            ]
            avg_latency = sum(intervals) / len(intervals) if intervals else 0.0
        else:
            avg_latency = 0.0

        try:
            self.storage.insert_keystroke_metrics(
                self.session_id, datetime.now(), count, round(avg_latency, 2), backspaces
            )
            logger.debug(
                f"InputMonitor flush: {count} keys, {avg_latency:.1f}ms avg, {backspaces} backspaces"
            )
        except Exception as e:
            logger.error(f"InputMonitor storage error: {e}")
