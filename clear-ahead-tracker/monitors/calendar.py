"""Calendar monitor — EventKit with attendee count and meeting detection."""

import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import EventKit
    HAS_EVENTKIT = True
except ImportError:
    HAS_EVENTKIT = False
    logger.warning("EventKit not available – calendar monitoring disabled")


class CalendarMonitor:
    SYNC_INTERVAL = 300  # 5 minutes

    def __init__(self, storage, session_id: int, registry=None):
        self.storage = storage
        self.session_id = session_id
        self.registry = registry
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._store = None
        self._authorized = False

    def start(self):
        if not HAS_EVENTKIT:
            logger.info("CalendarMonitor: EventKit unavailable, skipping")
            if self.registry:
                for sig in ("calendar_events", "calendar_attendees", "calendar_type"):
                    self.registry.set_status(sig, "unavailable", "EventKit not installed")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="calendar-monitor")
        self._thread.start()
        logger.info("CalendarMonitor started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

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
        if not HAS_EVENTKIT:
            return
        done = threading.Event()

        def handler(granted, error):
            if error:
                logger.error(f"EventKit error: {error}")
            self._authorized = bool(granted)
            if granted:
                self._store = EventKit.EKEventStore.alloc().init()
            else:
                if self.registry:
                    for sig in ("calendar_events", "calendar_attendees", "calendar_type"):
                        self.registry.set_status(sig, "no_permission", "Calendar access denied")
            done.set()

        store = EventKit.EKEventStore.alloc().init()
        store.requestAccessToEntityType_completion_(EventKit.EKEntityTypeEvent, handler)
        done.wait(timeout=30)
        if not self._authorized:
            logger.warning("Calendar access denied")

    def _sync_events(self):
        if self._store is None:
            return
        now = datetime.now()
        predicate = self._store.predicateForEventsWithStartDate_endDate_calendars_(
            self._to_nsdate(now - timedelta(days=1)),
            self._to_nsdate(now + timedelta(days=7)),
            None,
        )
        events = self._store.eventsMatchingPredicate_(predicate) or []
        synced = 0
        for ev in events:
            try:
                title    = str(ev.title() or "Untitled")
                start    = self._from_nsdate(ev.startDate())
                end      = self._from_nsdate(ev.endDate())
                duration = int((end - start).total_seconds() / 60)

                # Attendees
                attendees = ev.attendees() or []
                attendee_count = len(attendees)
                is_meeting = attendee_count > 0

                # Calendar source name
                cal = ev.calendar()
                source = str(cal.title() if cal else "") or ""

                self.storage.upsert_calendar_event(
                    self.session_id, title, start, end, duration,
                    attendee_count=attendee_count,
                    is_meeting=is_meeting,
                    calendar_source=source,
                )
                synced += 1
            except Exception as e:
                logger.debug(f"Skipping event: {e}")

        if self.registry and synced > 0:
            self.registry.record("calendar_events", synced)
            self.registry.record("calendar_attendees", synced)
            self.registry.record("calendar_type", synced)
        logger.debug(f"CalendarMonitor: synced {synced} events")

    @staticmethod
    def _to_nsdate(dt: datetime):
        import Foundation
        ref = datetime(2001, 1, 1)
        return Foundation.NSDate.dateWithTimeIntervalSinceReferenceDate_((dt - ref).total_seconds())

    @staticmethod
    def _from_nsdate(nsdate) -> datetime:
        from datetime import timedelta
        ref = datetime(2001, 1, 1)
        return ref + timedelta(seconds=nsdate.timeIntervalSinceReferenceDate())
