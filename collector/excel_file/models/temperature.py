from dataclasses import asdict, dataclass
from typing import Dict


@dataclass
class TireTemperatureDTO:
    record_type: str
    source: str
    source_id: str
    game: str
    compound: str
    temperature_celsius: str
    temperature_fahrenheit: str
    source_url: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class EngineTemperatureDTO:
    record_type: str
    source: str
    source_id: str
    game: str
    temperature_celsius: str
    temperature_fahrenheit: str
    power_percent: str
    source_url: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)
