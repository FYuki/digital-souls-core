"""隔離 pgvector PoC の合成契約。本番 schema / 実モデルは使用しない。"""

import asyncio
import hashlib
import os
from collections.abc import Iterator
from dataclasses import replace
from typing import Any, Literal, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, sql

from digital_souls_core.application import CoreError
from digital_souls_core.character import AccessScope
from digital_souls_core.history import Binding, SourceReference
from digital_souls_core.memory_contracts import Memory, SourceVersion
from digital_souls_core.memory_ranking import EmbeddingSpace, rank_memories
from experiments.pgvector_memory.store import (
    PgvectorMemoryStore,
    PocConfig,
    SourceSnapshot,
    WorkItem,
)

from .pgvector_support import raw_connection

pytestmark = pytest.mark.pgvector
SCOPE = Binding(AccessScope(subject="synthetic-operator", client="synthetic-client"), "synthetic")
SPACE = EmbeddingSpace("synthetic-embedding", "synthetic-v1", 3, "synthetic-config-v1")
VECTOR = (1.0, 0.0, 0.0)


@pytest.fixture
def store() -> Iterator[PgvectorMemoryStore]:
    names = (
        "DSC_PGVECTOR_POC_SOCKET",
        "DSC_PGVECTOR_POC_PORT",
        "DSC_PGVECTOR_POC_DATABASE",
        "DSC_PGVECTOR_POC_USER",
    )
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.fail("Synthetic pgvector configuration is required: " + ", ".join(missing))
    config = PocConfig(
        socket=os.environ[names[0]],
        port=int(os.environ[names[1]]),
        database=os.environ[names[2]],
        user=os.environ[names[3]],
        schema="pgvector_poc_" + uuid4().hex,
    )
    selected = PgvectorMemoryStore(config, SPACE)
    selected.initialize()
    try:
        yield selected
    finally:
        # この fixture 自身が生成した UUID schema だけを除去する。
        with raw_connection(config) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(config.schema))
            )


def source(store: PgvectorMemoryStore, name: str, binding: Binding = SCOPE) -> SourceSnapshot:
    snapshot = SourceSnapshot(source_id=name, revision=1, epoch=0)
    store.put_source(binding, snapshot)
    return snapshot


def pending(
    store: PgvectorMemoryStore,
    memory_id: str,
    sources: tuple[SourceSnapshot, ...],
    *,
    text: str | None = None,
    binding: Binding = SCOPE,
) -> WorkItem:
    body = text or "Synthetic evidence for " + memory_id + "."
    store.put_memory(binding, memory_id, body, sources)
    work = store.prepare(binding, memory_id)
    assert work is not None
    return work


def ready(
    store: PgvectorMemoryStore,
    memory_id: str,
    sources: tuple[SourceSnapshot, ...],
    vector: tuple[float, ...] = VECTOR,
    *,
    text: str | None = None,
    binding: Binding = SCOPE,
) -> WorkItem:
    work = pending(store, memory_id, sources, text=text, binding=binding)
    assert store.complete(work, vector)
    return work


def vector_count(store: PgvectorMemoryStore, memory_id: str | None = None) -> int:
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT count(*) FROM embeddings WHERE (%s::text IS NULL OR memory_id=%s)",
            (memory_id, memory_id),
        ).fetchone()
        assert row is not None
        return int(row[0])


def status(store: PgvectorMemoryStore, memory_id: str) -> str:
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT index_status FROM memories WHERE memory_id=%s",
            (memory_id,),
        ).fetchone()
        assert row is not None
        return str(row[0])


