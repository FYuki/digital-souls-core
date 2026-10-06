"""PostgreSQL memory adapter sharing history's atomic revocation boundary."""

import hashlib
import json
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from psycopg import Connection

from .application import CoreError
from .history import Binding, SourceReference, as_utc
from .memory_contracts import Candidate, Evidence, Memory, MemoryJob, SourceVersion
from .postgres_db import key as _key
from .postgres_history import PostgresHistory
from .privacy_scan import scan


def _encode(sources: tuple[SourceVersion, ...]) -> str:
    return json.dumps([asdict(s) for s in sources], sort_keys=True)


def _decode(raw: str) -> tuple[SourceVersion, ...]:
    return tuple(
        SourceVersion(SourceReference(**s["reference"]), s["epoch"]) for s in json.loads(raw)
    )


def _job_key(binding: Binding, sources: tuple[SourceVersion, ...], versions: str) -> str:
    return hashlib.sha256(
        json.dumps([_key(binding), _encode(sources), versions]).encode()
    ).hexdigest()


def _evidence(ref: SourceReference, row: tuple[Any, ...] | None) -> Evidence:
    if row is None or row[0] or row[2] or type(ref.message_index) is not int:
        raise CoreError(409, "memory_source_invalid", "Memory source is unavailable")
    messages = json.loads(row[4])
    if not 0 <= ref.message_index < len(messages) or ref.message_index in json.loads(row[3]):
        raise CoreError(409, "memory_source_invalid", "Memory source is unavailable")
    message = messages[ref.message_index]
    # Do not turn assistant proposals or tool output into user facts.
    text = message.get("content")
    if message["role"] != "user" or not isinstance(text, str) or not 0 < len(text) <= 2048:
        raise CoreError(409, "memory_source_invalid", "Memory source is unavailable")
    return Evidence(
        SourceVersion(ref, row[1]), text, as_utc(row[5]) if row[5] is not None else None
    )


