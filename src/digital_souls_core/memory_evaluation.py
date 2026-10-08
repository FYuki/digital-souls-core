"""Synthetic retrieval evaluation; this harness is not a storage/privacy boundary."""

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .application import CoreError
from .character import AccessScope
from .history import Binding, SourceReference
from .memory_contracts import SourceVersion
from .memory_ranking import (
    EmbeddingSpace,
    MemoryEmbedding,
    RetrievalPolicy,
    rank_records,
    validate_embedding_space,
)
from .memory_record_store import RetrievalCandidate
from .memory_records import (
    Citation,
    Episode,
    EpisodeContext,
    FiveW,
    RecordState,
    Speaker,
    TemporalValue,
)

type Identifier = Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9-]{0,63}$")]
type Component = Annotated[float, Field(strict=True, allow_inf_nan=False)]
type Vector = tuple[Component, ...]
type EvaluationMode = Literal["fixture", "local_model"]


class _FixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class EvaluationSource(_FixtureModel):
    conversation_id: Identifier
    turn_revision: Annotated[int, Field(strict=True, ge=1)]
    message_index: Annotated[int, Field(strict=True, ge=0)]
    epoch: Annotated[int, Field(strict=True, ge=0)]


class _EvaluationItem(_FixtureModel):
    id: Identifier
    text: Annotated[str, Field(strict=True, min_length=1, max_length=8192, repr=False)]
    vector: Vector = Field(repr=False)


class EvaluationDocument(_EvaluationItem):
    source: EvaluationSource

    def candidate(self, *, created_at: datetime) -> RetrievalCandidate:
        source = self.source
        binding = Binding(AccessScope(), "synthetic-evaluation")
        citation = Citation(
            binding,
            SourceVersion(
                SourceReference(source.conversation_id, source.turn_revision, source.message_index),
                source.epoch,
            ),
            Speaker.USER,
            0,
            len(self.text),
        )
        return RetrievalCandidate(
            Episode(
                episode_id=self.id,
                version=1,
                binding=binding,
                normalized_text=self.text,
                created_at=created_at,
                last_user_mentioned_at=None,
                state=RecordState.ACTIVE,
                five_w=FiveW(predicate="synthetic fixture"),
                experience_time=TemporalValue(),
                experienced_at=None,
                context=EpisodeContext.ACTUAL,
                citations=(citation,),
            )
        )


class EvaluationQuery(_EvaluationItem):
    text: Annotated[str, Field(strict=True, min_length=1, max_length=256, repr=False)]
    candidate_ids: tuple[Identifier, ...]
    relevant_ids: tuple[Identifier, ...]
    excluded_ids: tuple[Identifier, ...]


class EvaluationFixture(_FixtureModel):
    dataset_type: Literal["synthetic"]
    version: Identifier
    dimensions: Annotated[int, Field(strict=True, ge=1, le=4096)]
    documents: tuple[EvaluationDocument, ...] = Field(max_length=1000)
    queries: tuple[EvaluationQuery, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid_references_and_vectors(self) -> "EvaluationFixture":
        document_ids = {document.id for document in self.documents}
        if len(document_ids) != len(self.documents) or len({q.id for q in self.queries}) != len(
            self.queries
        ):
            raise ValueError("duplicate evaluation identifier")
        text_vectors: dict[str, Vector] = {}
        for item in (*self.documents, *self.queries):
            if len(item.vector) != self.dimensions or not any(item.vector):
                raise ValueError("invalid evaluation vector")
            if item.text in text_vectors and text_vectors[item.text] != item.vector:
                raise ValueError("conflicting evaluation vectors")
            text_vectors[item.text] = item.vector
        for query in self.queries:
            candidates = set(query.candidate_ids)
            relevant, excluded = set(query.relevant_ids), set(query.excluded_ids)
            if (
                len(candidates) != len(query.candidate_ids)
                or len(relevant) != len(query.relevant_ids)
                or len(excluded) != len(query.excluded_ids)
                or not candidates <= document_ids
                or not relevant <= candidates
                or not excluded <= candidates
                or relevant & excluded
            ):
                raise ValueError("invalid evaluation references")
        return self


class FixtureEmbedding:
    """Exact fixture vectors test ranking/metrics, never a learned model's quality."""

    def __init__(self, fixture: EvaluationFixture) -> None:
        self.space = EmbeddingSpace("synthetic-fixture", fixture.version, fixture.dimensions)
        self._vectors = {item.text: item.vector for item in (*fixture.documents, *fixture.queries)}

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple(self._vectors[text] for text in texts)


@dataclass(frozen=True)
class QueryEvaluation:
    query_id: str
    retrieved_ids: tuple[str, ...]
    relevant_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]
    candidate_count: int
    answerable: bool
    returned_empty: bool
    recall_at_k: float | None
    precision_at_k: float | None
    reciprocal_rank: float | None