def test_exact_cosine_matches_current_ranking_with_positive_filter_and_stable_ties(
    store: PgvectorMemoryStore,
) -> None:
    vectors = (
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
        (-1.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        (1.0, 2.0, 0.0),
    )
    memories = []
    for index, vector in enumerate(vectors):
        memory_id = f"synthetic-memory-{index}"
        evidence = source(store, f"synthetic-source-{index}")
        work = ready(store, memory_id, (evidence,), vector)
        memories.append(
            Memory(
                memory_id,
                "semantic",
                work.text,
                (
                    SourceVersion(
                        SourceReference(evidence.source_id, evidence.revision, 0), evidence.epoch
                    ),
                ),
            )
        )
    ordered = tuple(reversed(memories))
    expected = rank_memories(ordered, (VECTOR, *reversed(vectors)), SPACE, 8)
    actual = store.search(SCOPE, VECTOR)
    assert [hit.memory_id for hit in actual] == [memory.memory_id for memory in expected]
    assert [hit.memory_id for hit in actual[:2]] == ["synthetic-memory-4", "synthetic-memory-0"]
    assert all(hit.score > 0 and store.valid(hit.token) for hit in actual)
    assert [hit.score for hit in actual] == pytest.approx([1.0, 1.0, 2**-0.5, 5**-0.5], abs=1e-6)
    assert store.search(SCOPE, VECTOR, limit=2) == actual[:2]


@pytest.mark.parametrize(
    "invalid",
    [
        (0.0, 0.0, 0.0),
        (float("nan"), 0.0, 1.0),
        (float("inf"), 0.0, 1.0),
        (float("-inf"), 0.0, 1.0),
        (True, 0.0, 1.0),
        (1.0, 0.0),
        (1.0, 0.0, 0.0, 0.0),
    ],
)
def test_invalid_vectors_fail_before_indexing_or_search(
    store: PgvectorMemoryStore,
    invalid: tuple[float, ...],
) -> None:
    evidence = source(store, "synthetic-source")
    work = pending(store, "synthetic-memory", (evidence,))
    with pytest.raises(ValueError):
        store.complete(work, invalid)
    with pytest.raises(ValueError):
        store.search(SCOPE, invalid)
    with pytest.raises(CoreError):
        rank_memories((), (invalid,), SPACE, 1)
    assert vector_count(store) == 0 and status(store, work.memory_id) == "pending"


def test_scope_subject_client_character_are_separate_even_with_same_ids(
    store: PgvectorMemoryStore,
) -> None:
    bindings = (
        SCOPE,
        Binding(
            replace(SCOPE.scope, subject="other-synthetic-operator"),
            SCOPE.character_id,
        ),
        Binding(replace(SCOPE.scope, client="other-synthetic-client"), SCOPE.character_id),
        Binding(SCOPE.scope, "other-synthetic-character"),
    )
    for index, binding in enumerate(bindings):
        evidence = source(store, "same-synthetic-source", binding)
        ready(
            store,
            "same-synthetic-memory",
            (evidence,),
            text=f"Synthetic scope {index}.",
            binding=binding,
        )
    for index, binding in enumerate(bindings):
        hits = store.search(binding, VECTOR)
        assert len(hits) == 1 and hits[0].text == f"Synthetic scope {index}."
        assert hits[0].token.binding == binding and store.valid(hits[0].token)
        other = bindings[(index + 1) % len(bindings)]
        assert not store.valid(replace(hits[0].token, binding=other))


def test_unsupported_audience_is_rejected_not_treated_as_local_private(
    store: PgvectorMemoryStore,
) -> None:
    # 現 contract の audience は local-private のみ。反事実の入力を受理する試験ではない。
    invalid = Binding(
        replace(SCOPE.scope, audience=cast(Literal["local-private"], "synthetic-public")),
        SCOPE.character_id,
    )
    evidence = SourceSnapshot("synthetic-source", 1, 0)
    with pytest.raises(ValueError):
        store.put_source(invalid, evidence)
    with pytest.raises(ValueError):
        store.search(invalid, VECTOR)
    assert vector_count(store) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"private": True},
        {"excluded": True},
        {"deleted": True},
        {"role": "assistant"},
    ],
)
def test_ineligible_sources_never_enter_memory_projection(
    store: PgvectorMemoryStore,
    changes: dict[str, Any],
) -> None:
    evidence = SourceSnapshot("synthetic-ineligible-source", 1, 0, **changes)
    store.put_source(SCOPE, evidence)
    with pytest.raises(ValueError):
        store.put_memory(SCOPE, "synthetic-memory", "Synthetic evidence.", (evidence,))
    assert store.prepare(SCOPE, "synthetic-memory") is None
    assert not store.search(SCOPE, VECTOR) and vector_count(store) == 0


