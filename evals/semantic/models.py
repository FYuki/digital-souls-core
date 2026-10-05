"""入力専用の合成ケース。正解データはこのモジュールから読み込まない。"""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from digital_souls_core.character import AccessScope, managed_loopback_endpoint
from digital_souls_core.history import Binding
from digital_souls_core.local_embedding import LocalEmbeddingProfile
from experiments.pgvector_memory.store import SourceSnapshot, binding_key


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class Scope(StrictModel):
    subject: str
    client: str
    audience: str
    character_id: str

    def binding(self) -> Binding:
        value = Binding(AccessScope(self.subject, self.client, self.audience), self.character_id)  # type: ignore[arg-type]
        binding_key(value)
        return value


class Source(StrictModel):
    id: str
    revision: int
    epoch: int
    conversation_id: str
    turn_revision: int
    message_index: int
    private: bool
    excluded: bool
    deleted: bool
    role: str
    binding: Scope | None = None

    def snapshot(self) -> SourceSnapshot:
        return SourceSnapshot(source_id=self.id, **self.model_dump(exclude={"id", "binding"}))


class MemoryInput(StrictModel):
    id: str
    text: str = Field(min_length=1, max_length=262144, repr=False)
    source_ids: list[str] = Field(min_length=1, max_length=16)
    vector: list[float] = Field(min_length=4, max_length=4, repr=False)
    binding: Scope | None = None


class Mutation(StrictModel):
    phase: Literal["before_search", "after_search", "after_answer"]
    op: Literal["source_replace", "memory_update", "memory_delete"]
    binding: Scope | None = None
    source_id: str | None = None
    memory_id: str | None = None
    changes: dict[str, str | bool | int] | None = None
    text: str | None = Field(default=None, repr=False)
    vector: list[float] | None = Field(default=None, repr=False)
    source_ids: list[str] | None = None


class Case(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    category: str
    query: str = Field(min_length=1, max_length=8192, repr=False)
    query_vector: list[float] = Field(min_length=4, max_length=4, repr=False)
    binding: Scope
    sources: list[Source] = Field(max_length=64)
    memories: list[MemoryInput] = Field(max_length=64)
    mutations: list[Mutation] = Field(default_factory=list, max_length=16)
    limit: int = Field(default=8, ge=1, le=16)

    @model_validator(mode="after")
    def vectors_and_ids(self) -> "Case":
        vectors = [self.query_vector, *(memory.vector for memory in self.memories)]
        if any(not any(vector) or not all(math.isfinite(v) for v in vector) for vector in vectors):
            raise ValueError("Invalid synthetic vector")
        for items in (self.sources, self.memories):
            keys = [(item.id, (item.binding or self.binding).model_dump_json()) for item in items]
            if len(set(keys)) != len(keys):
                raise ValueError("Duplicate synthetic identifier in binding")
        return self


class Corpus(StrictModel):
    schema_version: Literal[1]
    dimensions: Literal[4]
    cases: list[Case] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_ids(self) -> "Corpus":
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case identifier")
        return self


class ChatProfile(StrictModel):
    api_base: str
    model: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$")
    model_digest: str = Field(min_length=1, max_length=128, repr=False)
    enabled: bool = False
    timeout_seconds: float = Field(default=15, gt=0, le=15, allow_inf_nan=False)
    max_tokens: int = Field(default=512, ge=1, le=1024)

    @model_validator(mode="after")
    def local_endpoint(self) -> "ChatProfile":
        managed_loopback_endpoint(self.api_base)
        if not self.enabled:
            raise ValueError("Chat profile must be explicitly enabled")
        return self


class LocalProfile(StrictModel):
    schema_version: Literal[1]
    profile_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    embedding: LocalEmbeddingProfile
    chat: ChatProfile | None = None

    @model_validator(mode="after")
    def enabled_embedding(self) -> "LocalProfile":
        if not self.embedding.enabled or self.embedding.dimensions > 2000:
            raise ValueError("An enabled bounded embedding profile is required")
        return self
