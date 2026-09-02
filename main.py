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
from collector.utils.metrics import (
    COLLECTION_RUN_DURATION,
    COLLECTION_RUNS_TOTAL,
    COLLECTOR_LAST_SUCCESS,
    COLLECTOR_RECORDS_TOTAL,
    COLLECTOR_RUN_DURATION,
    COLLECTOR_RUNS_TOTAL,
    REDIS_PUBLISH_TOTAL,
)

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
                        REDIS_PUBLISH_TOTAL.labels(outcome="success").inc()
                    except Exception as error:
                        REDIS_PUBLISH_TOTAL.labels(outcome="failed").inc()
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
        duration = time.perf_counter() - started_at
        outcome = "success" if succeeded else "failed"
        COLLECTOR_RUNS_TOTAL.labels(source=source_id.value, game=game_id.value, outcome=outcome).inc()
        COLLECTOR_RUN_DURATION.labels(source=source_id.value, game=game_id.value).observe(duration)
        COLLECTOR_RECORDS_TOTAL.labels(source=source_id.value, game=game_id.value, outcome=outcome).inc(collected_count)
        if succeeded:
            COLLECTOR_LAST_SUCCESS.labels(source=source_id.value, game=game_id.value).set_to_current_time()
        logger.info(
            "Collector finished collector=%s run_id=%s status=%s "
            "records=%d duration=%.2fs",
            label,
            active_run_id,
            "success" if succeeded else "failed",
            collected_count,
            duration,
        )
    return collected_count


def run() -> int:
    """Parse command-line options and run one or every collector."""
    started_at = time.perf_counter()
    started_at_utc = datetime.now(UTC)
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
        "event=collection_run_started run_id=%s started_at=%s collectors=%d",
        collector_run_id,
        started_at_utc.isoformat().replace("+00:00", "Z"),
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
            except Exception as error:
                # One unavailable website must not prevent the remaining collectors.
                failed_collectors += 1
                logger.exception(
                    "event=collector_error collector=%s source=%s game=%s "
                    "scope=collector run_id=%s error_type=%s",
                    f"{key.source.value}_{key.game.value}",
                    key.source.value,
                    key.game.value,
                    collector_run_id,
                    type(error).__name__,
                )
    finally:
        if publisher is not None:
            publisher.close()
        client.close()
        duration = time.perf_counter() - started_at
        finished_at_utc = datetime.now(UTC)
        outcome = "failed" if failed_collectors else "success"
        COLLECTION_RUNS_TOTAL.labels(outcome=outcome).inc()
        COLLECTION_RUN_DURATION.observe(duration)
        logger.info(
            "Raw documents handed to import pipeline run_id=%s",
            collector_run_id,
        )
        logger.info(
            "event=collection_run_finished run_id=%s started_at=%s "
            "finished_at=%s status=%s exit=%d collectors=%d failures=%d "
            "records=%d duration_seconds=%.2f",
            collector_run_id,
            started_at_utc.isoformat().replace("+00:00", "Z"),
            finished_at_utc.isoformat().replace("+00:00", "Z"),
            outcome,
            1 if failed_collectors else 0,
            len(collector_keys),
            failed_collectors,
            total_records,
            duration,
        )
    return 1 if failed_collectors else 0



if __name__ == "__main__":
    raise SystemExit(run())
