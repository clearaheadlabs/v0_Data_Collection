"""Calendar monitor using EventKit via PyObjC."""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

# EventKit is only available on macOS; import gracefully
try:
    import EventKit
    HAS_EVENTKIT = True
except ImportError:
    HAS_EVENTKIT = False
    logger.warning("EventKit not available – calendar monitoring disabled")


class CalendarMonitor:
    """Syncs upcoming and recent calendar events into the database."""

    SYNC_INTERVAL = 300  # seconds between full syncs

    def __init__(self, storage, session_id: int):
        self.storage = storage
        self.session_id = session_id
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._store = None
        self._authorized = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        if not HAS_EVENTKIT:
            logger.info("CalendarMonitor: EventKit unavailable, skipping")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="calendar-monitor")
        self._thread.start()
        logger.info("CalendarMonitor started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self):
        self._request_access()
        while not self._stop_event.is_set():
            if self._authorized:
                try:
                    self._sync_events()
                except Exception as e:
                    logger.error(f"CalendarMonitor sync error: {e}", exc_info=True)
            self._stop_event.wait(self.SYNC_INTERVAL)

    def _request_access(self):
        """Request calendar access via EventKit. Blocks until user responds."""
        if not HAS_EVENTKIT:
            return

        done = threading.Event()

        def handler(granted, error):
            if error:
                logger.error(f"EventKit access error: {error}")
            self._authorized = bool(granted)
            if granted:
                self._store = EventKit.EKEventStore.alloc().init()
            done.set()

        store = EventKit.EKEventStore.alloc().init()
        store.requestAccessToEntityType_completion_(
            EventKit.EKEntityTypeEvent, handler
        )
        done.wait(timeout=30)
        if not self._authorized:
            logger.warning("Calendar access denied – calendar monitoring disabled")

    def _sync_events(self):
        if self._store is None:
            return

        now = datetime.now()
        start_ns = self._to_nsdate(now - timedelta(days=1))
        end_ns = self._to_nsdate(now + timedelta(days=7))

        predicate = self._store.predicateForEventsWithStartDate_endDate_calendars_(
            start_ns, end_ns, None
        )
        events = self._store.eventsMatchingPredicate_(predicate)

        synced = 0
        for ev in (events or []):
            try:
                title = str(ev.title() or "Untitled")
                start = self._from_nsdate(ev.startDate())
                end = self._from_nsdate(ev.endDate())
                duration = int((end - start).total_seconds() / 60)
                self.storage.upsert_calendar_event(self.session_id, title, start, end, duration)
                synced += 1
            except Exception as e:
                logger.debug(f"Skipping event: {e}")

        logger.debug(f"CalendarMonitor: synced {synced} events")

    @staticmethod
    def _to_nsdate(dt: datetime):
        import Foundation
        ref = datetime(2001, 1, 1)
        interval = (dt - ref).total_seconds()
        return Foundation.NSDate.dateWithTimeIntervalSinceReferenceDate_(interval)

    @staticmethod
    def _from_nsdate(nsdate) -> datetime:
        interval = nsdate.timeIntervalSinceReferenceDate()
        ref = datetime(2001, 1, 1)
        return ref + timedelta(seconds=interval)
