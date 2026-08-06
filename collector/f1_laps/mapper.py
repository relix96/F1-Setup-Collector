from typing import Any, Dict

from collector.mapper.base_mapper import BaseMapper
from collector.models.setup import SetupDTO


class F1SetupLapsMapper(BaseMapper):
    def map(self, item: Dict[str, Any]) -> SetupDTO:
        setup = item.get("setup")
        if setup is not None or item.get("country") is not None:
            setup = {"country": item.get("country"), **(setup or {})}
        return SetupDTO(
            source="f1_setup_laps",
            source_id=str(item.get("id") or item.get("slug") or item.get("url")),
            game=item.get("game"),
            circuit=item.get("circuit") or item.get("track"),
            car=item.get("car"),
            platform=item.get("platform"),
            weather=item.get("weather"),
            setup=setup,
            source_url=item.get("url"),
        )

    DETAIL_LABELS = {
    "Team": "team",
    "Session": "session",
    "Lap time": "lap_time",
    "Conditions": "conditions",
    "Steering": "steering",
    "Date": "date",
    "Traction Control": "traction_control",
    "Anti-Lock Brakes": "anti_lock_brakes",
    "Steering Assist": "steering_assist",
    "Braking Assist": "braking_assist",
    "Gearbox": "gearbox",
    "Racing Line": "racing_line",
    }

    SETTING_LABELS = {
    "Front Wing": "front_wing",
    "Rear Wing": "rear_wing",
    "Differential Adjustment On Throttle": "differential_on_throttle",
    "Differential Adjustment Off Throttle": "differential_off_throttle",
    "Front Camber": "front_camber",
    "Rear Camber": "rear_camber",
    "Front Toe": "front_toe",
    "Rear Toe": "rear_toe",
    "Front Suspension": "front_suspension",
    "Rear Suspension": "rear_suspension",
    "Front Anti-Roll Bar": "front_anti_roll_bar",
    "Rear Anti-Roll Bar": "rear_anti_roll_bar",
    "Front Ride Height": "front_ride_height",
    "Rear Ride Height": "rear_ride_height",
    # F1Laps currently spells these two labels as "Break".
    "Break Pressure": "brake_pressure",
    "Brake Pressure": "brake_pressure",
    "Front Break Bias": "front_brake_bias",
    "Front Brake Bias": "front_brake_bias",
    "Front Right Tyre Pressure": "front_right_tyre_pressure",
    "Front Left Tyre Pressure": "front_left_tyre_pressure",
    "Rear Right Tyre Pressure": "rear_right_tyre_pressure",
    "Rear Left Tyre Pressure": "rear_left_tyre_pressure",
    }