@pytest.mark.parametrize("flag", ["private", "excluded", "deleted"])
def test_one_revoked_source_purges_all_dependent_vectors_and_preserves_other_memory(
    store: PgvectorMemoryStore,
    flag: str,
) -> None:
    first, second = source(store, "synthetic-first"), source(store, "synthetic-second")
    ready(store, "synthetic-combined", (first, second))
    ready(store, "synthetic-first-only", (first,))
    ready(store, "synthetic-second-only", (second,))
    before = {hit.memory_id: hit for hit in store.search(SCOPE, VECTOR)}
    changed_flags: dict[str, Any] = {flag: True}
    store.put_source(SCOPE, replace(first, revision=2, epoch=1, **changed_flags))
    assert [hit.memory_id for hit in store.search(SCOPE, VECTOR)] == ["synthetic-second-only"]
    assert (
        vector_count(store, "synthetic-combined")
        == vector_count(store, "synthetic-first-only")
        == 0
    )
    assert vector_count(store, "synthetic-second-only") == 1
    assert not store.valid(before["synthetic-combined"].token)
    assert not store.valid(before["synthetic-first-only"].token)
    assert store.valid(before["synthetic-second-only"].token)
    assert store.prepare(SCOPE, "synthetic-combined") is None
    with store.transaction() as connection:
        rows = connection.execute(
            "SELECT memory_id,body FROM memories ORDER BY memory_id"
        ).fetchall()
    assert rows == [
        ("synthetic-combined", None),
        ("synthetic-first-only", None),
        ("synthetic-second-only", before["synthetic-second-only"].text),
    ]


def test_unprivate_does_not_restore_old_vector_or_epoch_without_explicit_rebuild(
    store: PgvectorMemoryStore,
) -> None:
    evidence = source(store, "synthetic-source")
    original = ready(store, "synthetic-memory", (evidence,))
    token = store.search(SCOPE, VECTOR)[0].token
    store.put_source(SCOPE, replace(evidence, revision=2, epoch=1, private=True))
    restored = replace(evidence, revision=3, epoch=2)
    store.put_source(SCOPE, restored)
    assert not store.search(SCOPE, VECTOR) and store.prepare(SCOPE, original.memory_id) is None
    assert not store.complete(original, VECTOR) and not store.valid(token)
    with pytest.raises(ValueError):
        pending(store, original.memory_id, (restored,))
    ready(store, "synthetic-rebuilt-memory", (restored,))
    assert store.search(SCOPE, VECTOR)[0].token.sources == (restored,)


def test_body_update_is_pending_and_purges_old_vector_without_reordering_ties(
    store: PgvectorMemoryStore,
) -> None:
    evidence = source(store, "synthetic-source")
    old = ready(store, "synthetic-old", (evidence,))
    ready(store, "synthetic-newer", (evidence,))
    hit = next(hit for hit in store.search(SCOPE, VECTOR) if hit.memory_id == old.memory_id)
    text = "Synthetic corrected evidence."
    revision = store.put_memory(SCOPE, old.memory_id, text, (evidence,))
    assert revision == old.revision + 1
    assert status(store, old.memory_id) == "pending" and vector_count(store, old.memory_id) == 0
    assert not store.valid(hit.token) and not store.complete(old, VECTOR)
    assert [item.memory_id for item in store.search(SCOPE, VECTOR)] == ["synthetic-newer"]
    work = store.prepare(SCOPE, old.memory_id)
    assert work is not None and work.text == text
    assert work.text_hash == hashlib.sha256(text.encode()).hexdigest()
    assert work.generation > old.generation and store.complete(work, VECTOR)
    assert [item.memory_id for item in store.search(SCOPE, VECTOR)] == [
        "synthetic-newer",
        "synthetic-old",
    ]


