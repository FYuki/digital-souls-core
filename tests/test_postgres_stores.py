import json
import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from threading import Barrier, Event
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, sql

from digital_souls_core import postgres_history, postgres_schema
from digital_souls_core.application import CoreError
from digital_souls_core.character import AccessScope
from digital_souls_core.contracts import Message
from digital_souls_core.history import Binding, ConversationControls, SourceReference
from digital_souls_core.memory_contracts import Candidate, Memory, MemoryJob
from digital_souls_core.postgres_db import PostgresConfig, PostgresDatabase
from digital_souls_core.postgres_history import PostgresHistory
from digital_souls_core.postgres_memory import PostgresMemory

pytestmark = pytest.mark.postgres
BINDING = Binding(AccessScope(), "synthetic")
MESSAGES = (
    Message(role="user", content="I like synthetic tea."),
    Message(role="assistant", content="Synthetic answer."),
)


@contextmanager
def raw_connection(config: PostgresConfig) -> Iterator[Connection[tuple[Any, ...]]]:
    with psycopg.connect(
        host=config.host,
        port=config.port,
        dbname=config.database,
        user=config.user,
        password="",
        passfile="/dev/null/no-passfile",
        connect_timeout=5,
        sslmode="disable",
        gssencmode="disable",
        autocommit=True,
    ) as connection:
        yield connection


@dataclass
class Stores:
    config: PostgresConfig
    database: PostgresDatabase
    history: PostgresHistory
    memory: PostgresMemory


@pytest.fixture
def stores() -> Iterator[Stores]:
    names = (
        "DSC_TEST_POSTGRES_SOCKET",
        "DSC_TEST_POSTGRES_PORT",
        "DSC_TEST_POSTGRES_DATABASE",
        "DSC_TEST_POSTGRES_USER",
    )
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.fail("PostgreSQL synthetic test configuration is required: " + ", ".join(missing))
    config = PostgresConfig(
        host=os.environ[names[0]],
        port=int(os.environ[names[1]]),
        database=os.environ[names[2]],
        user=os.environ[names[3]],
        schema_name="dsc_test_" + uuid4().hex,
    )
    assert config.host.startswith("/"), "PostgreSQL tests require a local Unix socket"
    database = PostgresDatabase(config)
    try:
        history = PostgresHistory(database)
        memory = PostgresMemory(database)
        yield Stores(config, database, history, memory)
    finally:
        # The only dropped object is this fixture's freshly generated schema.
        with raw_connection(config) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(config.schema_name)
                )
            )


def seed(stores: Stores, text: str = "I like synthetic tea.") -> SourceReference:
    conversation = stores.history.create(BINDING)
    stores.history.append(
        BINDING,
        conversation.conversation_id,
        "synthetic-request",
        "synthetic-fingerprint",
        0,
        (Message(role="user", content=text), MESSAGES[-1]),
        "stop",
    )
    return SourceReference(conversation.conversation_id, 1, 0)


def candidate(stores: Stores, job: MemoryJob) -> Candidate:
    evidence = stores.memory.sources(BINDING, tuple(source.reference for source in job.sources))
    return Candidate(
        "semantic", job.sources, json.dumps([item.text for item in evidence], ensure_ascii=False)
    )


def prepare(stores: Stores, refs: tuple[SourceReference, ...]) -> tuple[MemoryJob, Candidate]:
    evidence = stores.memory.sources(BINDING, refs)
    job = stores.memory.begin(BINDING, tuple(item.source for item in evidence), "synthetic-v1")
    return job, candidate(stores, job)


def remember(stores: Stores, refs: tuple[SourceReference, ...]) -> tuple[Memory, ...]:
    job, selected = prepare(stores, refs)
    stores.memory.commit(BINDING, job, (selected,))
    result = stores.memory.results(BINDING, job.job_id)
    assert len(result) == 1
    return result


def revoke(history: PostgresHistory, ref: SourceReference, action: str) -> None:
    if action == "delete":
        history.delete(BINDING, ref.conversation_id)
    else:
        history.controls(
            BINDING,
            ref.conversation_id,
            ConversationControls(expected_revision=1, private_mode=True),
        )


