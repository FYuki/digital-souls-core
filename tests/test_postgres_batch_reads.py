"""Measure real PostgreSQL statements and fetched source rows for batched reads."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from psycopg import Connection, sql

from digital_souls_core.contracts import Message
from digital_souls_core.history import SourceReference
from digital_souls_core.memory_contracts import Candidate, Memory

from . import test_postgres_stores
from .test_postgres_stores import BINDING, MESSAGES, Stores, seed

pytestmark = pytest.mark.postgres
stores = test_postgres_stores.stores


@dataclass
class Queries:
    statements: list[str] = field(default_factory=list)
    source_bodies: list[str] = field(default_factory=list)


@contextmanager
def observe_queries(monkeypatch: pytest.MonkeyPatch) -> Iterator[Queries]:
    observed = Queries()
    original = Connection.execute

    def execute(
        connection: Connection[tuple[Any, ...]], query: Any, *args: Any, **kwargs: Any
    ) -> Any:
        text = query.as_string(connection) if isinstance(query, sql.Composable) else str(query)
        observed.statements.append(text)
        cursor = original(connection, query, *args, **kwargs)
        # Inspect libpq's result without consuming the cursor or issuing another
        # query. This measures bodies transferred from PostgreSQL, not Python
        # helper invocations or just the final filtered result.
        result = cursor.pgresult
        if result is not None:
            for column_index, column in enumerate(cursor.description or ()):
                if column.name == "messages":
                    for row in range(result.ntuples):
                        value = result.get_value(row, column_index)
                        assert value is not None
                        observed.source_bodies.append(value.decode("utf-8"))
        return cursor

    with monkeypatch.context() as patch:
        patch.setattr(Connection, "execute", execute)
        yield observed


def invoke(
    stores: Stores, operation: str, job_id: str, expected: tuple[Memory, ...]
) -> tuple[Memory, ...] | bool:
    if operation == "candidates":
        return stores.memory.candidates(BINDING)
    if operation == "results":
        return stores.memory.results(BINDING, job_id)
    if operation == "search":
        return stores.memory.search(BINDING, "synthetic", limit=16)
    assert operation == "valid"
    return stores.memory.valid(BINDING, expected)


def selected(stores: Stores, refs: tuple[SourceReference, ...]) -> Candidate:
    evidence = stores.memory.sources(BINDING, refs)
    return Candidate(
        "semantic",
        tuple(item.source for item in evidence),
        json.dumps([item.text for item in evidence], ensure_ascii=False),
    )


@pytest.mark.parametrize("operation", ["candidates", "results", "search", "valid"])
def test_read_statement_count_is_constant_for_one_ten_and_twenty_memories(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    refs = (seed(stores, "Synthetic tea."), seed(stores, "Synthetic mint."))
    value = selected(stores, refs)
    counts = []
    for size in (1, 10, 20):
        # One job can emit several candidates. Keeping the same two real sources
        # isolates the extra database work caused by increasing memory count.
        with stores.database.transaction(BINDING) as connection:
            connection.execute("DELETE FROM memories")
        job = stores.memory.begin(BINDING, value.sources, f"synthetic-size-{size}")
        stores.memory.commit(BINDING, job, (value,) * size)
        expected = stores.memory.results(BINDING, job.job_id)
        assert len(expected) == size and all(len(memory.sources) == 2 for memory in expected)
        with observe_queries(monkeypatch) as queries:
            result = invoke(stores, operation, job.job_id, expected)
        assert result == (
            True if operation == "valid" else expected[:16] if operation == "search" else expected
        )
        counts.append(len(queries.statements))
    # Include connection setup and scope-lock statements, not just data SELECTs.
    # The bound allows minor constant setup changes while rejecting N+1 growth.
    assert 0 < counts[0] <= 8
    assert counts == [counts[0]] * 3
    print(f"{operation}: PostgreSQL statements for 1/10/20 memories = {counts}")


def append_turn(stores: Stores, conversation: str, revision: int, *texts: str) -> None:
    stores.history.append(
        BINDING,
        conversation,
        f"request-{revision}",
        f"fingerprint-{revision}",
        revision,
        tuple(Message(role="user", content=text) for text in texts) + (MESSAGES[-1],),
        "stop",
    )


def test_batch_preserves_memory_order_and_source_order_across_turns_and_positions(
    stores: Stores,
) -> None:
    first = stores.history.create(BINDING).conversation_id
    second = stores.history.create(BINDING).conversation_id
    append_turn(stores, first, 0, "Synthetic first position.", "Synthetic second position.")
    append_turn(stores, first, 1, "Synthetic later turn.")
    append_turn(stores, second, 0, "Synthetic second conversation.")
    ordered = (
        SourceReference(second, 1, 0),
        SourceReference(first, 1, 1),
        SourceReference(first, 2, 0),
        SourceReference(first, 1, 0),
    )
    older = selected(stores, ordered)
    newer = selected(stores, (ordered[2], ordered[1]))
    job = stores.memory.begin(BINDING, older.sources, "synthetic-mixed-order")
    stores.memory.commit(BINDING, job, (older, newer))
    results = stores.memory.results(BINDING, job.job_id)
    assert [(memory.text, memory.sources) for memory in results] == [
        (newer.text, newer.sources),
        (older.text, older.sources),
    ]
    assert stores.memory.candidates(BINDING) == results
    assert stores.memory.search(BINDING, "synthetic") == results
    assert stores.memory.valid(BINDING, results)


@pytest.mark.parametrize("operation", ["candidates", "results", "search", "valid"])
def test_batch_fetches_only_exact_conversation_revision_pairs(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    first = stores.history.create(BINDING).conversation_id
    second = stores.history.create(BINDING).conversation_id
    append_turn(stores, first, 0, "Synthetic selected first.")
    append_turn(stores, first, 1, "Synthetic unrelated first later turn.")
    append_turn(stores, second, 0, "Synthetic unrelated second earlier turn.")
    append_turn(stores, second, 1, "Synthetic selected second.")
    seed(stores, "Synthetic unrelated other conversation.")
    value = selected(stores, (SourceReference(first, 1, 0), SourceReference(second, 2, 0)))
    job = stores.memory.begin(BINDING, value.sources, "synthetic-exact-pairs")
    stores.memory.commit(BINDING, job, (value,))
    expected = stores.memory.results(BINDING, job.job_id)
    with observe_queries(monkeypatch) as queries:
        result = invoke(stores, operation, job.job_id, expected)
    assert result == (True if operation == "valid" else expected)
    assert len(queries.source_bodies) == 2
    fetched_texts = {json.loads(body)[0]["content"] for body in queries.source_bodies}
    assert fetched_texts == {"Synthetic selected first.", "Synthetic selected second."}
    assert "unrelated" not in repr(queries.source_bodies)


@pytest.mark.parametrize("invalid", ["private", "private_turn", "excluded", "deleted", "epoch"])
def test_batched_eligibility_and_valid_reject_a_changed_source(
    stores: Stores, invalid: str
) -> None:
    conversation = stores.history.create(BINDING).conversation_id
    append_turn(
        stores, conversation, 0, "Synthetic shared turn first.", "Synthetic shared turn second."
    )
    append_turn(stores, conversation, 1, "Synthetic later evidence.")
    value = selected(
        stores,
        (SourceReference(conversation, 1, 1), SourceReference(conversation, 2, 0)),
    )
    job = stores.memory.begin(BINDING, value.sources, "synthetic-invalidation")
    stores.memory.commit(BINDING, job, (value,))
    prior = stores.memory.results(BINDING, job.job_id)
    independent = test_postgres_stores.remember(stores, (seed(stores, "Synthetic independent."),))
    assert stores.memory.valid(BINDING, prior + independent)
    # Modify only source metadata in the synthetic DB, deliberately leaving the
    # memory row active. Retrieval must recheck eligibility, even without a purge.
    with stores.database.transaction(BINDING) as connection:
        if invalid == "private":
            connection.execute(
                "UPDATE conversations SET private_mode=true WHERE id=%s", (conversation,)
            )
        elif invalid == "epoch":
            connection.execute(
                "UPDATE conversations SET memory_epoch=1 WHERE id=%s", (conversation,)
            )
        elif invalid == "deleted":
            connection.execute(
                "DELETE FROM turns WHERE conversation=%s AND revision=1", (conversation,)
            )
        elif invalid == "private_turn":
            connection.execute(
                "UPDATE turns SET private_mode=true WHERE conversation=%s AND revision=1",
                (conversation,),
            )
        else:
            connection.execute(
                "UPDATE turns SET memory_excluded='[1]' WHERE conversation=%s AND revision=1",
                (conversation,),
            )
    assert not stores.memory.valid(BINDING, prior)
    assert not stores.memory.valid(BINDING, independent + prior)
    assert stores.memory.valid(BINDING, independent)
    assert stores.memory.results(BINDING, job.job_id) == ()
    assert stores.memory.candidates(BINDING) == independent
    assert stores.memory.search(BINDING, "synthetic") == independent


def test_empty_batch_preserves_vacuous_validity_and_fetches_no_source_body(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(stores, "Synthetic unselected history.")
    with observe_queries(monkeypatch) as queries:
        assert stores.memory.candidates(BINDING) == ()
        assert stores.memory.results(BINDING, "synthetic-unknown-job") == ()
        assert stores.memory.search(BINDING, "synthetic") == ()
        assert stores.memory.valid(BINDING, ())
    assert queries.source_bodies == []


def test_distinct_source_pair_count_does_not_add_database_statements(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    refs = tuple(seed(stores, f"Synthetic distinct source {index}.") for index in range(16))
    counts: dict[str, list[int]] = {
        name: [] for name in ("candidates", "results", "search", "valid")
    }
    for size in (1, 8, 16):
        with stores.database.transaction(BINDING) as connection:
            connection.execute("DELETE FROM memories")
        value = selected(stores, refs[:size])
        job = stores.memory.begin(BINDING, value.sources, f"synthetic-pairs-{size}")
        stores.memory.commit(BINDING, job, (value,))
        expected = stores.memory.results(BINDING, job.job_id)
        assert len(expected) == 1 and len(expected[0].sources) == size
        for operation in counts:
            with observe_queries(monkeypatch) as queries:
                result = invoke(stores, operation, job.job_id, expected)
            assert result == (True if operation == "valid" else expected)
            assert len(queries.source_bodies) == size
            counts[operation].append(len(queries.statements))
    for operation, measured in counts.items():
        assert 0 < measured[0] <= 8
        assert measured == [measured[0]] * 3
        print(f"{operation}: PostgreSQL statements for 1/8/16 distinct source pairs = {measured}")