def test_delete_memory_purges_derived_vector_and_invalidates_search_guard(
    store: PgvectorMemoryStore,
) -> None:
    evidence = source(store, "synthetic-source")
    old = ready(store, "synthetic-delete", (evidence,))
    ready(store, "synthetic-retain", (evidence,))
    hit = next(hit for hit in store.search(SCOPE, VECTOR) if hit.memory_id == old.memory_id)
    store.delete_memory(SCOPE, old.memory_id)
    assert vector_count(store, old.memory_id) == 0
    assert not store.valid(hit.token) and not store.complete(old, VECTOR)
    assert store.prepare(SCOPE, old.memory_id) is None
    assert [item.memory_id for item in store.search(SCOPE, VECTOR)] == ["synthetic-retain"]
    with pytest.raises(ValueError):
        pending(store, old.memory_id, (evidence,))


@pytest.mark.parametrize("field", ["model", "revision", "configuration", "dimensions"])
def test_embedding_space_change_discards_old_vectors_and_pending_work(
    store: PgvectorMemoryStore,
    field: str,
) -> None:
    evidence = source(store, "synthetic-source")
    old = ready(store, "synthetic-memory", (evidence,))
    stale = pending(store, "synthetic-pending", (evidence,))
    token = store.search(SCOPE, VECTOR)[0].token
    value: str | int = 4 if field == "dimensions" else "synthetic-v2"
    space_changes: dict[str, Any] = {field: value}
    new_space = replace(SPACE, **space_changes)
    store.set_space(new_space)
    assert vector_count(store) == 0
    assert not store.valid(token) and not store.complete(stale, VECTOR)
    assert status(store, old.memory_id) == "pending"
    work = store.prepare(SCOPE, old.memory_id)
    assert work is not None and work.space == new_space
    assert work.space_generation > old.space_generation
    vector = (1.0,) + (0.0,) * (new_space.dimensions - 1)
    assert store.complete(work, vector)
    assert [hit.memory_id for hit in store.search(SCOPE, vector)] == [old.memory_id]


@pytest.mark.parametrize(
    "field",
    [
        "revision",
        "text_hash",
        "generation",
        "space_generation",
        "text",
        "sources",
        "binding",
        "memory_id",
        "space_model",
        "space_revision",
        "space_configuration",
        "space_dimensions",
        "bool_revision",
        "bool_generation",
        "bool_space_generation",
    ],
)
def test_forged_work_token_cannot_publish_a_vector(
    store: PgvectorMemoryStore,
    field: str,
) -> None:
    evidence = source(store, "synthetic-source")
    work = pending(store, "synthetic-memory", (evidence,))
    changes: dict[str, Any] = {
        "revision": work.revision + 1,
        "text_hash": "0" * 64,
        "generation": work.generation + 1,
        "space_generation": work.space_generation + 1,
        "text": "Synthetic different evidence.",
        "sources": (replace(evidence, epoch=1),),
        "binding": Binding(SCOPE.scope, "other-synthetic"),
        "memory_id": "other-synthetic-memory",
    }
    if field.startswith("bool_"):
        invalid_metadata: dict[str, Any] = {field.removeprefix("bool_"): True}
        forged = replace(work, **invalid_metadata)
    elif field.startswith("space_") and field != "space_generation":
        value: str | int = 4 if field == "space_dimensions" else "synthetic-other"
        space_changes: dict[str, Any] = {field.removeprefix("space_"): value}
        forged = replace(work, space=replace(work.space, **space_changes))
    else:
        forged = replace(work, **{field: changes[field]})
    assert not store.complete(forged, VECTOR)
    assert vector_count(store) == 0 and status(store, work.memory_id) == "pending"
    assert store.complete(work, VECTOR)


@pytest.mark.parametrize("change", ["private", "body", "delete", "space"])
async def test_change_while_synthetic_embedding_awaits_prevents_stale_commit(
    store: PgvectorMemoryStore,
    change: str,
) -> None:
    evidence = source(store, "synthetic-source")
    work = pending(store, "synthetic-memory", (evidence,))
    started, resume = asyncio.Event(), asyncio.Event()

    async def synthetic_embedding() -> bool:
        started.set()
        await resume.wait()
        return store.complete(work, VECTOR)

    task = asyncio.create_task(synthetic_embedding())
    await started.wait()
    try:
        if change == "private":
            store.put_source(SCOPE, replace(evidence, revision=2, epoch=1, private=True))
        elif change == "body":
            store.put_memory(SCOPE, work.memory_id, "Synthetic changed body.", (evidence,))
        elif change == "delete":
            store.delete_memory(SCOPE, work.memory_id)
        else:
            store.set_space(replace(SPACE, revision="synthetic-v2"))
    finally:
        resume.set()
    assert not await task
    assert vector_count(store) == 0 and not store.search(SCOPE, VECTOR)


