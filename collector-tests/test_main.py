import sys

import pytest

import main
from collector.enums import GameId, SourceId


def test_run_source_runs_prints_and_closes_collector(
    monkeypatch,
    capsys,
) -> None:
    events = []

    class FakeCollector:
        def __init__(self) -> None:
            events.append("created")

        def run(self):
            events.append("run")
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

    assert events == ["created", "run", "closed"]
    assert capsys.readouterr().out.splitlines() == [
        "{'track': 'australia', 'weather': 'dry'}",
        "{'track': 'australia', 'weather': 'wet'}",
    ]


def test_run_uses_source_from_command_line(monkeypatch) -> None:
    called_sources = []
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "f1_laps"])

    def fake_run_source(game_id, source_id) -> None:
        called_sources.append((game_id, source_id))

    monkeypatch.setattr(main, "run_source", fake_run_source)

    main.run()

    assert called_sources == [(GameId.F1_26, SourceId.F1_LAPS)]


@pytest.mark.live
def test_run_scrapes_all_collectors(monkeypatch) -> None:
    """Run every registered collector against its real website."""
    monkeypatch.setattr(sys, "argv", ["main.py"])

    main.run()
