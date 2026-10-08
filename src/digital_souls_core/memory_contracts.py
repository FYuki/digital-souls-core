"""Storage-independent memory values. Text is user evidence, never model reasoning."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from .history import Binding, SourceReference


@dataclass(frozen=True)
class SourceVersion:
    reference: SourceReference
    epoch: int


@dataclass(frozen=True)
class Evidence:
    source: SourceVersion
    text: str = field(repr=False)
    stated_at: datetime | None


@dataclass(frozen=True)
class Memory:
    memory_id: str
    kind: Literal["episode", "semantic"]
    text: str = field(repr=False)
    sources: tuple[SourceVersion, ...]
    # Storage order of the latest user source turn (PoC last_user_mentioned_at).
    # Ranking-only metadata; identity and dispatch validation ignore it.
    mentioned: int = field(default=0, compare=False, repr=False)


@dataclass(frozen=True)
class Candidate:
    kind: Literal["episode", "semantic"]
    sources: tuple[SourceVersion, ...]
    text: str = field(repr=False)


@dataclass(frozen=True)
class MemoryJob:
    job_id: str
    sources: tuple[SourceVersion, ...]
    versions: str
    state: str


class MemoryStore(Protocol):
    def sources(
        self, binding: Binding, refs: tuple[SourceReference, ...]
    ) -> tuple[Evidence, ...]: ...
    def current(self, binding: Binding, sources: tuple[SourceVersion, ...]) -> bool: ...
    def begin(
        self, binding: Binding, sources: tuple[SourceVersion, ...], versions: str
    ) -> MemoryJob: ...
    def commit(
        self, binding: Binding, job: MemoryJob, candidates: tuple[Candidate, ...]
    ) -> None: ...
    def results(self, binding: Binding, job_id: str) -> tuple[Memory, ...]: ...
    def valid(self, binding: Binding, memories: tuple[Memory, ...]) -> bool: ...
    def events(self, binding: Binding) -> tuple[str, ...]: ...
    def consume(self, binding: Binding, event_id: str) -> None: ...
    def pending(self, binding: Binding, limit: int = 16) -> tuple[MemoryJob, ...]: ...

    def fail(self, binding: Binding, job: MemoryJob) -> None: ...

    def rebase(self, binding: Binding, job: MemoryJob) -> MemoryJob | None: ...
