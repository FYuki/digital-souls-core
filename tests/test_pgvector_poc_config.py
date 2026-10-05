"""pgvector PoC の接続境界。DB・ネットワークを使わない単体試験。"""

from typing import Any

import psycopg
import pytest

from digital_souls_core.memory_ranking import EmbeddingSpace
from experiments.pgvector_memory.store import PgvectorMemoryStore, PocConfig, SourceSnapshot

from .pgvector_support import raw_connection

pytestmark = pytest.mark.ut
SOCKET = "/tmp/core-pgvector-poc-synthetic/socket"


@pytest.mark.parametrize(
    "socket",
    [
        "127.0.0.1",
        "relative/socket",
        "/run/postgresql",
        "/tmp/core-pgvector-poc-synthetic/socket,127.0.0.1",
        "/tmp/core-pgvector-poc-synthetic/socket,/tmp/other/socket",
        "/tmp/core-pgvector-poc-synthetic/../socket",
        "/tmp/core-pgvector-poc-synthetic/socket/",
        "/tmp/core-pgvector-poc-synthetic/socket\x00",
    ],
)
def test_socket_rejects_host_lists_and_non_fixture_paths(socket: str) -> None:
    with pytest.raises(ValueError):
        PocConfig(socket=socket)


@pytest.mark.parametrize(
    "changes",
    [
        {"database": "postgres"},
        {"user": "postgres"},
        {"database": "digital_souls_core"},
        {"user": "dsc_core"},
        {"port": 0},
        {"port": True},
        {"schema": "digital_souls_core"},
        {"schema": "public"},
    ],
)
def test_configuration_rejects_production_identity_and_schema(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        PocConfig(socket=SOCKET, **changes)


def test_configuration_accepts_only_explicit_synthetic_fixture_identity() -> None:
    config = PocConfig(socket=SOCKET, schema="pgvector_poc_synthetic")
    assert config.database == config.user == "core_pgvector_synthetic"
    assert config.socket == SOCKET and config.port == 5432


@pytest.mark.parametrize(
    "variable", ["PGHOSTADDR", "PGSERVICE", "PGOPTIONS", "PGPASSFILE", "PGSSLMODE", "PGUSER"]
)
@pytest.mark.parametrize("boundary", ["store", "cleanup"])
def test_libpq_environment_is_rejected_before_connection(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    boundary: str,
) -> None:
    store = PgvectorMemoryStore(
        PocConfig(socket=SOCKET),
        EmbeddingSpace("synthetic", "synthetic-v1", 3),
    )
    attempts: list[None] = []

    def reject_connection(*args: Any, **kwargs: Any) -> Any:
        attempts.append(None)
        pytest.fail("No connection may be attempted with inherited libpq configuration")

    monkeypatch.setattr(psycopg, "connect", reject_connection)
    monkeypatch.setenv(variable, "synthetic-untrusted-value")
    connection = store.transaction() if boundary == "store" else raw_connection(store.config)
    with pytest.raises(ValueError):
        with connection:
            pytest.fail("The transaction must not be entered")
    assert attempts == []


def test_source_message_index_rejects_overflow_before_postgresql_integer_conversion() -> None:
    with pytest.raises(ValueError):
        SourceSnapshot("synthetic-source", 1, 0, message_index=2**31)