def test_history_order_retry_cas_reopen_and_delete(stores: Stores) -> None:
    history = stores.history
    first, second = history.create(BINDING), history.create(BINDING)
    assert history.list(BINDING) == [first.conversation_id, second.conversation_id]
    receipt = history.append(BINDING, first.conversation_id, "r1", "fp1", 0, MESSAGES, "stop")
    history = PostgresHistory(PostgresDatabase(stores.config))
    assert (
        history.append(BINDING, first.conversation_id, "r1", "fp1", 0, MESSAGES, "stop") == receipt
    )
    assert history.receipt(BINDING, first.conversation_id, "r1") == receipt
    for request, fingerprint, code in (
        ("r1", "different", "request_conflict"),
        ("r2", "fp2", "revision_conflict"),
    ):
        with pytest.raises(CoreError) as error:
            history.append(
                BINDING, first.conversation_id, request, fingerprint, 0, MESSAGES, "stop"
            )
        assert error.value.code == code
    history.append(BINDING, first.conversation_id, "r2", "fp2", 1, MESSAGES, "stop")
    snapshot = history.read(BINDING, first.conversation_id)
    assert snapshot.revision == 2 and snapshot.messages == MESSAGES * 2
    history.delete(BINDING, first.conversation_id)
    history.delete(BINDING, first.conversation_id)
    assert history.receipt(BINDING, first.conversation_id, "r1") is None
    assert history.list(BINDING) == [second.conversation_id]
    with pytest.raises(CoreError) as error:
        history.read(BINDING, first.conversation_id)
    assert error.value.code == "conversation_not_found"
    deletions = history.deletions(BINDING)
    assert len(deletions) == 1
    assert deletions[0].conversation_id == first.conversation_id
    assert deletions[0].through_revision == 2
    history.acknowledge_deletion(BINDING, deletions[0].event_id)
    history.acknowledge_deletion(BINDING, deletions[0].event_id)
    assert history.deletions(BINDING) == ()


@pytest.mark.parametrize("excluded", [(0, 0), (1,), (-1,), (True,), (99,)])
def test_invalid_exclusion_rolls_back_revision_and_turn(
    stores: Stores, excluded: tuple[int, ...]
) -> None:
    conversation = stores.history.create(BINDING)
    with pytest.raises(CoreError) as error:
        stores.history.append(
            BINDING,
            conversation.conversation_id,
            "r1",
            "fp1",
            0,
            MESSAGES,
            "stop",
            memory_excluded_indices=excluded,
        )
    assert error.value.code == "invalid_exclusions"
    assert stores.history.read(BINDING, conversation.conversation_id) == conversation
    assert stores.history.receipt(BINDING, conversation.conversation_id, "r1") is None


def test_private_turn_and_explicit_exclusions_remain_ineligible_after_reopening(
    stores: Stores,
) -> None:
    history = stores.history
    conversation = history.create(BINDING).conversation_id
    history.append(
        BINDING, conversation, "r1", "fp1", 0, MESSAGES, "stop", memory_excluded_indices=(0,)
    )
    assert not any(source.eligible for source in history.read(BINDING, conversation).memory_sources)
    history.controls(
        BINDING, conversation, ConversationControls(expected_revision=1, private_mode=True)
    )
    history.append(BINDING, conversation, "r2", "fp2", 2, MESSAGES, "stop")
    history.controls(
        BINDING, conversation, ConversationControls(expected_revision=3, private_mode=False)
    )
    history.append(BINDING, conversation, "r3", "fp3", 4, MESSAGES, "stop")
    snapshot = history.read(BINDING, conversation)
    assert snapshot.revision == 5
    assert [source.eligible for source in snapshot.memory_sources] == [False] * 4 + [True, False]
    for ref in (SourceReference(conversation, 1, 0), SourceReference(conversation, 3, 0)):
        assert not history.source_eligible(BINDING, ref)
        with pytest.raises(CoreError):
            stores.memory.sources(BINDING, (ref,))
    assert stores.memory.sources(BINDING, (SourceReference(conversation, 5, 0),))


