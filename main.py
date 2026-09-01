import argparse
from datetime import UTC, datetime
import os
import time
from typing import Any, Optional
from uuid import uuid4

from collector.collectorFactory import CollectorFactory
from collector.database import DatabaseEnvironment, connect_database, insert_record
from collector.enums import GameId, SourceId
from collector.queue import RedisSetupPublisher
from collector.settings import COLLECTOR_LOG_RECORDS, REDIS_SETUP_STREAM, REDIS_URL
from collector.utils.logger import get_logger

logger = get_logger(__name__)

GAME_LABELS = {GameId.F1_26: "F1 26"}
SOURCE_LABELS = {
    SourceId.F1_LAPS: "F1Laps",
    SourceId.EA_SETUP: "EA Setup",
    SourceId.EXCEL_FILE: "Excel",
}


def collector_label(game_id: GameId, source_id: SourceId) -> str:
    return (
        f"{SOURCE_LABELS.get(source_id, source_id.value)}"
        f" -> {GAME_LABELS.get(game_id, game_id.value)}"
    )


def run_source(
    game_id: GameId,
    source_id: SourceId,
    collection: Optional[Any] = None,
    collector_run_id: str | None = None,
    publisher: RedisSetupPublisher | None = None,
) -> int:
    started_at = time.perf_counter()
    collected_count = 0
    active_run_id = collector_run_id or str(uuid4())
    collector = None
    succeeded = False
    label = collector_label(game_id, source_id)
    logger.info(
        "Collector started collector=%s run_id=%s",
        label,
        active_run_id,
    )
    try:
        collector = CollectorFactory.create_collector(game_id, source_id)
        for item in collector.run():
            if collection is not None:
                observation = {
                    **item,
                    "collector_run_id": active_run_id,
                    "collector_date": datetime.now(UTC),
                }
                document_id = insert_record(collection, observation)
                if publisher is not None and isinstance(observation.get("setup"), dict):
                    try:
                        publisher.publish(document_id)
                    except Exception as error:
                        # MongoDB is authoritative. The importer reconciles pending
                        # documents if Redis is temporarily unavailable.
                        logger.warning(
                            "Redis publish failed for MongoDB document %s: %s",
                            document_id,
                            type(error).__name__,
                        )
            collected_count += 1
            # Keep console output from aborting collection on Windows consoles
            # whose legacy encoding cannot represent values such as ``-3.50˚``.
            if COLLECTOR_LOG_RECORDS:
                print(ascii(item))
        succeeded = True
    finally:
        if collector is not None:
            collector.close()
        logger.info(
            "Collector finished collector=%s run_id=%s status=%s "
            "records=%d duration=%.2fs",
            label,
            active_run_id,
            "success" if succeeded else "failed",
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
    total_records = 0
    collector_keys = [
        key
        for key in CollectorFactory.get_registered_keys()
        if (selected_game is None or key.game is selected_game)
        and (selected_source is None or key.source is selected_source)
    ]

    # The application always writes to the production server. Tests select their
    # own profile through TEST_MONGODB_ENV in collector.database.
    client, collection = connect_database(DatabaseEnvironment.PRODUCTION)
    publisher = RedisSetupPublisher.from_url(REDIS_URL, REDIS_SETUP_STREAM)
    logger.info(
        "Collection run started run_id=%s collectors=%d",
        collector_run_id,
        len(collector_keys),
    )
    try:
        for key in collector_keys:
            try:
                total_records += run_source(
                    key.game,
                    key.source,
                    collection,
                    collector_run_id=collector_run_id,
                    publisher=publisher,
                ) or 0
            except Exception:
                # One unavailable website must not prevent the remaining collectors.
                failed_collectors += 1
                logger.exception(
                    "Collector error collector=%s run_id=%s",
                    collector_label(key.game, key.source),
                    collector_run_id,
                )
    finally:
        if publisher is not None:
            publisher.close()
        client.close()
        logger.info(
            "Raw documents handed to import pipeline run_id=%s",
            collector_run_id,
        )
        logger.info(
            "Collection run finished run_id=%s exit=%d collectors=%d "
            "failures=%d records=%d duration=%.2fs",
            collector_run_id,
            1 if failed_collectors else 0,
            len(collector_keys),
            failed_collectors,
            total_records,
            time.perf_counter() - started_at,
        )
    return 1 if failed_collectors else 0



if __name__ == "__main__":
    raise SystemExit(run())