def test_source_revision_and_epoch_cannot_move_backwards(store: PgvectorMemoryStore) -> None:
    current = SourceSnapshot("synthetic-source", 4, 3)
    store.put_source(SCOPE, current)
    work = ready(store, "synthetic-memory", (current,))
    for older in (replace(current, revision=3), replace(current, epoch=2)):
        with pytest.raises(ValueError):
            store.put_source(SCOPE, older)
    assert store.valid(store.search(SCOPE, VECTOR)[0].token)
    assert vector_count(store, work.memory_id) == 1


def test_revocation_vector_purge_rolls_back_with_authoritative_update(
    store: PgvectorMemoryStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = source(store, "synthetic-source")
    ready(store, "synthetic-memory", (evidence,))
    before = store.search(SCOPE, VECTOR)[0]
    execute = Connection.execute
    observed: list[int] = []

    def interrupt_after_purge(
        connection: Any, query: Any, params: Any = None, **kwargs: Any
    ) -> Any:
        result = execute(connection, query, params, **kwargs)
        rendered = query if isinstance(query, str) else query.as_string(connection)
        if "DELETE FROM embeddings" in rendered:
            row = execute(connection, "SELECT count(*) FROM embeddings").fetchone()
            assert row is not None
            observed.append(row[0])
            erased = execute(connection, "SELECT body FROM memories").fetchall()
            assert erased == [(None,)]
            raise RuntimeError("synthetic rollback after derived purge")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Connection, "execute", interrupt_after_purge)
        with pytest.raises(RuntimeError, match="synthetic rollback"):
            store.put_source(SCOPE, replace(evidence, revision=2, epoch=1, private=True))
    assert observed == [0]
    assert vector_count(store) == 1 and store.valid(before.token)
    assert store.search(SCOPE, VECTOR) == (before,)


def test_source_aba_does_not_revive_work_or_dispatch_token(store: PgvectorMemoryStore) -> None:
    evidence = source(store, "synthetic-source")
    ready(store, "synthetic-ready", (evidence,))
    stale = pending(store, "synthetic-pending", (evidence,))
    token = store.search(SCOPE, VECTOR)[0].token
    store.put_source(SCOPE, replace(evidence, private=True))
    store.put_source(SCOPE, evidence)
    assert not store.complete(stale, VECTOR) and not store.valid(token)
    assert not store.search(SCOPE, VECTOR) and vector_count(store) == 0
    with pytest.raises(ValueError):
        pending(store, stale.memory_id, (evidence,))
    assert store.prepare(SCOPE, stale.memory_id) is None


def test_space_aba_does_not_revive_work_or_dispatch_token(store: PgvectorMemoryStore) -> None:
    evidence = source(store, "synthetic-source")
    ready(store, "synthetic-ready", (evidence,))
    stale = pending(store, "synthetic-pending", (evidence,))
    token = store.search(SCOPE, VECTOR)[0].token
    store.set_space(replace(SPACE, revision="synthetic-v2"))
    store.set_space(SPACE)
    assert not store.complete(stale, VECTOR) and not store.valid(token)
    current = store.prepare(SCOPE, stale.memory_id)
    assert current is not None and current.space_generation > stale.space_generation
    assert current.space == stale.space and store.complete(current, VECTOR)


def test_same_body_rebuild_invalidates_previous_revision_and_dispatch_token(
    store: PgvectorMemoryStore,
) -> None:
    evidence = source(store, "synthetic-source")
    old = ready(store, "synthetic-memory", (evidence,))
    token = store.search(SCOPE, VECTOR)[0].token
    current = pending(store, old.memory_id, (evidence,), text=old.text)
    assert current.text_hash == old.text_hash
    assert current.revision > old.revision and current.generation > old.generation
    assert not store.valid(token) and not store.complete(old, VECTOR)
    assert store.complete(current, VECTOR)
    assert not store.valid(token)