def test_archive_controls_and_stale_cas_preserve_memory(stores: Stores) -> None:
    ref = seed(stores)
    memories = remember(stores, (ref,))
    with pytest.raises(CoreError) as error:
        stores.history.controls(
            BINDING,
            ref.conversation_id,
            ConversationControls(expected_revision=0, private_mode=True),
        )
    assert error.value.code == "revision_conflict"
    assert stores.memory.events(BINDING) == ()
    updated = stores.history.controls(
        BINDING, ref.conversation_id, ConversationControls(expected_revision=1, archived=True)
    )
    assert updated.archived and updated.revision == 2
    assert stores.history.list(BINDING) == []
    assert stores.history.list(BINDING, include_archived=True) == [ref.conversation_id]
    assert stores.memory.search(BINDING, "TEA") == memories


@pytest.mark.parametrize(
    "other",
    [
        Binding(AccessScope(subject="other"), "synthetic"),
        Binding(AccessScope(client="other"), "synthetic"),
        Binding(AccessScope(audience="other"), "synthetic"),  # type: ignore[arg-type]
        replace(BINDING, character_id="other"),
    ],
)
def test_scope_isolation_covers_history_memory_jobs_and_outboxes(
    stores: Stores, other: Binding
) -> None:
    ref = seed(stores)
    job, selected = prepare(stores, (ref,))
    stores.memory.commit(BINDING, job, (selected,))
    memories = stores.memory.results(BINDING, job.job_id)
    assert stores.history.list(other) == []
    assert stores.history.receipt(other, ref.conversation_id, "synthetic-request") is None
    assert not stores.history.source_eligible(other, ref)
    with pytest.raises(CoreError):
        stores.history.read(other, ref.conversation_id)
    with pytest.raises(CoreError):
        stores.history.append(other, ref.conversation_id, "r2", "fp2", 1, MESSAGES, "stop")
    with pytest.raises(CoreError):
        stores.memory.sources(other, (ref,))
    with pytest.raises(CoreError):
        stores.memory.commit(other, job, (selected,))
    stores.history.delete(other, ref.conversation_id)
    assert stores.history.read(BINDING, ref.conversation_id).revision == 1
    assert stores.memory.search(other, "tea") == ()
    assert stores.memory.results(other, job.job_id) == ()
    assert stores.memory.pending(other) == ()
    assert not stores.memory.current(other, job.sources)
    assert not stores.memory.valid(other, memories)
    stores.history.delete(BINDING, ref.conversation_id)
    event = stores.memory.events(BINDING)[0]
    deletion = stores.history.deletions(BINDING)[0]
    stores.memory.consume(other, event)
    stores.history.acknowledge_deletion(other, deletion.event_id)
    assert stores.memory.events(BINDING) == (event,)
    assert stores.history.deletions(BINDING) == (deletion,)
    assert stores.memory.events(other) == () and stores.history.deletions(other) == ()


def test_memory_provenance_reopen_canonical_retry_and_literal_search(stores: Stores) -> None:
    refs = (seed(stores, "抹茶 synthetic tea %_"), seed(stores, "Synthetic mint."))
    job, selected = prepare(stores, refs)
    same = stores.memory.begin(BINDING, tuple(reversed(job.sources)), job.versions)
    assert same.job_id == job.job_id and same.sources == job.sources
    stores.memory.commit(BINDING, job, (selected,))
    memory = PostgresMemory(PostgresDatabase(stores.config))
    memory.commit(BINDING, job, (selected,))
    results = memory.results(BINDING, job.job_id)
    assert len(results) == 1
    assert results[0].sources == job.sources and all(source.epoch == 0 for source in job.sources)
    assert set(source.reference for source in results[0].sources) == set(refs)
    assert memory.search(BINDING, "TEA") == results
    assert memory.search(BINDING, "%_") == results
    assert memory.search(BINDING, "' OR 1=1 --") == ()
    assert memory.search(BINDING, "no synthetic match") == ()
    assert memory.pending(BINDING) == ()


@pytest.mark.parametrize("role", ["assistant", "tool"])
def test_non_user_source_is_not_memory_evidence(stores: Stores, role: str) -> None:
    conversation = stores.history.create(BINDING).conversation_id
    message = (
        Message(role="assistant", content="Synthetic suggestion")
        if role == "assistant"
        else Message(role="tool", content="Synthetic tool output", tool_call_id="synthetic-call")
    )
    stores.history.append(BINDING, conversation, "r1", "fp1", 0, (message, MESSAGES[-1]), "stop")
    with pytest.raises(CoreError) as error:
        stores.memory.sources(BINDING, (SourceReference(conversation, 1, 0),))
    assert error.value.code == "memory_source_invalid"


