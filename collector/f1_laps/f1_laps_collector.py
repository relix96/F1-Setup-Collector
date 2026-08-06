from typing import ClassVar, Dict

from collector.base_collector import BaseCollector
from collector.enums import SourceId
from collector.f1_laps.mapper import F1SetupLapsMapper


class F1LapsCollector(BaseCollector):
    SourceId = SourceId.F1_LAPS
    base_url: ClassVar[str] = "https://www.f1laps.com/"

    def __init__(self) -> None:
        super().__init__()
        self.mapper = F1SetupLapsMapper()
        self._tracks: Dict[str, Dict[str, str]] = {}
