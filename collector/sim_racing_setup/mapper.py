import datetime
from typing import Any, Dict

from collector.enums import SourceId
from collector.f1_laps.models import F1LapsSettings
from collector.mapper.base_mapper import BaseMapper
from collector.models.setup import SetupDTO


class SimRacingSetupMapper(BaseMapper):
    """Map Sim Racing Setup pages into the shared raw setup contract."""

    def map(self, item: Dict[str, Any]) -> SetupDTO:
        setup = dict(item.get("setup") or {})
        setup["settings"] = F1LapsSettings.from_flat(
            setup.get("settings") or {}
        ).to_dict()
        return SetupDTO(
            source=SourceId.SIM_RACING_SETUP.value,
            source_id=str(item["id"]),
            game=item.get("game"),
            circuit=item.get("circuit"),
            car=item.get("car"),
            platform=item.get("platform"),
            weather=item.get("weather"),
            setup=setup,
            source_url=item.get("url"),
            collector_date=datetime.datetime.now().isoformat(),
        )