@pytest.mark.parametrize("action", ["private", "delete"])
def test_multisource_revocation_purges_body_and_rebuilds_only_original_epochs(
    stores: Stores, action: str
) -> None:
    refs = (seed(stores, "Synthetic tea."), seed(stores, "Synthetic mint."))
    memories = remember(stores, refs)
    revoke(stores.history, refs[0], action)
    if action == "private":
        stores.history.controls(
            BINDING,
            refs[0].conversation_id,
            ConversationControls(expected_revision=2, private_mode=False),
        )
        assert stores.history.source_eligible(BINDING, refs[0])
    assert not stores.memory.valid(BINDING, memories)
    assert stores.memory.search(BINDING, "synthetic") == ()
    with stores.database.transaction(BINDING) as connection:
        assert connection.execute("SELECT body,state FROM memories").fetchall() == [
            (None, "revoked")
        ]
    memory = PostgresMemory(PostgresDatabase(stores.config))
    events = memory.events(BINDING)
    assert len(events) == 1
    memory.consume(BINDING, events[0])
    memory.consume(BINDING, events[0])
    assert memory.events(BINDING) == ()
    jobs = memory.pending(BINDING)
    assert len(jobs) == 1
    assert tuple(source.reference for source in jobs[0].sources) == (refs[1],)
    memory.commit(BINDING, jobs[0], (candidate(stores, jobs[0]),))
    rebuilt = memory.search(BINDING, "mint")
    assert len(rebuilt) == 1 and rebuilt[0].memory_id != memories[0].memory_id
    assert memory.search(BINDING, "tea") == ()
    if action == "private":
        fresh = remember(stores, (refs[0],))
        assert fresh[0].sources[0].epoch == 1
        assert fresh[0].memory_id != memories[0].memory_id


def test_rebase_never_restores_a_revoked_original_source(stores: Stores) -> None:
    refs = tuple(seed(stores, f"Synthetic plant {index}.") for index in range(3))
    original, _ = prepare(stores, refs)
    stores.history.delete(BINDING, refs[0].conversation_id)
    remaining = stores.memory.rebase(BINDING, original)
    assert remaining is not None and len(remaining.sources) == 2
    assert stores.memory.rebase(BINDING, original) is None
    stores.history.delete(BINDING, refs[1].conversation_id)
    last = stores.memory.rebase(BINDING, remaining)
    assert last is not None and tuple(source.reference for source in last.sources) == (refs[2],)
    stores.memory.commit(BINDING, last, (candidate(stores, last),))
    results = stores.memory.results(BINDING, last.job_id)
    assert len(results) == 1 and results[0].sources == last.sources
    assert stores.memory.pending(BINDING) == ()


def test_candidate_mismatch_rolls_back_prior_candidate_and_keeps_job_retryable(
    stores: Stores,
) -> None:
    job, valid = prepare(stores, (seed(stores),))
    invalid = replace(valid, text=json.dumps(["Synthetic unsupported inference."]))
    with pytest.raises(CoreError) as error:
        stores.memory.commit(BINDING, job, (valid, invalid))
    assert error.value.code == "memory_denied"
    assert stores.memory.results(BINDING, job.job_id) == ()
    assert stores.memory.pending(BINDING) == (job,)
    stores.memory.commit(BINDING, job, (valid,))
    assert len(stores.memory.results(BINDING, job.job_id)) == 1


def test_failed_attempt_cannot_retire_or_commit_successor(stores: Stores) -> None:
    job, selected = prepare(stores, (seed(stores),))
    stores.memory.fail(BINDING, job)
    successor = stores.memory.begin(BINDING, job.sources, job.versions)
    assert successor.job_id != job.job_id
    stores.memory.fail(BINDING, job)
    with pytest.raises(CoreError):
        stores.memory.commit(BINDING, job, (selected,))
    assert stores.memory.pending(BINDING) == (successor,)
    stores.memory.commit(BINDING, successor, (selected,))
    stores.memory.fail(BINDING, successor)
    assert len(stores.memory.results(BINDING, successor.job_id)) == 1
    assert stores.memory.pending(BINDING) == ()


