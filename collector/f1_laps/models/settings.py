from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping, Optional, Type, TypeVar


@dataclass
class Aerodynamics:
    front_wing: Optional[str] = None
    rear_wing: Optional[str] = None


@dataclass
class Transmission:
    differential_on_throttle: Optional[str] = None
    differential_off_throttle: Optional[str] = None


@dataclass
class SuspensionGeometry:
    front_camber: Optional[str] = None
    rear_camber: Optional[str] = None
    front_toe: Optional[str] = None
    rear_toe: Optional[str] = None


@dataclass
class Suspension:
    front_suspension: Optional[str] = None
    rear_suspension: Optional[str] = None
    front_anti_roll_bar: Optional[str] = None
    rear_anti_roll_bar: Optional[str] = None
    front_ride_height: Optional[str] = None
    rear_ride_height: Optional[str] = None


@dataclass
class Brakes:
    brake_pressure: Optional[str] = None
    front_brake_bias: Optional[str] = None


@dataclass
class Tyres:
    front_right_tyre_pressure: Optional[str] = None
    front_left_tyre_pressure: Optional[str] = None
    rear_right_tyre_pressure: Optional[str] = None
    rear_left_tyre_pressure: Optional[str] = None


SettingsSection = TypeVar("SettingsSection")


def _section_from_flat(
    section_type: Type[SettingsSection],
    values: Mapping[str, Any],
) -> SettingsSection:
    section_values = {
        field.name: values.get(field.name)
        for field in fields(section_type)
    }
    return section_type(**section_values)


@dataclass
class F1LapsSettings:
    aerodynamics: Aerodynamics
    transmission: Transmission
    suspension_geometry: SuspensionGeometry
    suspension: Suspension
    brakes: Brakes
    tyres: Tyres

    @classmethod
    def from_flat(cls, values: Mapping[str, Any]) -> "F1LapsSettings":
        """Build the site section model from the scraper's flat label map."""
        return cls(
            aerodynamics=_section_from_flat(Aerodynamics, values),
            transmission=_section_from_flat(Transmission, values),
            suspension_geometry=_section_from_flat(SuspensionGeometry, values),
            suspension=_section_from_flat(Suspension, values),
            brakes=_section_from_flat(Brakes, values),
            tyres=_section_from_flat(Tyres, values),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
