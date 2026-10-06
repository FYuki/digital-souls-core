"""SQLite memory adapter sharing history's private file and atomic revocation boundary."""

import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

from .application import CoreError
from .history import Binding, SourceReference, as_utc
from .memory_contracts import Candidate, Evidence, Memory, MemoryJob, SourceVersion
from .privacy_scan import scan
from .sqlite_history import SQLiteHistory, _key


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


class SQLiteMemory(SQLiteHistory):
    """Trusted storage port; use MemoryService for authorization and model boundaries."""

    def _source(self, db: sqlite3.Connection, binding: Binding, ref: SourceReference) -> Evidence:
        row = db.execute(
            "SELECT c.private_mode,c.memory_epoch,t.private_mode,t.memory_excluded,"
            "t.messages,t.stated_at "
            "FROM conversations c JOIN turns t ON c.binding=t.binding AND c.id=t.conversation "
            "WHERE c.binding=? AND c.id=? AND t.revision=?",
            (_key(binding), ref.conversation_id, ref.turn_revision),
        ).fetchone()
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
            SourceVersion(ref, row[1]),
            text,
            as_utc(datetime.fromisoformat(row[5])) if row[5] is not None else None,
        )

    def sources(self, binding: Binding, refs: tuple[SourceReference, ...]) -> tuple[Evidence, ...]:
        if not 0 < len(refs) <= 16 or len(set(refs)) != len(refs):
            raise CoreError(400, "memory_sources_invalid", "Invalid memory source set")
        with self._connection() as db:
            db.execute("BEGIN")
            return tuple(self._source(db, binding, ref) for ref in refs)

    def _current(
        self, db: sqlite3.Connection, binding: Binding, sources: tuple[SourceVersion, ...]
    ) -> bool:
        if not sources:
            return False
        try:
            return all(self._source(db, binding, s.reference).source == s for s in sources)
        except CoreError:
            return False

    def current(self, binding: Binding, sources: tuple[SourceVersion, ...]) -> bool:
        with self._connection() as db:
            db.execute("BEGIN")
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
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self._current(db, binding, ordered):
                raise CoreError(409, "memory_source_invalid", "Memory source changed")
            # Failed attempts remain terminal. A deterministic successor makes
            # explicit concurrent retries idempotent without an ABA state reset.
            for _ in range(128):
                db.execute(
                    "INSERT OR IGNORE INTO memory_jobs VALUES (?,?,?,?,'pending')",
                    (key, _key(binding), _encode(ordered), versions),
                )
                state = db.execute(
                    "SELECT state FROM memory_jobs WHERE binding=? AND id=?", (_key(binding), key)
                ).fetchone()[0]
                if state != "failed":
                    return MemoryJob(key, ordered, versions, state)
                key = hashlib.sha256(json.dumps([key, "explicit-retry"]).encode()).hexdigest()
            raise CoreError(409, "memory_retry_limit", "Explicit memory retry limit reached")

    def commit(self, binding: Binding, job: MemoryJob, candidates: tuple[Candidate, ...]) -> None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT sources,versions,state FROM memory_jobs WHERE binding=? AND id=?",
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
                    "INSERT INTO memories VALUES (?,?,?,?,?,'active',NULL)",
                    (identifier, _key(binding), job.job_id, candidate.kind, candidate.text),
                )
                db.executemany(
                    "INSERT INTO memory_sources VALUES (?,?,?,?,?,?)",
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
                "UPDATE memory_jobs SET state='done' WHERE binding=? AND id=?",
                (_key(binding), job.job_id),
            )

    def _memories(
        self, db: sqlite3.Connection, binding: Binding, job_id: str | None = None
    ) -> tuple[Memory, ...]:
        rows = db.execute(
            "SELECT id,kind,body FROM memories WHERE binding=? AND state='active' "
            "AND (? IS NULL OR job=?) ORDER BY rowid DESC LIMIT 1001",
            (_key(binding), job_id, job_id),
        ).fetchall()
        if len(rows) > 1000:
            raise CoreError(413, "memory_limit", "Memory search scope exceeds limit")
        memories = []
        for identifier, kind, text in rows:
            sources = tuple(
                SourceVersion(SourceReference(c, r, p), e)
                for c, r, p, e in db.execute(
                    "SELECT conversation,revision,position,epoch FROM memory_sources "
                    "WHERE binding=? AND memory=? ORDER BY rowid",
                    (_key(binding), identifier),
                )
            )
            if self._current(db, binding, sources):
                memories.append(
                    Memory(identifier, kind, text, sources, self._mentioned(db, binding, sources))
                )
        return tuple(memories)

    def _mentioned(
        self, db: sqlite3.Connection, binding: Binding, sources: tuple[SourceVersion, ...]
    ) -> int:
        """Latest user source turn in append order; stands in for PoC mention time."""
        return max(
            int(
                db.execute(
                    "SELECT rowid FROM turns WHERE binding=? AND conversation=? AND revision=?",
                    (_key(binding), s.reference.conversation_id, s.reference.turn_revision),
                ).fetchone()[0]
            )
            for s in sources
        )

    def results(self, binding: Binding, job_id: str) -> tuple[Memory, ...]:
        with self._connection() as db:
            db.execute("BEGIN")
            return self._memories(db, binding, job_id)

    def search(self, binding: Binding, query: str, limit: int = 8) -> tuple[Memory, ...]:
        if not 0 < len(query) <= 256 or not 1 <= limit <= 16:
            raise CoreError(400, "memory_query_invalid", "Invalid memory query")
        return tuple(m for m in self.candidates(binding) if query.casefold() in m.text.casefold())[
            :limit
        ]

    def candidates(self, binding: Binding) -> tuple[Memory, ...]:
        """Bounded current evidence in one exact scope, newest first; no history import."""
        with self._connection() as db:
            db.execute("BEGIN")
            return self._memories(db, binding)

    def valid(self, binding: Binding, memories: tuple[Memory, ...]) -> bool:
        with self._connection() as db:
            db.execute("BEGIN")
            for memory in memories:
                row = db.execute(
                    "SELECT body,state FROM memories WHERE binding=? AND id=?",
                    (_key(binding), memory.memory_id),
                ).fetchone()
                if row != (memory.text, "active") or not self._current(db, binding, memory.sources):
                    return False
            return True

    def events(self, binding: Binding) -> tuple[str, ...]:
        with self._connection() as db:
            return tuple(
                row[0]
                for row in db.execute(
                    "SELECT id FROM memory_events WHERE binding=? AND "
                    "processed=0 ORDER BY rowid LIMIT 128",
                    (_key(binding),),
                )
            )

    def consume(self, binding: Binding, event_id: str) -> None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            event = db.execute(
                "SELECT processed FROM memory_events WHERE binding=? AND id=?",
                (_key(binding), event_id),
            ).fetchone()
            if event is None or event[0]:
                return
            for mid, versions in db.execute(
                "SELECT m.id,j.versions FROM memories m JOIN memory_jobs j "
                "ON m.binding=j.binding AND m.job=j.id WHERE m.binding=? AND m.revoked_by=?",
                (_key(binding), event_id),
            ).fetchall():
                old = tuple(
                    SourceVersion(SourceReference(c, r, p), e)
                    for c, r, p, e in db.execute(
                        "SELECT conversation,revision,position,epoch FROM memory_sources "
                        "WHERE binding=? AND memory=? ORDER BY rowid",
                        (_key(binding), mid),
                    )
                )
                remaining = tuple(s for s in old if self._current(db, binding, (s,)))
                if remaining:
                    job_id = hashlib.sha256(
                        json.dumps([event_id, mid, _encode(remaining), versions]).encode()
                    ).hexdigest()
                    db.execute(
                        "INSERT OR IGNORE INTO memory_jobs VALUES (?,?,?,?,'pending')",
                        (job_id, _key(binding), _encode(remaining), versions),
                    )
            db.execute(
                "UPDATE memory_events SET processed=1 WHERE binding=? AND id=?",
                (_key(binding), event_id),
            )

    def pending(self, binding: Binding, limit: int = 16) -> tuple[MemoryJob, ...]:
        if not 1 <= limit <= 128:
            raise ValueError("invalid job limit")
        with self._connection() as db:
            return tuple(
                MemoryJob(i, _decode(s), v, state)
                for i, s, v, state in db.execute(
                    "SELECT id,sources,versions,state FROM memory_jobs "
                    "WHERE binding=? AND state='pending' "
                    "ORDER BY rowid LIMIT ?",
                    (_key(binding), limit),
                )
            )

    def fail(self, binding: Binding, job: MemoryJob) -> None:
        """Retire matching pending work; never downgrade a concurrent commit."""
        with self._connection() as db:
            db.execute(
                "UPDATE memory_jobs SET state='failed' WHERE binding=? AND id=? "
                "AND sources=? AND versions=? AND state='pending'",
                (_key(binding), job.job_id, _encode(job.sources), job.versions),
            )

    def rebase(self, binding: Binding, job: MemoryJob) -> MemoryJob | None:
        """Retire stale work and keep only its still-valid original epoch references."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT sources,versions,state FROM memory_jobs WHERE binding=? AND id=?",
                (_key(binding), job.job_id),
            ).fetchone()
            if row is None or row != (_encode(job.sources), job.versions, "pending"):
                return None
            remaining = tuple(s for s in job.sources if self._current(db, binding, (s,)))
            if remaining == job.sources:
                return job
            db.execute(
                "UPDATE memory_jobs SET state='obsolete' WHERE binding=? AND id=?",
                (_key(binding), job.job_id),
            )
            if not remaining:
                return None
            key = hashlib.sha256(json.dumps([job.job_id, _encode(remaining)]).encode()).hexdigest()
            db.execute(
                "INSERT OR IGNORE INTO memory_jobs VALUES (?,?,?,?,'pending')",
                (key, _key(binding), _encode(remaining), job.versions),
            )
            state = db.execute(
                "SELECT state FROM memory_jobs WHERE binding=? AND id=?", (_key(binding), key)
            ).fetchone()[0]
            return MemoryJob(key, remaining, job.versions, state)
