from typing import Any, ClassVar

from collector.mapper.base_mapper import BaseMapper
from collector.models.setup import SetupDTO
from collector.excel_file.models.temperature import EngineTemperatureDTO, TireTemperatureDTO


class ExcelFileF126Mapper(BaseMapper):
    """Map every table exposed by the F1 26 spreadsheet."""

    setup_fields: ClassVar[dict[str, str]] = {
        "Aero": "aero",
        "Differential": "differential",
        "Susp. geometry": "suspension_geometry",
        "Suspension": "suspension",
        "Brakes": "brakes",
        "Tires Q": "tyres_qualifying",
        "Tires R": "tyres_race",
        "Compounds": "compounds",
        "Strategy (50%)": "strategy_50_percent",
        "Laps 50%": "laps_50_percent",
        "Creation date": "creation_date",
        "Notes": "notes",
    }

    def __init__(self, source_url: str) -> None:
        self.source_url = source_url

    def map(self, item: dict[str, Any]) -> SetupDTO:
        circuit = item["Circuit"]
        setup = {
            destination: item.get(source) or None
            for source, destination in self.setup_fields.items()
        }
        return SetupDTO(
            source="excel_file",
            source_id=circuit.lower().replace(" ", "-"),
            game="F1 26",
            circuit=circuit,
            weather="dry",
            setup=setup,
            source_url=self.source_url,
            date=item.get("Creation date") or None,
        )

    def map_tire_temperature(
        self, item: dict[str, str]
    ) -> TireTemperatureDTO:
        compound = item.get("Compound", "")
        return TireTemperatureDTO(
            record_type="tire_temperature",
            source="excel_file",
            source_id=f"tire-temperature:{compound.casefold().replace(' ', '-')}",
            game="F1 26",
            compound=compound,
            temperature_celsius=item.get("Temp Range (°C)", ""),
            temperature_fahrenheit=item.get("Temp Range (°F)", ""),
            source_url=self.source_url,
        )

    def map_engine_temperature(
        self, item: dict[str, str]
    ) -> EngineTemperatureDTO:
        temperature_celsius = item.get("Temp (°C)", "")
        return EngineTemperatureDTO(
            record_type="engine_temperature",
            source="excel_file",
            source_id=f"engine-temperature:{temperature_celsius}c",
            game="F1 26",
            temperature_celsius=temperature_celsius,
            temperature_fahrenheit=item.get("Temp (°F)", ""),
            power_percent=item.get("Power %", ""),
            source_url=self.source_url,
        )

    def map_tire_temperatures(
        self, items: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        return [self.map_tire_temperature(item).to_dict() for item in items]

    def map_engine_temperatures(
        self, items: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        return [self.map_engine_temperature(item).to_dict() for item in items]

    def map_reference_data(
        self,
        tire_temperatures: list[dict[str, str]],
        engine_temperatures: list[dict[str, str]],
    ) -> dict[str, list[dict[str, str]]]:
        return {
            "tire_temperatures": self.map_tire_temperatures(tire_temperatures),
            "engine_temperatures": self.map_engine_temperatures(
                engine_temperatures
            ),
        }
