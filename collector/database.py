from enum import Enum
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any
from uuid import UUID, uuid4

from collector.settings import (
    MONGODB_COLLECTION,
    MONGODB_DATABASE,
    MONGODB_PRODUCTION_URI,
    MONGODB_SANDBOX_URI,
    TEST_MONGODB_ENV,
)


class DatabaseEnvironment(str, Enum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"


def get_database_environment(value: str) -> DatabaseEnvironment:
    """Validate and normalize a database environment name."""
    try:
        return DatabaseEnvironment(value.strip().casefold())
    except ValueError as exc:
        choices = ", ".join(environment.value for environment in DatabaseEnvironment)
        raise ValueError(
            f"Invalid database environment {value!r}. Choose one of: {choices}"
        ) from exc


def get_test_database_environment() -> DatabaseEnvironment:
    """Return the database profile selected for integration tests."""
    return get_database_environment(TEST_MONGODB_ENV)


def get_mongodb_uri(environment: DatabaseEnvironment) -> str:
    uri = (
        MONGODB_PRODUCTION_URI
        if environment is DatabaseEnvironment.PRODUCTION
        else MONGODB_SANDBOX_URI
    )
    if not uri:
        variable = (
            "MONGODB_PRODUCTION_URI"
            if environment is DatabaseEnvironment.PRODUCTION
            else "MONGODB_SANDBOX_URI"
        )
        raise ValueError(f"{variable} must be configured")
    return uri


def connect_database(
    environment: DatabaseEnvironment,
) -> tuple[Any, Any]:
    """Connect to the selected MongoDB profile and return its F1 collection."""
    # Import lazily so collectors and tests that do not use MongoDB can run
    # without requiring the database driver during pytest discovery.
    from pymongo import MongoClient

    client = MongoClient(get_mongodb_uri(environment))
    collection = client[MONGODB_DATABASE][MONGODB_COLLECTION]
    collection.create_index(
        [("collector_run_id", 1), ("collector_date", -1)],
        name="ix_collector_run_date",
    )
    collection.create_index(
        [("source", 1), ("source_id", 1), ("collector_date", -1)],
        name="ix_source_external_date",
    )
    collection.create_index(
        [
            ("processing.status", 1),
            ("processing.next_attempt_at", 1),
            ("processing.lease_expires_at", 1),
            ("collector_date", 1),
        ],
        name="ix_processing_queue",
    )
    return client, collection


def is_guid(value: Any) -> bool:
    """Return whether a value is a canonical GUID string."""
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.casefold()
    except ValueError:
        return False


def insert_record(collection: Any, item: dict[str, Any]) -> str:
    """Store every collection observation as an immutable MongoDB document."""

    document_id = str(uuid4())
    document = {**item, "_id": document_id}
    if isinstance(item.get("setup"), dict):
        document["processing"] = {
            "status": "pending",
            "attempts": 0,
            "last_error": None,
            "last_attempt_at": None,
            "processed_at": None,
            "next_attempt_at": None,
            "worker_id": None,
            "lease_expires_at": None,
            "idempotency_key": document_id,
            "raw_hash": build_raw_hash(item),
            "normalizer_version": None,
        }
    collection.insert_one(document)
    return document_id


def build_raw_hash(item: dict[str, Any]) -> str:
    """Hash raw content while ignoring collection and processing trace fields."""

    content = {
        key: value
        for key, value in item.items()
        if key not in {"_id", "collector_date", "collector_run_id", "processing"}
    }
    serialized = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_serialize_hash_value,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _serialize_hash_value(value: object) -> str:
    if isinstance(value, (date, datetime, Decimal, UUID)):
        return str(value)
    raise TypeError(f"Unsupported raw hash value: {type(value).__name__}")
