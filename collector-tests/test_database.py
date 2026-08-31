import pytest

import collector.database as database
from collector.database import DatabaseEnvironment, build_raw_hash, insert_record


def test_sandbox_uses_local_mongodb(monkeypatch) -> None:
    monkeypatch.setattr(database, "MONGODB_SANDBOX_URI", "mongodb://localhost:27017")

    assert database.get_mongodb_uri(DatabaseEnvironment.SANDBOX) == (
        "mongodb://localhost:27017"
    )


def test_production_uses_server_mongodb(monkeypatch) -> None:
    server_uri = "mongodb://user:password@192.0.2.10:27017"
    monkeypatch.setattr(database, "MONGODB_PRODUCTION_URI", server_uri)

    assert database.get_mongodb_uri(DatabaseEnvironment.PRODUCTION) == server_uri


@pytest.mark.parametrize(
    ("configured_value", "expected"),
    [
        ("sandbox", DatabaseEnvironment.SANDBOX),
        ("production", DatabaseEnvironment.PRODUCTION),
    ],
)
def test_tests_can_select_database_environment(
    monkeypatch,
    configured_value,
    expected,
) -> None:
    monkeypatch.setattr(database, "TEST_MONGODB_ENV", configured_value)

    assert database.get_test_database_environment() is expected


def test_rejects_unknown_database_environment() -> None:
    with pytest.raises(ValueError, match="Invalid database environment"):
        database.get_database_environment("staging")


def test_every_observation_is_inserted_with_a_new_id() -> None:
    class RecordingCollection:
        def __init__(self) -> None:
            self.documents = []

        def insert_one(self, document) -> None:
            self.documents.append(document)

    collection = RecordingCollection()
    item = {
        "source": "f1_laps",
        "source_id": "setup-1",
        "setup": {"aerodynamics": "10-20"},
    }

    first_id = insert_record(collection, item)
    second_id = insert_record(collection, item)

    assert first_id != second_id
    assert [document["_id"] for document in collection.documents] == [
        first_id,
        second_id,
    ]
    assert all(
        document["processing"]["status"] == "pending"
        for document in collection.documents
    )
    assert all(
        document["processing"]["idempotency_key"] == document["_id"]
        for document in collection.documents
    )


def test_raw_hash_ignores_collection_trace_fields() -> None:
    first = {
        "source": "f1_laps",
        "source_id": "setup-1",
        "setup": {"aero": "10-20"},
        "collector_run_id": "run-1",
        "collector_date": "2026-08-31T10:00:00Z",
    }
    second = {
        **first,
        "collector_run_id": "run-2",
        "collector_date": "2026-08-31T18:00:00Z",
    }

    assert build_raw_hash(first) == build_raw_hash(second)


def test_reference_records_are_not_added_to_setup_queue() -> None:
    class RecordingCollection:
        def __init__(self) -> None:
            self.documents = []

        def insert_one(self, document) -> None:
            self.documents.append(document)

    collection = RecordingCollection()
    insert_record(
        collection,
        {"record_type": "tire_temperature", "source": "excel_file"},
    )

    assert "processing" not in collection.documents[0]
