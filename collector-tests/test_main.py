import sys

import pytest

import main
from collector.database import connect_database, get_test_database_environment
from collector.enums import GameId, SourceId


def test_run_source_runs_prints_and_closes_collector(
    monkeypatch,
    capsys,
) -> None:
    events = []
    monkeypatch.setattr(main, "COLLECTOR_LOG_RECORDS", True)

    class FakeCollector:
        def __init__(self) -> None:
            events.append("created")

        def run(self):
            events.append(f"run:{self.collector_run_id}")
            yield {"track": "australia", "weather": "dry"}
            yield {"track": "australia", "weather": "wet"}

        def close(self) -> None:
            events.append("closed")

    monkeypatch.setattr(
        main.CollectorFactory,
        "create_collector",
        lambda game_id, source_id: FakeCollector(),
    )

    main.run_source(GameId.F1_26, SourceId.F1_LAPS)

    assert events[0] == "created"
    assert events[1].startswith("run:")
    assert events[1] != "run:None"
    assert events[2] == "closed"
    assert capsys.readouterr().out.splitlines() == [
        "{'track': 'australia', 'weather': 'dry'}",
        "{'track': 'australia', 'weather': 'wet'}",
    ]


def test_run_source_inserts_every_collected_item(monkeypatch) -> None:
    class FakeCollector:
        def run(self):
            yield {"source": "excel_file", "source_id": "australia"}
            yield {"source": "excel_file", "source_id": "china"}

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        main.CollectorFactory,
        "create_collector",
        lambda game_id, source_id: FakeCollector(),
    )
    calls = []
    collection = object()
    monkeypatch.setattr(
        main,
        "insert_record",
        lambda target, item: calls.append((target, item)),
    )

    main.run_source(
        GameId.F1_26,
        SourceId.EXCEL_FILE,
        collection,
        collector_run_id="run-test",
    )

    assert [target for target, _ in calls] == [collection, collection]
    assert [item["source_id"] for _, item in calls] == ["australia", "china"]
    assert all(item["collector_run_id"] == "run-test" for _, item in calls)
    assert all(item["collector_date"].tzinfo is not None for _, item in calls)


def test_run_source_prints_unicode_safely(monkeypatch, capsys) -> None:
    monkeypatch.setattr(main, "COLLECTOR_LOG_RECORDS", True)

    class FakeCollector:
        def run(self):
            yield {"front_camber": "-3.50˚"}

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        main.CollectorFactory,
        "create_collector",
        lambda game_id, source_id: FakeCollector(),
    )

    main.run_source(GameId.F1_26, SourceId.F1_LAPS)

    assert capsys.readouterr().out.strip() == "{'front_camber': '-3.50\\u02da'}"


def test_run_source_logs_human_readable_collector_and_summary(
    monkeypatch,
    caplog,
) -> None:
    class FakeCollector:
        def run(self):
            yield {"source": "f1_laps"}

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        main.CollectorFactory,
        "create_collector",
        lambda game_id, source_id: FakeCollector(),
    )

    with caplog.at_level("INFO"):
        main.run_source(
            GameId.F1_26,
            SourceId.F1_LAPS,
            collector_run_id="visible-run",
        )

    assert "Collector started collector=F1Laps -> F1 26 run_id=visible-run" in caplog.text
    assert "status=success records=1" in caplog.text


def test_run_uses_source_from_command_line(monkeypatch) -> None:
    called_sources = []
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "f1_laps"])

    class FakeClient:
        def close(self) -> None:
            pass

    collection = object()
    monkeypatch.setattr(
        main,
        "connect_database",
        lambda environment: (FakeClient(), collection),
    )

    def fake_run_source(
        game_id,
        source_id,
        collection,
        collector_run_id=None,
        publisher=None,
    ) -> None:
        called_sources.append(
            (game_id, source_id, collection, collector_run_id)
        )

    monkeypatch.setattr(main, "run_source", fake_run_source)

    assert main.run() == 0

    assert len(called_sources) == 1
    assert called_sources[0][:2] == (GameId.F1_26, SourceId.F1_LAPS)
    assert called_sources[0][2] is collection
    assert called_sources[0][3]


def test_run_returns_failure_when_a_collector_fails(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py"])

    class FakeClient:
        def close(self) -> None:
            pass

    monkeypatch.setattr(
        main,
        "connect_database",
        lambda environment: (FakeClient(), object()),
    )
    monkeypatch.setattr(
        main,
        "run_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failed")),
    )

    assert main.run() == 1


def test_run_logs_structured_summary_and_collector_error(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py"])

    class FakeClient:
        def close(self) -> None:
            pass

    monkeypatch.setattr(
        main,
        "connect_database",
        lambda environment: (FakeClient(), object()),
    )
    monkeypatch.setattr(
        main,
        "run_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failed")),
    )

    with caplog.at_level("INFO"):
        assert main.run() == 1

    assert "event=collection_run_started" in caplog.text
    assert "event=collector_error" in caplog.text
    assert "collector=" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "event=collection_run_finished" in caplog.text
    assert "started_at=" in caplog.text
    assert "finished_at=" in caplog.text
    assert "status=failed" in caplog.text
    assert "duration_seconds=" in caplog.text


def test_run_uses_collector_run_id_from_environment(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "f1_laps"])
    monkeypatch.setenv("COLLECTOR_RUN_ID", "scheduled-run")

    class FakeClient:
        def close(self) -> None:
            pass

    monkeypatch.setattr(
        main,
        "connect_database",
        lambda environment: (FakeClient(), object()),
    )
    run_ids = []
    monkeypatch.setattr(
        main,
        "run_source",
        lambda *args, **kwargs: run_ids.append(kwargs["collector_run_id"]),
    )

    assert main.run() == 0
    assert run_ids == ["scheduled-run"]


@pytest.mark.live
def test_run_scrapes_all_collectors(monkeypatch) -> None:
    """Run every registered collector against its real website."""
    monkeypatch.setattr(sys, "argv", ["main.py"])
    test_environment = get_test_database_environment()
    monkeypatch.setattr(
        main,
        "connect_database",
        lambda production_environment: connect_database(test_environment),
    )

    main.run()
