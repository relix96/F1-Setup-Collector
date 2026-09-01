"""Tests for the spreadsheet-backed F1 26 collector."""

import datetime
from dataclasses import dataclass
from unittest.mock import ANY

import pytest

from collector.collectorFactory import CollectorFactory
from collector.database import (
    DatabaseEnvironment,
    connect_database,
    is_guid,
    insert_record,
)
from collector.enums import GameId, SourceId
from collector.excel_file.f1_26.collector import ExcelFileF126Collector
from collector.excel_file.mapper import ExcelFileF126Mapper


@dataclass
class FakeResponse:
    text: str


CSV = """DO NOT REQUEST EDITOR ACCESS,,,,
Circuit,Aero,Differential,Susp. geometry,Suspension,Brakes,Tires Q,Tires R,Compounds,Strategy (50%),Fuel 50%,Laps 50%,Creation date,Notes
Australia,30-0q / 42-15r,100-45q 60r,LLLL,41-38-1-5-21-47,98/56,29.5 20.5,29.5 20.5,C3-C5,MH 11-13,27.5 laps / -1.9,29,24/06/2026,lico hell
China,50-22,100-65,LLLL,41-41-1-4-22-46,98/57,29.5 20.5,29.5 20.5,C2-C4,MH 10-12,,28,Theory,save ERS
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
    assert collector.ProxySupported is True


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
    collected_at = datetime.datetime.strptime(
        setups[0]["collector_date"], "%d/%m/%Y %H:%M:%S"
    )
    assert collected_at.date() == datetime.date.today()
    assert setups[0]["setup"]["aero"] == "30-0q / 42-15r"
    assert setups[0]["setup"]["notes"] == "lico hell"
    assert setups[0]["setup"]["fuel_50_percent"] == "27.5 laps / -1.9"
    assert [record["record_type"] for record in records[2:]] == [
        "tire_temperature",
        "tire_temperature",
        "engine_temperature",
        "engine_temperature",
    ]


def test_maps_fuel_50_percent() -> None:
    collector = get_collector()
    setups = [
        record for record in collector.run() if "record_type" not in record
    ]

    assert setups[0]["setup"]["fuel_50_percent"] == "27.5 laps / -1.9"
    assert setups[1]["setup"]["fuel_50_percent"] is None


def test_gets_all_setups_from_excel_file() -> None:
    records = list(get_collector().run())
    setups = [record for record in records if "record_type" not in record]

    assert len(setups) == 2
    assert [setup["circuit"] for setup in setups] == ["Australia", "China"]


@pytest.mark.live
def test_run_gets_all_real_setups_from_excel_file() -> None:
    collector = ExcelFileF126Collector()
    database_client, collection = connect_database(DatabaseEnvironment.SANDBOX)

    try:
        records = list(collector.run())
        setups = [record for record in records if "record_type" not in record]

        assert setups
        assert len(setups) == len(collector.get_tracks())
        assert all(setup["source"] == "excel_file" for setup in setups)
        assert all(setup["source_id"] for setup in setups)
        assert all(setup["circuit"] for setup in setups)

        for record in records:
            insert_record(collection, record)

        expected_source_ids = {record["source_id"] for record in records}
        saved_source_ids = {
            document["source_id"]
            for document in collection.find(
                {
                    "source": "excel_file",
                    "source_id": {"$in": list(expected_source_ids)},
                },
                {"_id": 0, "source_id": 1},
            )
        }

        assert saved_source_ids == expected_source_ids
        assert all(
            is_guid(document["_id"])
            for document in collection.find(
                {
                    "source": "excel_file",
                    "source_id": {"$in": list(expected_source_ids)},
                }
            )
        )
    finally:
        collector.close()
        database_client.close()


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
                "collector_date": ANY,
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
                "collector_date": ANY,
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
                "collector_date": ANY,
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
                "collector_date": ANY,
        },
    ]
