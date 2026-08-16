import pytest

import collector.database as database
from collector.database import DatabaseEnvironment


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
