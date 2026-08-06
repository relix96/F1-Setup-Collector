from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Iterator, List

from collector.settings import REQUESTS_PER_MINUTE
from collector.utils.http_scrapper import HttpScrapper


from abc import ABC, abstractmethod
from typing import Any, ClassVar, Iterator

from collector.enums import GameId, SourceId
from collector.settings import REQUESTS_PER_MINUTE
from collector.utils.http_scrapper import HttpScrapper
from collector.enums import SourceId, GameId


class BaseCollector(HttpScrapper, ABC):
    GameId: ClassVar[GameId]
    SourceId: ClassVar[SourceId]

    def __init__(self, requests_per_minute: int = REQUESTS_PER_MINUTE,) -> None:
        if not isinstance(type(self).GameId, GameId):
            raise TypeError(f"{type(self).__name__}.GameId must be a GameId")

        if not isinstance(type(self).SourceId, SourceId):
            raise TypeError(f"{type(self).__name__}.SourceId must be a SourceId")

        super().__init__(requests_per_minute=requests_per_minute)

    @abstractmethod
    def run(self) -> Iterator[dict[str, Any]]:
        pass

    @abstractmethod
    def get_setups_by_track(self, track_name: str,) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def get_tracks(self) -> list[str]:
        pass

