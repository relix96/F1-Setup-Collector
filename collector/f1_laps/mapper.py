import datetime
from typing import Any, Dict

from collector.enums import SourceId
from collector.f1_laps.models import F1LapsSettings
from collector.mapper.base_mapper import BaseMapper
from collector.models.setup import SetupDTO


class F1SetupLapsMapper(BaseMapper):
    def map(self, item: Dict[str, Any]) -> SetupDTO:
        setup = item.get("setup")
        if setup is not None:
            setup = dict(setup)
            flat_settings = setup.get("settings") or {}
            setup["settings"] = F1LapsSettings.from_flat(
                flat_settings
            ).to_dict()
        if setup is not None or item.get("country") is not None:
            setup = {"country": item.get("country"), **(setup or {})}
        return SetupDTO(
            source=SourceId.F1_LAPS.value,
            source_id=str(item.get("id") or item.get("slug") or item.get("url")),
            game=item.get("game"),
            circuit=item.get("circuit") or item.get("track"),
            car=item.get("car"),
            platform=item.get("platform"),
            weather=item.get("weather"),
            setup=setup,
            source_url=item.get("url"),
            lap_date=datetime.datetime.now().isoformat(),
        )
