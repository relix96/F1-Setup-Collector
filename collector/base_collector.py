from abc import ABC, abstractmethod
from typing import Any, ClassVar, Iterator

from collector.enums import GameId, SourceId
from collector.settings import PROXY_ENABLED, REQUESTS_PER_MINUTE
from collector.utils.http_scrapper import HttpScrapper


class BaseCollector(HttpScrapper, ABC):
    GameId: ClassVar[GameId]
    SourceId: ClassVar[SourceId]
    # Technical allow-list only. This flag does not establish permission from
    # the source; operators must verify that separately before opting in.
    ProxySupported: ClassVar[bool] = False

    def __init__(self, requests_per_minute: int = REQUESTS_PER_MINUTE) -> None:
        if not isinstance(type(self).GameId, GameId):
            raise TypeError(f"{type(self).__name__}.GameId must be a GameId")
        if not isinstance(type(self).SourceId, SourceId):
            raise TypeError(f"{type(self).__name__}.SourceId must be a SourceId")

        super().__init__(
            requests_per_minute=requests_per_minute,
            proxy_enabled=PROXY_ENABLED and type(self).ProxySupported,
        )
        self.collector_run_id: str | None = None

    @abstractmethod
    def run(self) -> Iterator[dict[str, Any]]:
        pass

    @abstractmethod
    def get_setups_by_track(self, track_name: str) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def get_tracks(self) -> list[str]:
        pass
