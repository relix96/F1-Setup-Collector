from typing import Any, Dict

from collector.mapper.base_mapper import BaseMapper
from collector.models.setup import SetupDTO


class EASetupMapper(BaseMapper):
    def map(self, item: Dict[str, Any]) -> SetupDTO:
        return SetupDTO(
            source="ea_setup",
            source_id=str(item.get("id") or item.get("slug") or item.get("url")),
            game=item.get("game"),
            circuit=item.get("circuit") or item.get("track"),
            car=item.get("car"),
            platform=item.get("platform"),
            weather=item.get("weather"),
            setup=item.get("setup"),
            source_url=item.get("url"),
        )
