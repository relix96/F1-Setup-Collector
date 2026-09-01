"""Run the collector at fixed local-time slots inside a long-lived container."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import signal
from threading import Event
from typing import Callable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from collector.utils.logger import get_logger
from main import run as run_collectors


logger = get_logger(__name__)


class SchedulerConfigurationError(ValueError):
    """Raised when the scheduler environment is invalid."""


def parse_schedule_hours(value: str) -> tuple[int, ...]:
    try:
        hours = tuple(sorted({int(part.strip()) for part in value.split(",")}))
    except ValueError as error:
        raise SchedulerConfigurationError(
            "COLLECTOR_SCHEDULE_HOURS must contain comma-separated hours"
        ) from error
    if not hours or any(hour < 0 or hour > 23 for hour in hours):
        raise SchedulerConfigurationError(
            "COLLECTOR_SCHEDULE_HOURS must contain values from 0 to 23"
        )
    return hours


def latest_slot(now: datetime, hours: Sequence[int]) -> datetime:
    for hour in reversed(hours):
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= now:
            return candidate
    previous_day = now - timedelta(days=1)
    return previous_day.replace(
        hour=hours[-1],
        minute=0,
        second=0,
        microsecond=0,
    )


def next_slot(now: datetime, hours: Sequence[int]) -> datetime:
    for hour in hours:
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > now:
            return candidate
    next_day = now + timedelta(days=1)
    return next_day.replace(
        hour=hours[0],
        minute=0,
        second=0,
        microsecond=0,
    )


def seconds_until(now: datetime, target: datetime) -> float:
    """Return elapsed seconds, accounting for daylight-saving transitions."""

    return (
        target.astimezone(UTC) - now.astimezone(UTC)
    ).total_seconds()


@dataclass
class CollectorScheduler:
    timezone: ZoneInfo
    hours: tuple[int, ...]
    state_file: Path
    failure_retry_seconds: int
    runner: Callable[[], int] = run_collectors
    clock: Callable[[], datetime] | None = None

    def _now(self) -> datetime:
        if self.clock is not None:
            return self.clock()
        return datetime.now(self.timezone)

    @staticmethod
    def _slot_id(slot: datetime) -> str:
        return slot.isoformat()

    def _last_successful_slot(self) -> str | None:
        try:
            value = self.state_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        return value or None

    def _record_success(self, slot: datetime) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(self._slot_id(slot), encoding="utf-8")
        temporary.replace(self.state_file)

    def tick(self) -> float:
        """Run an overdue slot once and return seconds until the next action."""

        now = self._now()
        due = latest_slot(now, self.hours)
        if self._last_successful_slot() != self._slot_id(due):
            logger.info(
                "Starting scheduled collection slot=%s timezone=%s",
                self._slot_id(due),
                self.timezone.key,
            )
            status = self.runner()
            if status == 0:
                self._record_success(due)
                logger.info("Scheduled collection completed slot=%s", self._slot_id(due))
                now = self._now()
                if self._slot_id(latest_slot(now, self.hours)) != self._slot_id(due):
                    # The run crossed another scheduled boundary. Loop again
                    # immediately so that the newer slot is not skipped.
                    return 1.0
            else:
                logger.error(
                    "Scheduled collection failed slot=%s exit=%s; retry_in=%ss",
                    self._slot_id(due),
                    status,
                    self.failure_retry_seconds,
                )
                return float(self.failure_retry_seconds)

        upcoming = next_slot(now, self.hours)
        delay = max(1.0, seconds_until(now, upcoming))
        logger.info(
            "Next scheduled collection slot=%s wait_seconds=%d",
            self._slot_id(upcoming),
            round(delay),
        )
        return delay

    def run_forever(self, stop: Event) -> None:
        logger.info(
            "Collector scheduler ready hours=%s timezone=%s",
            ",".join(f"{hour:02d}:00" for hour in self.hours),
            self.timezone.key,
        )
        while not stop.is_set():
            try:
                delay = self.tick()
            except Exception:
                logger.exception(
                    "Unexpected scheduler error; retrying in %ss",
                    self.failure_retry_seconds,
                )
                delay = float(self.failure_retry_seconds)
            stop.wait(delay)
        logger.info("Collector scheduler stopped")


def build_scheduler() -> CollectorScheduler:
    timezone_name = os.getenv("COLLECTOR_TIMEZONE", "Europe/Lisbon")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise SchedulerConfigurationError(
            f"unknown COLLECTOR_TIMEZONE: {timezone_name}"
        ) from error

    retry_seconds = int(os.getenv("COLLECTOR_FAILURE_RETRY_SECONDS", "900"))
    if retry_seconds < 1:
        raise SchedulerConfigurationError(
            "COLLECTOR_FAILURE_RETRY_SECONDS must be positive"
        )
    return CollectorScheduler(
        timezone=timezone,
        hours=parse_schedule_hours(
            os.getenv("COLLECTOR_SCHEDULE_HOURS", "6,18")
        ),
        state_file=Path(
            os.getenv(
                "COLLECTOR_SCHEDULER_STATE_FILE",
                "/var/lib/setup-collector/last-successful-slot",
            )
        ),
        failure_retry_seconds=retry_seconds,
    )


def main() -> None:
    stop = Event()

    def request_stop(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    build_scheduler().run_forever(stop)


if __name__ == "__main__":
    main()
