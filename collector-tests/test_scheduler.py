from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from collector.scheduler import (
    CollectorScheduler,
    SchedulerConfigurationError,
    latest_slot,
    next_slot,
    parse_schedule_hours,
    seconds_until,
)


LISBON = ZoneInfo("Europe/Lisbon")


def test_parses_and_orders_unique_schedule_hours() -> None:
    assert parse_schedule_hours("18, 6,18") == (6, 18)


@pytest.mark.parametrize("value", ["", "six", "-1,18", "6,24"])
def test_rejects_invalid_schedule_hours(value) -> None:
    with pytest.raises(SchedulerConfigurationError):
        parse_schedule_hours(value)


def test_calculates_latest_and_next_slots_in_lisbon_time() -> None:
    now = datetime(2026, 9, 1, 12, 30, tzinfo=LISBON)

    assert latest_slot(now, (6, 18)) == datetime(
        2026, 9, 1, 6, 0, tzinfo=LISBON
    )
    assert next_slot(now, (6, 18)) == datetime(
        2026, 9, 1, 18, 0, tzinfo=LISBON
    )


def test_wait_duration_accounts_for_lisbon_daylight_saving_changes() -> None:
    before_spring_change = datetime(2026, 3, 28, 18, 0, tzinfo=LISBON)
    before_autumn_change = datetime(2026, 10, 24, 18, 0, tzinfo=LISBON)

    assert seconds_until(
        before_spring_change,
        next_slot(before_spring_change, (6, 18)),
    ) == 11 * 60 * 60
    assert seconds_until(
        before_autumn_change,
        next_slot(before_autumn_change, (6, 18)),
    ) == 13 * 60 * 60


def test_runs_missed_slot_once_and_persists_success(tmp_path) -> None:
    calls = []
    now = datetime(2026, 9, 1, 7, 0, tzinfo=LISBON)
    scheduler = CollectorScheduler(
        timezone=LISBON,
        hours=(6, 18),
        state_file=tmp_path / "last-slot",
        failure_retry_seconds=900,
        runner=lambda: calls.append("run") or 0,
        clock=lambda: now,
    )

    first_delay = scheduler.tick()
    second_delay = scheduler.tick()

    assert calls == ["run"]
    assert first_delay == second_delay == 11 * 60 * 60
    assert scheduler.state_file.read_text(encoding="utf-8") == (
        "2026-09-01T06:00:00+01:00"
    )


def test_failed_slot_is_not_marked_and_uses_retry_delay(tmp_path) -> None:
    scheduler = CollectorScheduler(
        timezone=LISBON,
        hours=(6, 18),
        state_file=tmp_path / "last-slot",
        failure_retry_seconds=123,
        runner=lambda: 1,
        clock=lambda: datetime(2026, 9, 1, 7, 0, tzinfo=LISBON),
    )

    assert scheduler.tick() == 123
    assert not scheduler.state_file.exists()


def test_requests_immediate_tick_when_collection_crosses_next_slot(
    tmp_path,
) -> None:
    times = iter(
        [
            datetime(2026, 9, 1, 17, 59, tzinfo=LISBON),
            datetime(2026, 9, 1, 18, 1, tzinfo=LISBON),
        ]
    )
    scheduler = CollectorScheduler(
        timezone=LISBON,
        hours=(6, 18),
        state_file=tmp_path / "last-slot",
        failure_retry_seconds=900,
        runner=lambda: 0,
        clock=lambda: next(times),
    )

    assert scheduler.tick() == 1
    assert scheduler.state_file.read_text(encoding="utf-8") == (
        "2026-09-01T06:00:00+01:00"
    )
