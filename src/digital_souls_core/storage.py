"""Explicit trusted storage selection; importing this module opens no database."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .history import HistoryStore
from .memory_contracts import MemoryStore
from .postgres_db import PostgresConfig, PostgresDatabase
from .postgres_history import PostgresHistory
from .postgres_memory import PostgresMemory
from .sqlite_history import SQLiteHistory
from .sqlite_memory import SQLiteMemory


class StorageConfig(BaseModel):
    """Deployment-owned values, separate from history and memory authorization."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    backend: Literal["sqlite", "postgresql"]
    sqlite_path: str | None = Field(default=None, min_length=1, max_length=4096, repr=False)
    postgres: PostgresConfig | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def explicit_backend(self) -> "StorageConfig":
        if self.backend == "postgresql":
            if self.postgres is None or self.sqlite_path is not None:
                raise ValueError("PostgreSQL requires only explicit PostgreSQL configuration")
        elif self.postgres is not None:
            raise ValueError("SQLite does not accept PostgreSQL configuration")
        return self


@dataclass(frozen=True)
class StorageStores:
    history: HistoryStore
    memory: MemoryStore


def open_storage(config: StorageConfig) -> StorageStores:
    """Open stores only on explicit invocation; never import or extract history."""
    config = StorageConfig.model_validate(config.model_dump())
    if config.backend == "postgresql":
        assert config.postgres is not None
        database = PostgresDatabase(config.postgres)
        return StorageStores(PostgresHistory(database), PostgresMemory(database))
    path = Path(config.sqlite_path) if config.sqlite_path is not None else None
    return StorageStores(SQLiteHistory(path), SQLiteMemory(path))
