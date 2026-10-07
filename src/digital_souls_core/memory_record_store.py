"""Storage-independent canonical memory port. Admission/formation belong to callers."""

from dataclasses import dataclass
from typing import Protocol

from .history import Binding
from .memory_records import (
    Episode,
    EpisodeFactLink,
    Fact,
    RecordHead,
    RecordKind,
    RecordRef,
    Semantic,
)

type MemoryRecord = Episode | Fact | EpisodeFactLink | Semantic


@dataclass(frozen=True)
class FactWrite:
    fact: Fact
    expected_version: int | None = None


@dataclass(frozen=True)
class RecordBatch:
    episodes: tuple[Episode, ...] = ()
    facts: tuple[FactWrite, ...] = ()
    links: tuple[EpisodeFactLink, ...] = ()
    semantics: tuple[Semantic, ...] = ()


class MemoryRecordStore(Protocol):
    def register(
        self, binding: Binding, batch: RecordBatch, formation_version: str
    ) -> tuple[RecordRef, ...]:
        """Atomically register active records; matching retry returns original references.

        New identities start at v1. Fact writes require the expected head version
        and exactly its successor. Stale sources, references, IDs and conflicting
        retries fail closed. No operation reactivates a suspended identity.
        """
        ...

    def get(
        self, binding: Binding, kind: RecordKind, record_id: str, *, version: int | None = None
    ) -> MemoryRecord | None: ...

    def list(self, binding: Binding, kind: RecordKind) -> tuple[MemoryRecord, ...]:
        """Active current versions only; get(version=...) can read active Fact history."""
        ...

    def head(self, binding: Binding, kind: RecordKind, record_id: str) -> RecordHead | None:
        """Content-free identity, including suspended records."""
        ...

    def affected(self, binding: Binding, event_id: str) -> tuple[RecordRef, ...]:
        """Content-free reevaluation targets, independent of legacy event consumption."""
        ...