class PostgresMemory(PostgresHistory):
    """Trusted storage port; use MemoryService for authorization and model boundaries."""

    def _source(
        self, db: Connection[tuple[Any, ...]], binding: Binding, ref: SourceReference
    ) -> Evidence:
        row = db.execute(
            "SELECT c.private_mode,c.memory_epoch,t.private_mode,t.memory_excluded,"
            "t.messages,t.stated_at "
            "FROM conversations c JOIN turns t ON c.binding=t.binding AND c.id=t.conversation "
            "WHERE c.binding=%s AND c.id=%s AND t.revision=%s",
            (_key(binding), ref.conversation_id, ref.turn_revision),
        ).fetchone()
        return _evidence(ref, row)

    def sources(self, binding: Binding, refs: tuple[SourceReference, ...]) -> tuple[Evidence, ...]:
        if not 0 < len(refs) <= 16 or len(set(refs)) != len(refs):
            raise CoreError(400, "memory_sources_invalid", "Invalid memory source set")
        with self.database.transaction(binding) as db:
            return tuple(self._source(db, binding, ref) for ref in refs)

    def _source_rows(
        self, db: Connection[tuple[Any, ...]], binding: Binding, refs: tuple[SourceReference, ...]
    ) -> dict[tuple[str, int], tuple[Any, ...]]:
        # Pair the arrays before joining: separate ANY predicates would also
        # fetch unrelated conversation/revision combinations.
        pairs = tuple(dict.fromkeys((ref.conversation_id, ref.turn_revision) for ref in refs))
        if not pairs:
            return {}
        rows = db.execute(
            "SELECT c.id,t.revision,c.private_mode,c.memory_epoch,"
            "t.private_mode,t.memory_excluded,t.messages,t.stated_at "
            "FROM unnest(%s::text[], %s::bigint[]) AS requested(conversation,revision) "
            "JOIN conversations c ON c.binding=%s AND c.id=requested.conversation "
            "JOIN turns t ON t.binding=c.binding AND t.conversation=c.id "
            "AND t.revision=requested.revision",
            (
                [conversation for conversation, _ in pairs],
                [revision for _, revision in pairs],
                _key(binding),
            ),
        ).fetchall()
        return {(row[0], row[1]): row[2:] for row in rows}

    def _current_rows(
        self,
        sources: tuple[SourceVersion, ...],
        rows: dict[tuple[str, int], tuple[Any, ...]],
    ) -> bool:
        if not sources:
            return False
        try:
            return all(
                _evidence(
                    source.reference,
                    rows.get((source.reference.conversation_id, source.reference.turn_revision)),
                ).source
                == source
                for source in sources
            )
        except CoreError:
            return False

    def _current(
        self, db: Connection[tuple[Any, ...]], binding: Binding, sources: tuple[SourceVersion, ...]
    ) -> bool:
        rows = self._source_rows(db, binding, tuple(source.reference for source in sources))
        return self._current_rows(sources, rows)

    def current(self, binding: Binding, sources: tuple[SourceVersion, ...]) -> bool:
        with self.database.transaction(binding) as db:
            return self._current(db, binding, sources)

    def begin(
        self, binding: Binding, sources: tuple[SourceVersion, ...], versions: str
    ) -> MemoryJob:
        # Canonical order also makes reordered retries idempotent.
        ordered = tuple(
            sorted(
                sources,
                key=lambda s: (
                    s.reference.conversation_id,
                    s.reference.turn_revision,
                    s.reference.message_index,
                    s.epoch,
                ),
            )
        )
        key = _job_key(binding, ordered, versions)
        with self.database.transaction(binding) as db:
            if not self._current(db, binding, ordered):
                raise CoreError(409, "memory_source_invalid", "Memory source changed")
            # Failed attempts remain terminal. A deterministic successor makes
            # explicit concurrent retries idempotent without an ABA state reset.
            for _ in range(128):
                db.execute(
                    "INSERT INTO memory_jobs (id,binding,sources,versions,state) "
                    "VALUES (%s,%s,%s,%s,'pending') ON CONFLICT DO NOTHING",
                    (key, _key(binding), _encode(ordered), versions),
                )
                row = db.execute(
                    "SELECT state FROM memory_jobs WHERE binding=%s AND id=%s", (_key(binding), key)
                ).fetchone()
                if row is None:
                    raise CoreError(409, "memory_job_invalid", "Memory job is unavailable")
                state = row[0]
                if state != "failed":
                    return MemoryJob(key, ordered, versions, state)
                key = hashlib.sha256(json.dumps([key, "explicit-retry"]).encode()).hexdigest()
            raise CoreError(409, "memory_retry_limit", "Explicit memory retry limit reached")

    def commit(self, binding: Binding, job: MemoryJob, candidates: tuple[Candidate, ...]) -> None:
        with self.database.transaction(binding) as db:
            row = db.execute(
                "SELECT sources,versions,state FROM memory_jobs WHERE binding=%s AND id=%s",
                (_key(binding), job.job_id),
            ).fetchone()
            if row is None or row[:2] != (_encode(job.sources), job.versions):
                raise CoreError(409, "memory_job_invalid", "Memory job changed")
            if row[2] == "done":
                return
            if row[2] != "pending" or not self._current(db, binding, job.sources):
                raise CoreError(409, "memory_source_invalid", "Memory source changed")
            for candidate in candidates:
                finding = scan(candidate.text)
                if (
                    finding.secret
                    or finding.failed
                    or not candidate.sources
                    or not set(candidate.sources) <= set(job.sources)
                    or candidate.kind not in {"episode", "semantic"}
                ):
                    raise CoreError(403, "memory_denied", "Invalid memory candidate")
                expected = json.dumps(
                    [self._source(db, binding, s.reference).text for s in candidate.sources],
                    ensure_ascii=False,
                )
                if candidate.text != expected:
                    raise CoreError(403, "memory_denied", "Memory evidence mismatch")
                identifier = str(uuid4())
                db.execute(
                    "INSERT INTO memories (id,binding,job,kind,body,state,revoked_by) "
                    "VALUES (%s,%s,%s,%s,%s,'active',NULL)",
                    (identifier, _key(binding), job.job_id, candidate.kind, candidate.text),
                )
                with db.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO memory_sources "
                        "(binding,memory,conversation,revision,position,epoch) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        [
                            (
                                _key(binding),
                                identifier,
                                s.reference.conversation_id,
                                s.reference.turn_revision,
                                s.reference.message_index,
                                s.epoch,
                            )
                            for s in candidate.sources
                        ],
                    )
            db.execute(
                "UPDATE memory_jobs SET state='done' WHERE binding=%s AND id=%s",
                (_key(binding), job.job_id),
            )

    def _memories(
        self, db: Connection[tuple[Any, ...]], binding: Binding, job_id: str | None = None
    ) -> tuple[Memory, ...]:
        rows = db.execute(
            "SELECT id,kind,body FROM memories WHERE binding=%s AND state='active' "
            "AND (%s::text IS NULL OR job=%s) ORDER BY seq DESC LIMIT 1001",
            (_key(binding), job_id, job_id),
        ).fetchall()
        if len(rows) > 1000:
            raise CoreError(413, "memory_limit", "Memory search scope exceeds limit")
        if not rows:
            return ()
        grouped: dict[str, list[SourceVersion]] = {}
        for identifier, conversation, revision, position, epoch in db.execute(
            "SELECT memory,conversation,revision,position,epoch FROM memory_sources "
            "WHERE binding=%s AND memory=ANY(%s::text[]) ORDER BY seq",
            (_key(binding), [row[0] for row in rows]),
        ):
            grouped.setdefault(identifier, []).append(
                SourceVersion(SourceReference(conversation, revision, position), epoch)
            )
        source_rows = self._source_rows(
            db,
            binding,
            tuple(source.reference for sources in grouped.values() for source in sources),
        )
        # Latest user source turn in append order; stands in for PoC mention time.
        pairs = tuple(
            dict.fromkeys(
                (s.reference.conversation_id, s.reference.turn_revision)
                for sources in grouped.values()
                for s in sources
            )
        )
        turn_order = {
            (conversation, revision): seq
            for conversation, revision, seq in db.execute(
                "SELECT t.conversation,t.revision,t.seq "
                "FROM unnest(%s::text[], %s::bigint[]) AS requested(conversation,revision) "
                "JOIN turns t ON t.binding=%s AND t.conversation=requested.conversation "
                "AND t.revision=requested.revision",
                ([c for c, _ in pairs], [r for _, r in pairs], _key(binding)),
            )
        }
        memories = []
        for identifier, kind, text in rows:
            sources = tuple(grouped.get(identifier, ()))
            if self._current_rows(sources, source_rows):
                mentioned = max(
                    turn_order[(s.reference.conversation_id, s.reference.turn_revision)]
                    for s in sources
                )
                memories.append(Memory(identifier, kind, text, sources, mentioned))
        return tuple(memories)

    def results(self, binding: Binding, job_id: str) -> tuple[Memory, ...]:
        with self.database.transaction(binding) as db:
            return self._memories(db, binding, job_id)

    def candidates(self, binding: Binding) -> tuple[Memory, ...]:
        """Return only currently eligible memories, in deterministic newest-first order."""
        with self.database.transaction(binding) as db:
            return self._memories(db, binding)

    def search(self, binding: Binding, query: str, limit: int = 8) -> tuple[Memory, ...]:
        if not 0 < len(query) <= 256 or not 1 <= limit <= 16:
            raise CoreError(400, "memory_query_invalid", "Invalid memory query")
        # Literal casefold substring, no query DSL, embeddings, persisted index or cache.
        with self.database.transaction(binding) as db:
            return tuple(
                m for m in self._memories(db, binding) if query.casefold() in m.text.casefold()
            )[:limit]

    def valid(self, binding: Binding, memories: tuple[Memory, ...]) -> bool:
        with self.database.transaction(binding) as db:
            if not memories:
                return True
            current = {
                identifier: (text, state)
                for identifier, text, state in db.execute(
                    "SELECT id,body,state FROM memories WHERE binding=%s AND id=ANY(%s::text[])",
                    (_key(binding), [memory.memory_id for memory in memories]),
                )
            }
            if any(current.get(memory.memory_id) != (memory.text, "active") for memory in memories):
                return False
            rows = self._source_rows(
                db,
                binding,
                tuple(source.reference for memory in memories for source in memory.sources),
            )
            return all(self._current_rows(memory.sources, rows) for memory in memories)

    def events(self, binding: Binding) -> tuple[str, ...]:
        with self.database.transaction(binding) as db:
            return tuple(
                row[0]
                for row in db.execute(
                    "SELECT id FROM memory_events WHERE binding=%s AND "
                    "processed=false ORDER BY seq LIMIT 128",
                    (_key(binding),),
                )
            )

    def consume(self, binding: Binding, event_id: str) -> None:
        with self.database.transaction(binding) as db:
            event = db.execute(
                "SELECT processed FROM memory_events WHERE binding=%s AND id=%s",
                (_key(binding), event_id),
            ).fetchone()
            if event is None or event[0]:
                return
            for mid, versions in db.execute(
                "SELECT m.id,j.versions FROM memories m JOIN memory_jobs j "
                "ON m.binding=j.binding AND m.job=j.id WHERE m.binding=%s AND m.revoked_by=%s",
                (_key(binding), event_id),
            ).fetchall():
                old = tuple(
                    SourceVersion(SourceReference(c, r, p), e)
                    for c, r, p, e in db.execute(
                        "SELECT conversation,revision,position,epoch FROM memory_sources "
                        "WHERE binding=%s AND memory=%s ORDER BY seq",
                        (_key(binding), mid),
                    )
                )
                remaining = tuple(s for s in old if self._current(db, binding, (s,)))
                if remaining:
                    job_id = hashlib.sha256(
                        json.dumps([event_id, mid, _encode(remaining), versions]).encode()
                    ).hexdigest()
                    db.execute(
                        "INSERT INTO memory_jobs (id,binding,sources,versions,state) "
                        "VALUES (%s,%s,%s,%s,'pending') ON CONFLICT DO NOTHING",
                        (job_id, _key(binding), _encode(remaining), versions),
                    )
            db.execute(
                "UPDATE memory_events SET processed=true WHERE binding=%s AND id=%s",
                (_key(binding), event_id),
            )

    def pending(self, binding: Binding, limit: int = 16) -> tuple[MemoryJob, ...]:
        if not 1 <= limit <= 128:
            raise ValueError("invalid job limit")
        with self.database.transaction(binding) as db:
            return tuple(
                MemoryJob(i, _decode(s), v, state)
                for i, s, v, state in db.execute(
                    "SELECT id,sources,versions,state FROM memory_jobs "
                    "WHERE binding=%s AND state='pending' "
                    "ORDER BY seq LIMIT %s",
                    (_key(binding), limit),
                )
            )

    def fail(self, binding: Binding, job: MemoryJob) -> None:
        """Retire matching pending work; never downgrade a concurrent commit."""
        with self.database.transaction(binding) as db:
            db.execute(
                "UPDATE memory_jobs SET state='failed' WHERE binding=%s AND id=%s "
                "AND sources=%s AND versions=%s AND state='pending'",
                (_key(binding), job.job_id, _encode(job.sources), job.versions),
            )

    def rebase(self, binding: Binding, job: MemoryJob) -> MemoryJob | None:
        """Retire stale work and keep only its still-valid original epoch references."""
        with self.database.transaction(binding) as db:
            row = db.execute(
                "SELECT sources,versions,state FROM memory_jobs WHERE binding=%s AND id=%s",
                (_key(binding), job.job_id),
            ).fetchone()
            if row is None or row != (_encode(job.sources), job.versions, "pending"):
                return None
            remaining = tuple(s for s in job.sources if self._current(db, binding, (s,)))
            if remaining == job.sources:
                return job
            db.execute(
                "UPDATE memory_jobs SET state='obsolete' WHERE binding=%s AND id=%s",
                (_key(binding), job.job_id),
            )
            if not remaining:
                return None
            key = hashlib.sha256(json.dumps([job.job_id, _encode(remaining)]).encode()).hexdigest()
            db.execute(
                "INSERT INTO memory_jobs (id,binding,sources,versions,state) "
                "VALUES (%s,%s,%s,%s,'pending') ON CONFLICT DO NOTHING",
                (key, _key(binding), _encode(remaining), job.versions),
            )
            row = db.execute(
                "SELECT state FROM memory_jobs WHERE binding=%s AND id=%s", (_key(binding), key)
            ).fetchone()
            if row is None:
                raise CoreError(409, "memory_job_invalid", "Memory job is unavailable")
            state = row[0]
            return MemoryJob(key, remaining, job.versions, state)
