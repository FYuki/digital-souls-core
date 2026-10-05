"""The trusted factory is explicit and cannot change default API persistence."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from digital_souls_core import storage
from digital_souls_core.character import AccessScope
from digital_souls_core.history import Binding
from digital_souls_core.postgres_db import PostgresConfig
from digital_souls_core.sqlite_memory import SQLiteMemory

pytestmark = pytest.mark.ut


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"backend": "remote"},
        {"backend": "postgresql"},
        {"backend": "sqlite", "extra": True},
        {"backend": "sqlite", "sqlite_path": ""},
        {"backend": "sqlite", "postgres": {"database": "synthetic", "user": "synthetic"}},
        {
            "backend": "postgresql",
            "sqlite_path": "/tmp/synthetic",
            "postgres": {"database": "synthetic", "user": "synthetic"},
        },
    ],
)
def test_ambiguous_config_is_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        storage.StorageConfig.model_validate(values)


def test_sqlite_stores_share_explicit_database(tmp_path: Path) -> None:
    config = storage.StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "history.db"))
    stores = storage.open_storage(config)
    binding = Binding(
        AccessScope(subject="synthetic", client="test", audience="local-private"), "char"
    )
    created = stores.history.create(binding)
    assert isinstance(stores.memory, SQLiteMemory)
    assert stores.memory.read(binding, created.conversation_id) == created
    assert stores.memory.search(binding, "synthetic", 10) == ()


def test_postgres_factory_shares_database_and_does_not_extract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = storage.StorageConfig(
        backend="postgresql", postgres=PostgresConfig(database="synthetic", user="synthetic")
    )
    calls: list[object] = []

    def opened(database: object) -> object:
        calls.append(database)
        return object()

    monkeypatch.setattr(storage, "PostgresHistory", opened)
    monkeypatch.setattr(storage, "PostgresMemory", opened)
    result = storage.open_storage(config)
    assert isinstance(result, storage.StorageStores)
    assert len(calls) == 2 and calls[0] is calls[1]


def test_construct_cannot_bypass_backend_validation() -> None:
    config = storage.StorageConfig.model_construct(backend="postgresql", postgres=None)
    with pytest.raises(ValidationError):
        storage.open_storage(config)
