from dataclasses import dataclass

import pytest

from collector.collectorFactory import CollectorFactory
from collector.enums import GameId, SourceId
from collector.f1_laps.f1_26.collector import F1LapsF126Collector


@dataclass
class FakeResponse:
    text: str


class F1Laps_F1_26_CollectorTest:
    __test__ = True

    @staticmethod
    def get_collector() -> F1LapsF126Collector:
        collector_class = CollectorFactory.get_collector_class(GameId.F1_26, SourceId.F1_LAPS,)
        return collector_class()

    def test_factory_returns_f1_laps_f1_26_collector(self) -> None:
        collector = self.get_collector()

        assert isinstance(collector, F1LapsF126Collector)
        assert collector.GameId is GameId.F1_26
        assert collector.SourceId is SourceId.F1_LAPS

    def test_f1_laps_collector_gets_all_tracks(self, monkeypatch: pytest.MonkeyPatch,) -> None:
        collector = self.get_collector()
        tracks_html = """
            <a href="/f1-26/setups/australia/">Australia</a>
            <a href="/f1-26/setups/china/">China</a>
            <a href="/f1-26/setups/japan/">Japan</a>
            <a href="/f1-26/setups/bahrain/">Bahrain</a>
            <a href="/f1-26/setups/">all</a>
        """
        calls = []

        def fake_request(url: str, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(tracks_html)

        monkeypatch.setattr(collector, "request_api", fake_request)

        assert collector.get_tracks() == [
            "australia",
            "china",
            "japan",
            "bahrain",
        ]
        assert calls == [
            (
                collector.game_url,
                {"method": "GET", "json_response": False},
            )
        ]

    def test_f1_laps_collector_run_processes_every_track_and_weather(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        collector = self.get_collector()
        setup_calls = []
        monkeypatch.setattr(
            collector,
            "get_tracks",
            lambda: ["australia", "china"],
        )

        def fake_get_setups(track_name: str, weather: str):
            setup_calls.append((track_name, weather))
            yield {"circuit": track_name, "weather": weather}

        monkeypatch.setattr(collector, "get_setups", fake_get_setups)

        assert list(collector.run()) == [
            {"circuit": "australia", "weather": "dry"},
            {"circuit": "australia", "weather": "wet"},
            {"circuit": "china", "weather": "dry"},
            {"circuit": "china", "weather": "wet"},
        ]
        assert setup_calls == [
            ("australia", "dry"),
            ("australia", "wet"),
            ("china", "dry"),
            ("china", "wet"),
        ]

    @pytest.mark.live
    def test_get_setups_by_track(self) -> None:
        collector = self.get_collector()
        setups = []

        for track in ("australia", "china", "japan", "bahrain"):
            setups.extend(collector.get_setups_by_track(track))

        assert isinstance(setups, list)