@pytest.mark.parametrize("query,limit", [("", 8), ("x" * 257, 8), ("tea", 0), ("tea", 17)])
def test_memory_query_bounds(stores: Stores, query: str, limit: int) -> None:
    with pytest.raises(CoreError) as error:
        stores.memory.search(BINDING, query, limit)
    assert error.value.code == "memory_query_invalid"


def test_unknown_schema_version_is_preserved_and_rejected(stores: Stores) -> None:
    ref = seed(stores)
    with stores.database.transaction(BINDING) as connection:
        connection.execute("UPDATE schema_version SET version=99")
    with pytest.raises(CoreError) as error:
        PostgresDatabase(stores.config).initialize()
    assert error.value.code == "storage_schema"
    assert stores.history.read(BINDING, ref.conversation_id).messages == MESSAGES
    with stores.database.transaction(BINDING) as connection:
        assert connection.execute("SELECT version FROM schema_version").fetchall() == [(99,)]


@pytest.mark.parametrize(
    "alteration",
    [
        "ALTER TABLE turns DROP CONSTRAINT turns_binding_conversation_fkey",
        "ALTER TABLE turns DROP CONSTRAINT turns_binding_conversation_revision_key",
        "ALTER TABLE memories ALTER COLUMN body TYPE varchar",
        "ALTER TABLE conversations ALTER COLUMN private_mode SET DEFAULT true",
        "ALTER TABLE turns ALTER COLUMN messages DROP NOT NULL",
        "CREATE VIEW unexpected_view AS SELECT 1 AS value",
        "DROP TABLE source_deletions",
        "ALTER TABLE memories ADD COLUMN unexpected text",
    ],
)
def test_changed_schema_contract_is_rejected_without_rewriting_data(
    stores: Stores, alteration: str
) -> None:
    ref = seed(stores)
    with stores.database.transaction(BINDING) as connection:
        connection.execute(alteration)
    with pytest.raises(CoreError) as error:
        PostgresDatabase(stores.config).initialize()
    assert error.value.code == "storage_schema"
    assert stores.history.read(BINDING, ref.conversation_id).messages == MESSAGES


@pytest.mark.parametrize("action", ["private", "delete"])
def test_failed_revocation_rolls_back_history_memory_and_outboxes_together(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    ref = seed(stores)
    memories = remember(stores, (ref,))
    original_revoke = postgres_schema.revoke

    def abort_after_revoke(
        connection: Connection[tuple[Any, ...]],
        binding: str,
        conversation: str,
        epoch: int,
        kind: str,
    ) -> None:
        original_revoke(connection, binding, conversation, epoch, kind)
        raise RuntimeError("Synthetic transaction interruption")

    monkeypatch.setattr(postgres_history, "revoke", abort_after_revoke)
    with pytest.raises(RuntimeError, match="Synthetic transaction interruption"):
        revoke(stores.history, ref, action)
    snapshot = stores.history.read(BINDING, ref.conversation_id)
    assert snapshot.revision == 1 and not snapshot.private_mode
    assert stores.history.source_eligible(BINDING, ref)
    assert stores.memory.search(BINDING, "tea") == memories
    assert stores.memory.valid(BINDING, memories)
    assert stores.memory.events(BINDING) == ()
    assert stores.history.deletions(BINDING) == ()


def test_concurrent_revision_cas_commits_exactly_one_turn(stores: Stores) -> None:
    conversation = stores.history.create(BINDING).conversation_id
    barrier = Barrier(2)
    histories = [PostgresHistory(PostgresDatabase(stores.config)) for _ in range(2)]

    def append(index: int) -> str:
        barrier.wait(timeout=3)
        try:
            histories[index].append(
                BINDING, conversation, f"r{index}", f"fp{index}", 0, MESSAGES, "stop"
            )
            return "committed"
        except CoreError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(append, range(2)))
    assert sorted(results) == ["committed", "revision_conflict"]
    snapshot = stores.history.read(BINDING, conversation)
    assert snapshot.revision == 1 and snapshot.messages == MESSAGES


