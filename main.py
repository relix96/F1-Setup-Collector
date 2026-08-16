import argparse
from typing import Any, Optional

from collector.collectorFactory import CollectorFactory
from collector.database import DatabaseEnvironment, connect_database, upsert_record
from collector.enums import GameId, SourceId
from collector.utils.logger import get_logger

logger = get_logger(__name__)


def run_source(game_id: GameId, source_id: SourceId, collection: Optional[Any] = None,) -> None:
    logger.info("Starting collector: %s/%s", game_id.value, source_id.value)
    collector = CollectorFactory.create_collector(game_id, source_id)
    try:
        for item in collector.run():
            if collection is not None:
                upsert_record(collection, item)
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

    # The application always writes to the production server. Tests select their
    # own profile through TEST_MONGODB_ENV in collector.database.
    client, collection = connect_database(DatabaseEnvironment.PRODUCTION)
    try:
        for key in collector_keys:
            try:
                run_source(key.game, key.source, collection)
            except Exception:
                # One unavailable website must not prevent the remaining collectors.
                logger.exception("Collector failed: %s/%s", key.game.value, key.source.value)
    finally:
        client.close()



if __name__ == "__main__":
    run()
