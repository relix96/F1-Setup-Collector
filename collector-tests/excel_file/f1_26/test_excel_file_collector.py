"""Tests for the spreadsheet-backed F1 26 collector."""

from dataclasses import dataclass

from collector.collectorFactory import CollectorFactory
from collector.enums import GameId, SourceId
from collector.excel_file.f1_26.collector import ExcelFileF126Collector
from collector.excel_file.mapper import ExcelFileF126Mapper


@dataclass
class FakeResponse:
    text: str


CSV = """DO NOT REQUEST EDITOR ACCESS,,,,
Circuit,Aero,Differential,Susp. geometry,Suspension,Brakes,Tires Q,Tires R,Compounds,Strategy (50%),Laps 50%,Creation date,Notes
Australia,30-0q / 42-15r,100-45q 60r,LLLL,41-38-1-5-21-47,98/56,29.5 20.5,29.5 20.5,C3-C5,MH 11-13,29,24/06/2026,lico hell
China,50-22,100-65,LLLL,41-41-1-4-22-46,98/57,29.5 20.5,29.5 20.5,C2-C4,MH 10-12,28,Theory,save ERS
,,,,,,,,,,,,
Tire Temperatures,,,,,,,,,,,,
Compound,Temp Range (°C),Temp Range (°F),,,,,,,,,,
C1,95 - 115,203 - 239,,,,,,,,,,
C2,85 - 115,185 - 239,,,,,,,,,,
,,,,,,,,,,,,
Engine temperatures,,,,,,,,,,,,
Temp (°C),Temp (°F),Power %,,,,,,,,,,
65,149,96,,,,,,,,,,
75,167,97,,,,,,,,,,
"""


def get_collector() -> ExcelFileF126Collector:
    collector_class = CollectorFactory.get_collector_class(
        GameId.F1_26, SourceId.EXCEL_FILE
    )
    collector = collector_class()
    collector.request_api = lambda *args, **kwargs: FakeResponse(CSV)
    return collector


def test_factory_returns_excel_file_collector() -> None:
    collector = get_collector()

    assert isinstance(collector, ExcelFileF126Collector)
    assert isinstance(collector.mapper, ExcelFileF126Mapper)


def test_get_tracks_ignores_tables_after_the_setup_table() -> None:
    assert get_collector().get_tracks() == ["Australia", "China"]


def test_run_maps_spreadsheet_setup() -> None:
    records = list(get_collector().run())
    setups = records[:2]

    assert len(setups) == 2
    assert setups[0]["source"] == "excel_file"
    assert setups[0]["source_id"] == "australia"
    assert setups[0]["game"] == "F1 26"
    assert setups[0]["weather"] == "dry"
    assert setups[0]["date"] == "24/06/2026"
    assert setups[0]["setup"]["aero"] == "30-0q / 42-15r"
    assert setups[0]["setup"]["notes"] == "lico hell"
    assert [record["record_type"] for record in records[2:]] == [
        "tire_temperature",
        "tire_temperature",
        "engine_temperature",
        "engine_temperature",
    ]


def test_get_setups_by_track_is_case_insensitive() -> None:
    setups = get_collector().get_setups_by_track("australia")

    assert len(setups) == 1
    assert setups[0]["circuit"] == "Australia"


def test_get_tire_temperatures() -> None:
    assert get_collector().get_tire_temperatures() == [
        {
            "record_type": "tire_temperature",
            "source": "excel_file",
            "source_id": "tire-temperature:c1",
            "game": "F1 26",
            "compound": "C1",
            "temperature_celsius": "95 - 115",
            "temperature_fahrenheit": "203 - 239",
            "source_url": ExcelFileF126Collector.spreadsheet_url,
        },
        {
            "record_type": "tire_temperature",
            "source": "excel_file",
            "source_id": "tire-temperature:c2",
            "game": "F1 26",
            "compound": "C2",
            "temperature_celsius": "85 - 115",
            "temperature_fahrenheit": "185 - 239",
            "source_url": ExcelFileF126Collector.spreadsheet_url,
        },
    ]


def test_get_engine_temperatures() -> None:
    assert get_collector().get_engine_temperatures() == [
        {
            "record_type": "engine_temperature",
            "source": "excel_file",
            "source_id": "engine-temperature:65c",
            "game": "F1 26",
            "temperature_celsius": "65",
            "temperature_fahrenheit": "149",
            "power_percent": "96",
            "source_url": ExcelFileF126Collector.spreadsheet_url,
        },
        {
            "record_type": "engine_temperature",
            "source": "excel_file",
            "source_id": "engine-temperature:75c",
            "game": "F1 26",
            "temperature_celsius": "75",
            "temperature_fahrenheit": "167",
            "power_percent": "97",
            "source_url": ExcelFileF126Collector.spreadsheet_url,
        },
    ]
