import argparse

from collector.collectorFactory import CollectorFactory
from collector.enums import GameId, SourceId
from collector.utils.logger import get_logger

logger = get_logger(__name__)


def run_source(game_id: GameId, source_id: SourceId) -> None:
    """Create and run one collector through ``CollectorFactory``."""
    logger.info("Starting collector: %s/%s", game_id.value, source_id.value)
    collector = CollectorFactory.create_collector(game_id, source_id)
    try:
        for item in collector.run():
            # Replace this with a database, JSONL or queue writer when the output is defined.
            print(item)
    finally:
        collector.close()


def run() -> None:
    """Parse command-line options and run one or every collector."""
    parser = argparse.ArgumentParser(description="Collect Formula 1 setups")
    parser.add_argument("--game", choices=[game.value for game in GameId])
    parser.add_argument("--source", choices=[source.value for source in SourceId])
    args = parser.parse_args()

    selected_game = GameId(args.game) if args.game else None
    selected_source = SourceId(args.source) if args.source else None
    collector_keys = [
        key
        for key in CollectorFactory.get_registered_keys()
        if (selected_game is None or key.game is selected_game)
        and (selected_source is None or key.source is selected_source)
    ]

    for key in collector_keys:
        try:
            run_source(key.game, key.source)
        except Exception:
            # One unavailable website must not prevent the remaining collectors.
            logger.exception("Collector failed: %s/%s", key.game.value, key.source.value)



if __name__ == "__main__":
    run()
