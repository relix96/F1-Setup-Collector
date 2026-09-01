from dataclasses import dataclass
from threading import Lock
import time

import pytest

from collector.collectorFactory import CollectorFactory
from collector.enums import GameId, SourceId
from collector.f1_laps.f1_26.collector import (
    F1LapsF126Collector,
    PartialCollectionError,
)
from collector.f1_laps.mapper import F1SetupLapsMapper


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

    def test_mapper_uses_registered_source_id(self) -> None:
        setup = F1SetupLapsMapper().map(
            {
                "id": "setup-1",
                "setup": {"date": "Aug. 30, 2026"},
            }
        ).to_dict()

        assert setup["source"] == SourceId.F1_LAPS.value
        assert setup["collector_date"]
        assert setup["setup"]["date"] == "Aug. 30, 2026"
        assert "lap_date" not in setup

    def test_mapper_groups_settings_like_the_site(self) -> None:
        setup = F1SetupLapsMapper().map(
            {
                "id": "setup-1",
                "country": "Australia",
                "setup": {
                    "user": "driver",
                    "settings": {
                        "front_wing": "50",
                        "rear_wing": "35",
                        "differential_on_throttle": "80%",
                        "differential_off_throttle": "50%",
                        "engine_braking": "35%",
                        "front_camber": "-3.50˚",
                        "rear_camber": "-2.00˚",
                        "front_toe": "0.00˚",
                        "rear_toe": "0.10˚",
                        "front_suspension": "41",
                        "rear_suspension": "32",
                        "front_anti_roll_bar": "1",
                        "rear_anti_roll_bar": "9",
                        "front_ride_height": "22",
                        "rear_ride_height": "40",
                        "brake_pressure": "100",
                        "front_brake_bias": "55",
                        "front_right_tyre_pressure": "29.5",
                        "front_left_tyre_pressure": "29.5",
                        "rear_right_tyre_pressure": "21.3",
                        "rear_left_tyre_pressure": "21.3",
                    },
                },
            }
        ).to_dict()

        assert setup["setup"]["country"] == "Australia"
        assert setup["setup"]["user"] == "driver"
        assert setup["setup"]["settings"] == {
            "aerodynamics": {
                "front_wing": "50",
                "rear_wing": "35",
            },
            "transmission": {
                "differential_on_throttle": "80%",
                "differential_off_throttle": "50%",
                "engine_braking": "35%",
            },
            "suspension_geometry": {
                "front_camber": "-3.50˚",
                "rear_camber": "-2.00˚",
                "front_toe": "0.00˚",
                "rear_toe": "0.10˚",
            },
            "suspension": {
                "front_suspension": "41",
                "rear_suspension": "32",
                "front_anti_roll_bar": "1",
                "rear_anti_roll_bar": "9",
                "front_ride_height": "22",
                "rear_ride_height": "40",
            },
            "brakes": {
                "brake_pressure": "100",
                "front_brake_bias": "55",
            },
            "tyres": {
                "front_right_tyre_pressure": "29.5",
                "front_left_tyre_pressure": "29.5",
                "rear_right_tyre_pressure": "21.3",
                "rear_left_tyre_pressure": "21.3",
            },
        }

    def test_f1_laps_collector_gets_all_tracks(self, monkeypatch: pytest.MonkeyPatch,) -> None:
        collector = self.get_collector()
        tracks_html = """
            <a href="/f1-26/setups/wet/">Wet setups</a>
            <a href="/f1-26/setups/australia/">Australia</a>
            <a href="/f1-26/setups/china/">China</a>
            <a href="/f1-26/setups/japan/">Japan</a>
            <a href="/f1-26/setups/bahrain/">Bahrain</a>
            <a href="/f1-26/setups/saudi_arabia/">Saudi Arabia</a>
            <a href="/f1-26/setups/las_vegas/">Las Vegas</a>
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
            "saudi_arabia",
            "las_vegas",
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

    def test_run_limits_parallel_track_workers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import collector.f1_laps.f1_26.collector as collector_module

        collector = self.get_collector()
        monkeypatch.setattr(collector_module, "COLLECTOR_CONCURRENCY", 2)
        monkeypatch.setattr(
            collector,
            "get_tracks",
            lambda: ["australia", "china", "japan", "bahrain"],
        )
        lock = Lock()
        active = 0
        maximum_active = 0

        def fake_get_setups(track_name: str, weather: str):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.01)
            yield {"circuit": track_name, "weather": weather}
            with lock:
                active -= 1

        monkeypatch.setattr(collector, "get_setups", fake_get_setups)

        results = list(collector.run())

        assert len(results) == 8
        assert maximum_active == 2

    def test_run_reports_failure_and_continues_with_remaining_tracks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import collector.f1_laps.f1_26.collector as collector_module

        collector = self.get_collector()
        calls = []
        monkeypatch.setattr(collector_module, "COLLECTOR_CONCURRENCY", 1)
        monkeypatch.setattr(
            collector,
            "get_tracks",
            lambda: ["australia", "china"],
        )

        def fake_get_setups(track_name: str, weather: str):
            calls.append((track_name, weather))
            if track_name == "australia" and weather == "dry":
                raise RuntimeError("fixture failure")
            yield {"circuit": track_name, "weather": weather}

        monkeypatch.setattr(collector, "get_setups", fake_get_setups)
        collected = []

        with caplog.at_level("INFO"), pytest.raises(
            PartialCollectionError,
            match="australia/dry:RuntimeError",
        ):
            for setup in collector.run():
                collected.append(setup)

        assert calls == [
            ("australia", "dry"),
            ("australia", "wet"),
            ("china", "dry"),
            ("china", "wet"),
        ]
        assert collected == [
            {"circuit": "australia", "weather": "wet"},
            {"circuit": "china", "weather": "dry"},
            {"circuit": "china", "weather": "wet"},
        ]
        assert (
            "Track collection error track=australia weather=dry "
            "error=RuntimeError"
        ) in caplog.text
        assert "Track collection finished track=china status=success" in caplog.text

    def test_parallel_run_reports_failure_after_other_tracks_finish(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import collector.f1_laps.f1_26.collector as collector_module

        collector = self.get_collector()
        monkeypatch.setattr(collector_module, "COLLECTOR_CONCURRENCY", 2)
        monkeypatch.setattr(
            collector,
            "get_tracks",
            lambda: ["australia", "china"],
        )

        def fake_get_setups(track_name: str, weather: str):
            if track_name == "australia" and weather == "dry":
                raise RuntimeError("parallel fixture failure")
            yield {"circuit": track_name, "weather": weather}

        monkeypatch.setattr(collector, "get_setups", fake_get_setups)
        collected = []

        with pytest.raises(PartialCollectionError):
            for setup in collector.run():
                collected.append((setup["circuit"], setup["weather"]))

        assert set(collected) == {
            ("australia", "wet"),
            ("china", "dry"),
            ("china", "wet"),
        }

    @pytest.mark.live
    def test_get_setups_by_track(self) -> None:
        collector = self.get_collector()
        setups = []

        for track in (
            "australia",
            "china",
            "japan",
            "bahrain",
            "saudi_arabia",
            "miami",
            "canada",
            "monaco",
        ):
            setups.extend(collector.get_setups_by_track(track))

        assert isinstance(setups, list)
