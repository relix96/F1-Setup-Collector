import argparse
from datetime import UTC, datetime
import os
import time
from typing import Any, Optional
from uuid import uuid4

from collector.collectorFactory import CollectorFactory
from collector.database import DatabaseEnvironment, connect_database, insert_record
from collector.enums import GameId, SourceId
from collector.utils.logger import get_logger

logger = get_logger(__name__)


def run_source(
    game_id: GameId,
    source_id: SourceId,
    collection: Optional[Any] = None,
    collector_run_id: str | None = None,
) -> int:
    logger.info("Starting collector: %s/%s", game_id.value, source_id.value)
    started_at = time.perf_counter()
    collected_count = 0
    active_run_id = collector_run_id or str(uuid4())
    collector = None
    try:
        collector = CollectorFactory.create_collector(game_id, source_id)
        for item in collector.run():
            if collection is not None:
                observation = {
                    **item,
                    "collector_run_id": active_run_id,
                    "collector_date": datetime.now(UTC),
                }
                insert_record(collection, observation)
            collected_count += 1
            # Keep console output from aborting collection on Windows consoles
            # whose legacy encoding cannot represent values such as ``-3.50˚``.
            print(ascii(item))
    finally:
        if collector is not None:
            collector.close()
        logger.info(
            "Collector finished: %s/%s | records=%d | duration=%.2fs",
            game_id.value,
            source_id.value,
            collected_count,
            time.perf_counter() - started_at,
        )
    return collected_count


def run() -> int:
    """Parse command-line options and run one or every collector."""
    started_at = time.perf_counter()
    parser = argparse.ArgumentParser(description="Collect Formula 1 setups")
    parser.add_argument("--game", choices=[game.value for game in GameId])
    parser.add_argument("--source", choices=[source.value for source in SourceId])
    args = parser.parse_args()

    selected_game = GameId(args.game) if args.game else None
    selected_source = SourceId(args.source) if args.source else None
    collector_run_id = os.getenv("COLLECTOR_RUN_ID") or str(uuid4())
    failed_collectors = 0
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
                run_source(
                    key.game,
                    key.source,
                    collection,
                    collector_run_id=collector_run_id,
                )
            except Exception:
                # One unavailable website must not prevent the remaining collectors.
                failed_collectors += 1
                logger.exception("Collector failed: %s/%s", key.game.value, key.source.value)
    finally:
        client.close()
        logger.info(
            "All collectors finished | run_id=%s | failures=%d | duration=%.2fs",
            collector_run_id,
            failed_collectors,
            time.perf_counter() - started_at,
        )
    return 1 if failed_collectors else 0



if __name__ == "__main__":
    raise SystemExit(run())
