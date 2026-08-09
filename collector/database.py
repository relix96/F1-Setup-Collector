from enum import Enum
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
    return client, collection


def is_guid(value: Any) -> bool:
    """Return whether a value is a canonical GUID string."""
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.casefold()
    except ValueError:
        return False


def upsert_record(collection: Any, item: dict[str, Any]) -> None:
    """Store a record with a persistent GUID and migrate its legacy id."""
    logical_key = {
        "source": item["source"],
        "source_id": item["source_id"],
    }
    existing = collection.find_one(logical_key, {"_id": 1})

    if existing is not None and is_guid(existing.get("_id")):
        document_id = existing["_id"]
    else:
        document_id = str(uuid4())
        collection.delete_many(logical_key)

    collection.replace_one(
        {"_id": document_id},
        {"_id": document_id, **item},
        upsert=True,
    )
