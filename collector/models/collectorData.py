from dataclasses import dataclass
from collector.enums import GameId, SourceId


@dataclass(frozen=True)
class CollectorKey:
    game: GameId
    source: SourceId