def test_scope_and_eligibility_are_filtered_before_top_one_limit(
    store: PgvectorMemoryStore,
) -> None:
    evidence = source(store, "synthetic-eligible-source")
    ready(store, "synthetic-eligible", (evidence,), (1.0, 1.0, 0.0))
    other = Binding(SCOPE.scope, "other-synthetic-character")
    foreign_source = source(store, "synthetic-other-source", other)
    ready(store, "synthetic-other", (foreign_source,), binding=other)
    revoked = source(store, "synthetic-revoked-source")
    ready(store, "synthetic-revoked", (revoked,))
    store.put_source(SCOPE, replace(revoked, excluded=True))
    hits = store.search(SCOPE, VECTOR, limit=1)
    assert len(hits) == 1 and hits[0].memory_id == "synthetic-eligible"
    assert hits[0].score == pytest.approx(2**-0.5, abs=1e-6)


def test_provenance_preserves_conversation_turn_message_index_epoch_and_order(
    store: PgvectorMemoryStore,
) -> None:
    first = SourceSnapshot(
        "synthetic-source-first",
        7,
        4,
        conversation_id="synthetic-conversation",
        message_index=3,
        turn_revision=2,
    )
    second = SourceSnapshot(
        "synthetic-source-second",
        11,
        6,
        conversation_id="synthetic-conversation",
        message_index=1,
        turn_revision=2,
    )
    third = SourceSnapshot(
        "synthetic-source-third",
        8,
        5,
        conversation_id="synthetic-other-conversation",
        message_index=4,
        turn_revision=9,
    )
    for item in (first, second, third):
        store.put_source(SCOPE, item)
    ordered = (third, second, first)
    work = ready(store, "synthetic-memory", ordered)
    assert work.sources == store.search(SCOPE, VECTOR)[0].token.sources == ordered
    exported = store.export_eligible(SCOPE)
    assert exported[0][0].sources == (
        SourceVersion(SourceReference("synthetic-other-conversation", 9, 4), 5),
        SourceVersion(SourceReference("synthetic-conversation", 2, 1), 6),
        SourceVersion(SourceReference("synthetic-conversation", 2, 3), 4),
    )
    token = store.search(SCOPE, VECTOR)[0].token
    store.put_source(SCOPE, replace(second, revision=12, message_index=2))
    assert not store.valid(token) and not store.search(SCOPE, VECTOR)
    assert vector_count(store) == 0


def test_scope_transfer_requires_destination_sources_and_removes_old_vectors(
    store: PgvectorMemoryStore,
) -> None:
    evidence = source(store, "synthetic-source")
    old = ready(store, "synthetic-memory", (evidence,))
    token = store.search(SCOPE, VECTOR)[0].token
    destination = Binding(SCOPE.scope, "other-synthetic-character")
    with pytest.raises(ValueError):
        store.move_memory(SCOPE, destination, old.memory_id)
    assert store.valid(token) and vector_count(store) == 1
    store.put_source(destination, evidence)
    store.move_memory(SCOPE, destination, old.memory_id)
    assert not store.valid(token) and not store.complete(old, VECTOR)
    assert not store.search(SCOPE, VECTOR) and vector_count(store) == 0
    current = store.prepare(destination, old.memory_id)
    assert current is not None and store.complete(current, VECTOR)
    assert store.search(destination, VECTOR)[0].token.binding == destination
    with pytest.raises(ValueError):
        store.move_memory(destination, SCOPE, old.memory_id)


def test_duplicate_source_alias_cannot_hide_a_revoked_original_message(
    store: PgvectorMemoryStore,
) -> None:
    evidence = SourceSnapshot(
        "synthetic-source",
        4,
        2,
        conversation_id="synthetic-conversation",
        turn_revision=2,
        message_index=3,
    )
    store.put_source(SCOPE, evidence)
    ready(store, "synthetic-memory", (evidence,))
    with pytest.raises((ValueError, psycopg.errors.UniqueViolation)):
        store.put_source(SCOPE, replace(evidence, source_id="synthetic-alias"))
    store.put_source(SCOPE, replace(evidence, excluded=True))
    assert not store.search(SCOPE, VECTOR) and vector_count(store) == 0