@dataclass(frozen=True)
class EvaluationReport:
    fixture_version: str
    mode: EvaluationMode
    quality_evidence: bool
    synthetic_only: bool
    backend_identity_verified: bool
    space: EmbeddingSpace
    k: int
    embedding_call_count: int
    query_count: int
    answerable_count: int
    unanswerable_count: int
    empty_result_count: int
    answerable_empty_result_count: int
    unanswerable_empty_result_count: int
    mean_recall_at_k: float | None
    mean_precision_at_k: float | None
    mrr_at_k: float | None
    unanswerable_empty_rate: float | None
    queries: tuple[QueryEvaluation, ...]


async def evaluate_memory_search(
    fixture: EvaluationFixture,
    embedding: MemoryEmbedding,
    *,
    k: int = 2,
    mode: EvaluationMode = "fixture",
    timeout_seconds: float = 15,
) -> EvaluationReport:
    """Evaluate synthetic canonical candidates using the product record ranker.

    Precision@k uses k as its denominator even when fewer results are returned.
    Recall/precision/MRR averages include answerable queries only; unanswerable
    empty-result rate is separate. Mode is caller-declared, not model attestation.
    Fixture vectors provide no model-quality evidence. Local mode measures only
    this synthetic dataset and does not establish good real-world quality.
    """
    if (
        type(k) is not int
        or not 1 <= k <= 16
        or mode not in ("fixture", "local_model")
        or isinstance(timeout_seconds, bool)
        or not 0 < timeout_seconds <= 300
    ):
        raise ValueError("invalid evaluation configuration")
    if mode == "local_model" and isinstance(embedding, FixtureEmbedding):
        raise ValueError("fixture vectors are not model-quality evidence")
    space = replace(validate_embedding_space(embedding.space))
    # Product ranking policy; only the returned count follows the requested k.
    policy = RetrievalPolicy(max_retrieved_memories=k, candidate_pool_size=max(k, 20))
    records = {
        document.id: document.candidate(
            created_at=datetime(2026, 1, 1, tzinfo=UTC) - timedelta(seconds=index)
        )
        for index, document in enumerate(fixture.documents)
    }
    rows: list[QueryEvaluation] = []
    embedding_calls = 0
    for query in fixture.queries:
        excluded = set(query.excluded_ids)
        candidates = tuple(records[mid] for mid in query.candidate_ids if mid not in excluded)
        ranked: tuple[RetrievalCandidate, ...] = ()
        if candidates:
            try:
                if replace(validate_embedding_space(embedding.space)) != space:
                    raise ValueError
                async with asyncio.timeout(timeout_seconds):
                    vectors = await embedding.embed(
                        (query.text, *(m.record.normalized_text for m in candidates))
                    )
                if replace(validate_embedding_space(embedding.space)) != space:
                    raise ValueError
                ranked = rank_records(candidates, vectors, space, policy)
                embedding_calls += 1
            except Exception:
                raise CoreError(502, "memory_embedding_failed", "Memory embedding failed") from None
        relevant = set(query.relevant_ids)
        ids = tuple(memory.identifier for memory in ranked)
        hits = sum(mid in relevant for mid in ids)
        reciprocal = next((1 / rank for rank, mid in enumerate(ids, 1) if mid in relevant), 0.0)
        rows.append(
            QueryEvaluation(
                query.id,
                ids,
                query.relevant_ids,
                query.excluded_ids,
                len(candidates),
                bool(relevant),
                not ids,
                hits / len(relevant) if relevant else None,
                hits / k if relevant else None,
                reciprocal if relevant else None,
            )
        )
    answerable = sum(row.answerable for row in rows)
    unanswerable = len(rows) - answerable
    empty_answerable = sum(row.returned_empty and row.answerable for row in rows)
    empty_unanswerable = sum(row.returned_empty and not row.answerable for row in rows)
    return EvaluationReport(
        fixture.version,
        mode,
        mode == "local_model" and embedding_calls > 0,
        True,
        False,
        space,
        k,
        embedding_calls,
        len(rows),
        answerable,
        unanswerable,
        empty_answerable + empty_unanswerable,
        empty_answerable,
        empty_unanswerable,
        sum(row.recall_at_k or 0 for row in rows) / answerable if answerable else None,
        sum(row.precision_at_k or 0 for row in rows) / answerable if answerable else None,
        sum(row.reciprocal_rank or 0 for row in rows) / answerable if answerable else None,
        empty_unanswerable / unanswerable if unanswerable else None,
        tuple(rows),
    )
