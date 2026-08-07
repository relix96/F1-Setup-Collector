from typing import ClassVar

from collector.base_collector import BaseCollector
from collector.ea_setup.ea_setup_scrapper import EASetupCollector
from collector.enums import GameId, SourceId
from collector.excel_file.f1_26.collector import ExcelFileF126Collector
from collector.f1_laps.f1_26.collector import F1LapsF126Collector
from collector.models.collectorData import CollectorKey


class CollectorFactory:
    _factory: ClassVar[dict[CollectorKey, type[BaseCollector]]] = {
        CollectorKey(game=GameId.F1_26, source=SourceId.F1_LAPS): F1LapsF126Collector,
        CollectorKey(game=GameId.F1_26, source=SourceId.EXCEL_FILE): ExcelFileF126Collector,
        #CollectorKey(game=GameId.F1_26, source=SourceId.EA_SETUP): EASetupCollector, => need a log in to access the EA setups page, so this collector is disabled for now.
    }

    @classmethod
    def get_collector_class(
        cls,
        game_id: GameId,
        source_id: SourceId,
    ) -> type[BaseCollector]:
        if not isinstance(game_id, GameId):
            raise TypeError("game_id must be a GameId")
        if not isinstance(source_id, SourceId):
            raise TypeError("source_id must be a SourceId")

        try:
            return cls._factory[CollectorKey(game_id, source_id)]
        except KeyError:
            raise ValueError(
                f"Collector not supported: {game_id.value}/{source_id.value}"
            ) from None

    @classmethod
    def create_collector(
        cls,
        game_id: GameId,
        source_id: SourceId,
    ) -> BaseCollector:
        """Create the collector registered for a game/source pair."""
        return cls.get_collector_class(game_id, source_id)()

    @classmethod
    def get_registered_keys(cls) -> tuple[CollectorKey, ...]:
        """Return all registered game/source pairs in registration order."""
        return tuple(cls._factory)
