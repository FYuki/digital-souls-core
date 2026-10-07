"""Explicit trusted storage selection; importing this module opens no database."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .history import HistoryStore
from .memory_contracts import MemoryStore
from .postgres_db import PostgresConfig, PostgresDatabase
from .postgres_history import PostgresHistory
from .postgres_memory import PostgresMemory


class StorageConfig(BaseModel):
    """Deployment-owned values, separate from history and memory authorization."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    backend: Literal["postgresql"]
    postgres: PostgresConfig = Field(repr=False)


@dataclass(frozen=True)
class StorageStores:
    history: HistoryStore
    memory: MemoryStore


def open_storage(config: StorageConfig) -> StorageStores:
    """Open stores only on explicit invocation; never import or extract history."""
    config = StorageConfig.model_validate(config.model_dump())
    database = PostgresDatabase(config.postgres)
    return StorageStores(PostgresHistory(database), PostgresMemory(database))