def test_concurrent_memory_retries_share_one_job_and_result(stores: Stores) -> None:
    ref = seed(stores)
    evidence = stores.memory.sources(BINDING, (ref,))
    memories = [PostgresMemory(PostgresDatabase(stores.config)) for _ in range(2)]
    barrier = Barrier(2)

    def commit(index: int) -> str:
        barrier.wait(timeout=3)
        job = memories[index].begin(BINDING, (evidence[0].source,), "synthetic-v1")
        selected = Candidate("semantic", job.sources, json.dumps([evidence[0].text]))
        memories[index].commit(BINDING, job, (selected,))
        return job.job_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = list(executor.map(commit, range(2)))
    assert jobs[0] == jobs[1]
    assert len(stores.memory.results(BINDING, jobs[0])) == 1


@pytest.mark.parametrize("action", ["private", "delete"])
@pytest.mark.parametrize("first", ["commit", "revoke"])
def test_concurrent_revocation_and_commit_serialize_and_leave_no_visible_memory(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, action: str, first: str
) -> None:
    ref = seed(stores)
    job, selected = prepare(stores, (ref,))
    commit_db, revoke_db = PostgresDatabase(stores.config), PostgresDatabase(stores.config)
    memory, history = PostgresMemory(commit_db), PostgresHistory(revoke_db)
    first_db, second_db = (commit_db, revoke_db) if first == "commit" else (revoke_db, commit_db)
    entered, release, connected = Event(), Event(), Event()
    backend_pids: list[int] = []
    original_transaction = first_db.transaction
    original_connect = second_db._connect

    @contextmanager
    def hold_after_lock(binding: Binding) -> Iterator[Connection[tuple[Any, ...]]]:
        with original_transaction(binding) as connection:
            entered.set()
            assert release.wait(3), "Synthetic transaction gate was not released"
            yield connection

    @contextmanager
    def observe_second_connection() -> Iterator[Connection[tuple[Any, ...]]]:
        with original_connect() as connection:
            row = connection.execute("SELECT pg_backend_pid()").fetchone()
            assert row is not None
            backend_pids.append(row[0])
            connected.set()
            yield connection

    monkeypatch.setattr(first_db, "transaction", hold_after_lock)
    monkeypatch.setattr(second_db, "_connect", observe_second_connection)

    def commit() -> str:
        try:
            memory.commit(BINDING, job, (selected,))
            return "committed"
        except CoreError as error:
            return error.code

    def revoke_source() -> str:
        revoke(history, ref, action)
        return "revoked"

    operations: dict[str, Callable[[], str]] = {"commit": commit, "revoke": revoke_source}
    with ThreadPoolExecutor(max_workers=2) as executor:
        leading = executor.submit(operations[first])
        try:
            assert entered.wait(3)
            following = executor.submit(operations["revoke" if first == "commit" else "commit"])
            assert connected.wait(3)
            # Observe a real second backend waiting for an advisory lock, rather
            # than inferring serialization from Python thread scheduling.
            with raw_connection(stores.config) as observer:
                deadline = time.monotonic() + 2
                while True:
                    waiting = observer.execute(
                        "SELECT 1 FROM pg_locks WHERE pid=%s "
                        "AND locktype='advisory' AND NOT granted",
                        (backend_pids[0],),
                    ).fetchone()
                    if waiting is not None:
                        break
                    assert time.monotonic() < deadline, "Second backend did not wait on scope lock"
                    Event().wait(0.01)
            assert not following.done()
        finally:
            release.set()
        outcomes = {leading.result(timeout=5), following.result(timeout=5)}
    assert outcomes == {"revoked", "committed" if first == "commit" else "memory_source_invalid"}
    assert stores.memory.search(BINDING, "tea") == ()
    assert stores.memory.results(BINDING, job.job_id) == ()
    with stores.database.transaction(BINDING) as connection:
        assert (
            connection.execute("SELECT body FROM memories WHERE body IS NOT NULL").fetchall() == []
        )
    assert len(stores.memory.events(BINDING)) == 1
    if action == "delete":
        assert len(stores.history.deletions(BINDING)) == 1
