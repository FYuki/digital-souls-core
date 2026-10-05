"""Synthetic authoritative projection and derived vectors in an isolated PoC schema.

No production adapter, model call, asynchronous worker, or automatic history import
is installed by this module. A caller supplies fixed vectors and explicitly runs
prepare/complete. Each operation serializes on a schema advisory lock; throughput
under concurrent bindings is deliberately outside this experiment's claims.
"""

import hashlib
import json
import math
import os
import re
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, cast

import psycopg
from psycopg import Connection, sql

from digital_souls_core.application import CoreError
from digital_souls_core.character import AccessScope
from digital_souls_core.history import Binding, SourceReference
from digital_souls_core.memory_contracts import Memory, SourceVersion
from digital_souls_core.memory_ranking import EmbeddingSpace, validate_embedding_space

from .schema import DDL, ELIGIBLE, SEARCH

MAX_DIMENSIONS = 2000
MAX_BIGINT = 2**63 - 1


def _integer(value: object, minimum: int = 0) -> None:
    if type(value) is not int or not minimum <= value <= MAX_BIGINT:
        raise ValueError("Invalid integer metadata")


def _identifier(value: object) -> None:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
        raise ValueError("Invalid synthetic identifier")


def _space(value: EmbeddingSpace) -> EmbeddingSpace:
    validate_embedding_space(value)
    if value.dimensions > MAX_DIMENSIONS:
        raise ValueError("PoC supports at most 2000 dimensions")
    return value


def binding_key(binding: Binding) -> str:
    if type(binding) is not Binding or type(binding.scope) is not AccessScope:
        raise ValueError("Invalid binding")
    scope = binding.scope
    _identifier(scope.subject)
    _identifier(scope.client)
    if type(scope.audience) is not str or scope.audience != "local-private":
        raise ValueError("Unsupported audience")
    _identifier(binding.character_id)
    return json.dumps([scope.subject, scope.client, scope.audience, binding.character_id])


@dataclass(frozen=True)
class PocConfig:
    socket: str
    port: int = 5432
    database: str = "core_pgvector_synthetic"
    user: str = "core_pgvector_synthetic"
    schema: str = "pgvector_poc_default"

    def __post_init__(self) -> None:
        if type(self.socket) is not str or not re.fullmatch(
            r"/tmp/core-pgvector-poc[.-][A-Za-z0-9_-]+/socket", self.socket
        ):
            raise ValueError("A synthetic Unix socket directory is required")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Invalid port")
        if self.database != "core_pgvector_synthetic" or self.user != "core_pgvector_synthetic":
            raise ValueError("Only the dedicated synthetic database identity is permitted")
        if type(self.schema) is not str or not re.fullmatch(
            r"pgvector_poc_[a-z0-9_]{1,49}", self.schema
        ):
            raise ValueError("Only an isolated pgvector_poc_* schema is permitted")


@dataclass(frozen=True)
class SourceSnapshot:
    source_id: str
    revision: int
    epoch: int
    private: bool = False
    excluded: bool = False
    deleted: bool = False
    role: str = "user"
    conversation_id: str | None = None
    message_index: int = 0
    turn_revision: int | None = None

    def __post_init__(self) -> None:
        if self.conversation_id is None:
            object.__setattr__(self, "conversation_id", self.source_id)
        if self.turn_revision is None:
            object.__setattr__(self, "turn_revision", self.revision)
        _source(self)

    @property
    def reference(self) -> SourceReference:
        assert self.conversation_id is not None
        assert self.turn_revision is not None
        return SourceReference(self.conversation_id, self.turn_revision, self.message_index)

    @property
    def eligible(self) -> bool:
        return not (self.private or self.excluded or self.deleted) and self.role == "user"


def _source(value: SourceSnapshot) -> None:
    if type(value) is not SourceSnapshot:
        raise ValueError("Invalid source snapshot")
    _identifier(value.source_id)
    _integer(value.revision, 1)
    _integer(value.epoch)
    _identifier(value.conversation_id)
    _integer(value.message_index)
    if value.message_index > 2**31 - 1:
        raise ValueError("Message position exceeds the SQL integer range")
    _integer(value.turn_revision, 1)
    if any(type(flag) is not bool for flag in (value.private, value.excluded, value.deleted)):
        raise ValueError("Invalid source flags")
    if type(value.role) is not str or value.role not in {"user", "assistant", "tool", "system"}:
        raise ValueError("Invalid source role")


def _sources(values: tuple[SourceSnapshot, ...]) -> None:
    if type(values) is not tuple or not 1 <= len(values) <= 16:
        raise ValueError("One to sixteen explicit sources are required")
    for value in values:
        _source(value)
    if len({value.source_id for value in values}) != len(values):
        raise ValueError("Duplicate source reference")


@dataclass(frozen=True)
class IndexToken:
    binding: Binding
    memory_id: str
    revision: int
    text_hash: str
    generation: int
    sources: tuple[SourceSnapshot, ...]
    space: EmbeddingSpace
    space_generation: int


@dataclass(frozen=True)
class WorkItem(IndexToken):
    text: str = field(repr=False)

    @property
    def token(self) -> IndexToken:
        return IndexToken(
            self.binding,
            self.memory_id,
            self.revision,
            self.text_hash,
            self.generation,
            self.sources,
            self.space,
            self.space_generation,
        )


@dataclass(frozen=True)
class SearchHit:
    memory_id: str
    text: str = field(repr=False)
    score: float
    token: IndexToken


def _check_token(token: IndexToken) -> None:
    binding_key(token.binding)
    _identifier(token.memory_id)
    _integer(token.revision, 1)
    _integer(token.generation, 1)
    _integer(token.space_generation, 1)
    if type(token.text_hash) is not str or not re.fullmatch(r"[0-9a-f]{64}", token.text_hash):
        raise ValueError("Invalid text hash")
    _sources(token.sources)
    _space(token.space)


def _vector(vector: tuple[float, ...], dimensions: int) -> str:
    if type(vector) is not tuple or len(vector) != dimensions:
        raise ValueError("Invalid vector dimensions")
    values = []
    for value in vector:
        if type(value) not in (int, float):
            raise ValueError("Vector elements must be finite numbers")
        try:
            quantized = struct.unpack("!f", struct.pack("!f", value))[0]
        except (OverflowError, struct.error):
            raise ValueError("Vector element is outside float32 range") from None
        if not math.isfinite(quantized):
            raise ValueError("Vector elements must be finite numbers")
        values.append(quantized)
    if not any(values):
        raise ValueError("Zero vector is not searchable")
    # Keep benchmark inputs unchanged; reject unsafe float32 norm accumulation.
    # Fourfold margins also avoid subnormal/overflow boundary rounding in SQL.
    norm_squared = math.fsum(value * value for value in values)
    if not 4 * 1.1754943508222875e-38 <= norm_squared <= 3.4028234663852886e38 / 4:
        raise ValueError("Vector norm is outside the safe float32 cosine range")
    return json.dumps(values, separators=(",", ":"), allow_nan=False)


def _source_values(source: SourceSnapshot) -> tuple[object, ...]:
    return (
        source.source_id,
        source.revision,
        source.epoch,
        source.private,
        source.excluded,
        source.deleted,
        source.role,
        source.conversation_id,
        source.message_index,
        source.turn_revision,
    )


class PgvectorMemoryStore:
    def __init__(self, config: PocConfig, space: EmbeddingSpace) -> None:
        config.__post_init__()
        self.config = config
        self.space = _space(space)
        self._lock = int.from_bytes(
            hashlib.sha256(("pgvector-memory-poc:" + config.schema).encode()).digest()[:8],
            "big",
            signed=True,
        )

    @contextmanager
    def transaction(self) -> Iterator[Connection[tuple[Any, ...]]]:
        """One local synthetic transaction; useful for read-only test observations."""
        self.config.__post_init__()
        if any(key.startswith("PG") and value for key, value in os.environ.items()):
            raise ValueError("Implicit PostgreSQL environment is prohibited")
        with psycopg.connect(
            host=self.config.socket,
            port=self.config.port,
            dbname=self.config.database,
            user=self.config.user,
            password="",
            passfile="/dev/null/no-passfile",
            sslmode="disable",
            gssencmode="disable",
            channel_binding="disable",
            require_auth="none",
            connect_timeout=5,
            options="-c statement_timeout=120000 -c lock_timeout=30000",
        ) as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (self._lock,))
            db.execute(
                sql.SQL("SET LOCAL search_path TO pg_catalog, {}, public").format(
                    sql.Identifier(self.config.schema)
                )
            )
            yield db

    def initialize(self) -> None:
        """Create a fresh disposable schema; never install extensions or reuse a schema."""
        with self.transaction() as db:
            extension = db.execute(
                "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n "
                "ON n.oid=e.extnamespace WHERE e.extname='vector'"
            ).fetchone()
            if extension != ("public",):
                raise ValueError("Fixture must preinstall pgvector in public")
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.config.schema)))
            # pg_catalog first would make an unqualified CREATE choose that schema.
            db.execute(
                sql.SQL("SET LOCAL search_path TO {}, pg_catalog, public").format(
                    sql.Identifier(self.config.schema)
                )
            )
            db.execute(DDL)
            db.execute(
                "INSERT INTO metadata VALUES (true,%s,%s,%s,%s,1)", self._space_values(self.space)
            )

    @staticmethod
    def _space_values(space: EmbeddingSpace) -> tuple[object, ...]:
        return space.model, space.revision, space.dimensions, space.configuration

    def _active(self, db: Connection[tuple[Any, ...]]) -> tuple[EmbeddingSpace, int]:
        row = db.execute(
            "SELECT model,revision,dimensions,configuration,generation "
            "FROM metadata WHERE singleton"
        ).fetchone()
        if row is None:
            raise ValueError("Missing embedding configuration")
        return _space(EmbeddingSpace(*row[:4])), row[4]

    def _expected(self, db: Connection[tuple[Any, ...]]) -> tuple[EmbeddingSpace, int]:
        active = self._active(db)
        if active[0] != self.space:
            raise ValueError("Store embedding configuration is stale")
        return active

    def _refs(
        self, db: Connection[tuple[Any, ...]], key: str, ids: list[str]
    ) -> dict[str, tuple[SourceSnapshot, ...]]:
        grouped: dict[str, list[SourceSnapshot]] = {}
        if ids:
            for row in db.execute(
                "SELECT memory_id,source_id,revision,epoch,private,excluded,deleted,role,"
                "conversation_id,message_index,turn_revision "
                "FROM source_refs WHERE binding=%s AND memory_id=ANY(%s::text[]) ORDER BY position",
                (key, ids),
            ):
                grouped.setdefault(row[0], []).append(SourceSnapshot(*row[1:]))
        return {identifier: tuple(values) for identifier, values in grouped.items()}

    def _current_sources(
        self, db: Connection[tuple[Any, ...]], key: str, sources: tuple[SourceSnapshot, ...]
    ) -> bool:
        if not sources or not all(source.eligible for source in sources):
            return False
        current = {
            row[0]: SourceSnapshot(*row)
            for row in db.execute(
                "SELECT source_id,revision,epoch,private,excluded,deleted,role,"
                "conversation_id,message_index,turn_revision "
                "FROM sources WHERE binding=%s AND source_id=ANY(%s::text[])",
                (key, [source.source_id for source in sources]),
            )
        }
        return all(current.get(source.source_id) == source for source in sources)

    def put_source(self, binding: Binding, source: SourceSnapshot) -> None:
        key = binding_key(binding)
        _source(source)
        with self.transaction() as db:
            old = db.execute(
                "SELECT source_id,revision,epoch,private,excluded,deleted,role,"
                "conversation_id,message_index,turn_revision "
                "FROM sources WHERE binding=%s AND source_id=%s",
                (key, source.source_id),
            ).fetchone()
            if old is not None:
                previous = SourceSnapshot(*old)
                if source.revision < previous.revision or source.epoch < previous.epoch:
                    raise ValueError("Source revision or epoch cannot move backward")
                if previous == source:
                    return
            db.execute(
                "INSERT INTO sources VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (binding,source_id) DO UPDATE SET revision=EXCLUDED.revision,"
                "epoch=EXCLUDED.epoch,private=EXCLUDED.private,excluded=EXCLUDED.excluded,"
                "deleted=EXCLUDED.deleted,role=EXCLUDED.role,"
                "conversation_id=EXCLUDED.conversation_id,message_index=EXCLUDED.message_index,"
                "turn_revision=EXCLUDED.turn_revision",
                (key, *_source_values(source)),
            )
            db.execute(
                "UPDATE memories m SET generation=generation+1,revision=revision+1,body=NULL,"
                "text_hash=%s,"
                "index_status=CASE WHEN index_status='deleted' THEN 'deleted' ELSE 'invalid' END "
                "WHERE binding=%s AND EXISTS (SELECT 1 FROM source_refs r "
                "WHERE r.binding=m.binding AND r.memory_id=m.memory_id AND r.source_id=%s)",
                (hashlib.sha256(b"").hexdigest(), key, source.source_id),
            )
            db.execute(
                "DELETE FROM embeddings e WHERE binding=%s AND EXISTS "
                "(SELECT 1 FROM source_refs r WHERE r.binding=e.binding "
                "AND r.memory_id=e.memory_id AND r.source_id=%s)",
                (key, source.source_id),
            )

    def _put_memory(
        self,
        db: Connection[tuple[Any, ...]],
        binding: Binding,
        memory_id: str,
        text: str,
        sources: tuple[SourceSnapshot, ...],
    ) -> int:
        key = binding_key(binding)
        _identifier(memory_id)
        _sources(sources)
        if type(text) is not str or not text.strip() or len(text.encode()) > 262144:
            raise ValueError("Invalid synthetic memory text")
        if not self._current_sources(db, key, sources):
            raise ValueError("Every source snapshot must be current and eligible")
        previous = db.execute(
            "SELECT index_status FROM memories WHERE binding=%s AND memory_id=%s",
            (key, memory_id),
        ).fetchone()
        if previous is not None and previous[0] in {"invalid", "deleted"}:
            raise ValueError("A revoked memory identifier cannot be reused")
        digest = hashlib.sha256(text.encode()).hexdigest()
        row = db.execute(
            "INSERT INTO memories "
            "(binding,memory_id,revision,text_hash,body,generation,index_status) "
            "VALUES (%s,%s,1,%s,%s,1,'pending') ON CONFLICT (binding,memory_id) DO UPDATE "
            "SET revision=memories.revision+1,text_hash=EXCLUDED.text_hash,body=EXCLUDED.body,"
            "generation=memories.generation+1,index_status='pending' RETURNING revision",
            (key, memory_id, digest, text),
        ).fetchone()
        assert row is not None
        db.execute("DELETE FROM embeddings WHERE binding=%s AND memory_id=%s", (key, memory_id))
        db.execute("DELETE FROM source_refs WHERE binding=%s AND memory_id=%s", (key, memory_id))
        with db.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO source_refs VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    (key, memory_id, position, *_source_values(source))
                    for position, source in enumerate(sources)
                ],
            )
        return int(row[0])

    def put_memory(
        self, binding: Binding, memory_id: str, text: str, sources: tuple[SourceSnapshot, ...]
    ) -> int:
        with self.transaction() as db:
            self._expected(db)
            return self._put_memory(db, binding, memory_id, text, sources)

    def _work(
        self, db: Connection[tuple[Any, ...]], binding: Binding, memory_id: str
    ) -> WorkItem | None:
        key = binding_key(binding)
        _identifier(memory_id)
        space, space_generation = self._expected(db)
        row = db.execute(
            "SELECT revision,text_hash,generation,body FROM memories "
            "WHERE binding=%s AND memory_id=%s AND index_status='pending'",
            (key, memory_id),
        ).fetchone()
        if row is None:
            return None
        sources = self._refs(db, key, [memory_id]).get(memory_id, ())
        if not self._current_sources(db, key, sources):
            return None
        return WorkItem(
            binding, memory_id, row[0], row[1], row[2], sources, space, space_generation, row[3]
        )

    def prepare(self, binding: Binding, memory_id: str) -> WorkItem | None:
        with self.transaction() as db:
            return self._work(db, binding, memory_id)

    def _complete(self, db: Connection[tuple[Any, ...]], work: WorkItem, serialized: str) -> bool:
        space, generation = self._active(db)
        if space != work.space or generation != work.space_generation:
            return False
        if self._work(db, work.binding, work.memory_id) != work:
            return False
        key = binding_key(work.binding)
        db.execute(
            "INSERT INTO embeddings (binding,memory_id,memory_revision,text_hash,generation,"
            "model,revision,dimensions,configuration,space_generation,embedding) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::public.vector)",
            (
                key,
                work.memory_id,
                work.revision,
                work.text_hash,
                work.generation,
                *self._space_values(space),
                generation,
                serialized,
            ),
        )
        db.execute(
            "UPDATE memories SET index_status='ready' WHERE binding=%s AND memory_id=%s",
            (key, work.memory_id),
        )
        return True

    def complete(self, work: WorkItem, vector: tuple[float, ...]) -> bool:
        if type(work) is not WorkItem:
            return False
        try:
            _check_token(work)
            if (
                type(work.text) is not str
                or hashlib.sha256(work.text.encode()).hexdigest() != work.text_hash
            ):
                return False
        except (ValueError, TypeError, AttributeError, CoreError):
            return False
        with self.transaction() as db:
            if self._active(db) != (work.space, work.space_generation):
                return False
            if self._work(db, work.binding, work.memory_id) != work:
                return False
            return self._complete(db, work, _vector(vector, work.space.dimensions))

    def _delete(self, db: Connection[tuple[Any, ...]], key: str, memory_id: str) -> None:
        db.execute(
            "UPDATE memories SET revision=revision+1,generation=generation+1,body=NULL,"
            "text_hash=%s,index_status='deleted' WHERE binding=%s AND memory_id=%s",
            (hashlib.sha256(b"").hexdigest(), key, memory_id),
        )
        db.execute("DELETE FROM embeddings WHERE binding=%s AND memory_id=%s", (key, memory_id))
        db.execute("DELETE FROM source_refs WHERE binding=%s AND memory_id=%s", (key, memory_id))

    def delete_memory(self, binding: Binding, memory_id: str) -> None:
        key = binding_key(binding)
        _identifier(memory_id)
        with self.transaction() as db:
            self._delete(db, key, memory_id)

    def move_memory(self, old_binding: Binding, new_binding: Binding, memory_id: str) -> None:
        old, new = binding_key(old_binding), binding_key(new_binding)
        _identifier(memory_id)
        if old == new:
            raise ValueError("Scope transfer requires a different binding")
        with self.transaction() as db:
            self._expected(db)
            row = db.execute(
                "SELECT body FROM memories WHERE binding=%s AND memory_id=%s "
                "AND index_status IN ('ready','pending')",
                (old, memory_id),
            ).fetchone()
            if (
                row is None
                or db.execute(
                    "SELECT 1 FROM memories WHERE binding=%s AND memory_id=%s", (new, memory_id)
                ).fetchone()
            ):
                raise ValueError("Scope transfer requires an eligible source and absent target")
            sources = self._refs(db, old, [memory_id]).get(memory_id, ())
            if not self._current_sources(db, old, sources):
                raise ValueError("Source binding is no longer eligible")
            # New scope must independently contain the same explicit authoritative snapshots.
            self._put_memory(db, new_binding, memory_id, row[0], sources)
            self._delete(db, old, memory_id)

    def set_space(self, space: EmbeddingSpace) -> None:
        _space(space)
        with self.transaction() as db:
            if self._active(db)[0] != space:
                db.execute(
                    "UPDATE metadata SET model=%s,revision=%s,dimensions=%s,configuration=%s,"
                    "generation=generation+1",
                    self._space_values(space),
                )
                db.execute("DELETE FROM embeddings")
                db.execute(
                    "UPDATE memories SET generation=generation+1,index_status="
                    "CASE WHEN index_status IN ('ready','pending') THEN 'pending' "
                    "ELSE index_status END"
                )
        self.space = space

    def _eligible_parameters(
        self, db: Connection[tuple[Any, ...]], binding: Binding
    ) -> tuple[object, ...]:
        space, generation = self._expected(db)
        return binding_key(binding), *self._space_values(space), generation

    def search(
        self, binding: Binding, query_vector: tuple[float, ...], limit: int = 8
    ) -> tuple[SearchHit, ...]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Search limit must be between 1 and 1000")
        serialized = _vector(query_vector, self.space.dimensions)
        with self.transaction() as db:
            parameters = self._eligible_parameters(db, binding)
            rows = db.execute(SEARCH, (*parameters, serialized, limit)).fetchall()
            refs = self._refs(db, binding_key(binding), [row[0] for row in rows])
            return tuple(
                SearchHit(
                    row[0],
                    row[1],
                    float(row[5]),
                    IndexToken(
                        binding,
                        row[0],
                        row[2],
                        row[3],
                        row[4],
                        refs[row[0]],
                        self.space,
                        cast(int, parameters[-1]),
                    ),
                )
                for row in rows
            )

    def valid(self, token: IndexToken) -> bool:
        if type(token) is not IndexToken:
            return False
        try:
            _check_token(token)
        except (ValueError, TypeError, AttributeError, CoreError):
            return False
        with self.transaction() as db:
            if self._active(db) != (token.space, token.space_generation):
                return False
            row = db.execute(
                "SELECT m.revision,m.text_hash,m.generation,m.index_status,"
                "e.memory_revision,e.text_hash,e.generation,e.model,e.revision,"
                "e.dimensions,e.configuration,e.space_generation FROM memories m "
                "JOIN embeddings e ON e.binding=m.binding AND e.memory_id=m.memory_id "
                "WHERE m.binding=%s AND m.memory_id=%s",
                (binding_key(token.binding), token.memory_id),
            ).fetchone()
            if row != (
                token.revision,
                token.text_hash,
                token.generation,
                "ready",
                token.revision,
                token.text_hash,
                token.generation,
                *self._space_values(token.space),
                token.space_generation,
            ):
                return False
            refs = self._refs(db, binding_key(token.binding), [token.memory_id]).get(
                token.memory_id, ()
            )
            return refs == token.sources and self._current_sources(
                db, binding_key(token.binding), refs
            )

    def bulk_load(
        self,
        binding: Binding,
        entries: tuple[tuple[str, str, tuple[SourceSnapshot, ...], tuple[float, ...]], ...],
    ) -> None:
        """Atomic initial synthetic load; reuses the same mutation/CAS validation path."""
        key = binding_key(binding)
        if type(entries) is not tuple or len({entry[0] for entry in entries}) != len(entries):
            raise ValueError("Duplicate bulk memory identifier")
        with self.transaction() as db:
            self._expected(db)
            if db.execute(
                "SELECT 1 FROM memories WHERE binding=%s AND memory_id=ANY(%s::text[])",
                (key, [entry[0] for entry in entries]),
            ).fetchone():
                raise ValueError("Bulk load only accepts absent memories")
            for memory_id, text, sources, vector in entries:
                self._put_memory(db, binding, memory_id, text, sources)
                work = self._work(db, binding, memory_id)
                assert work is not None
                if not self._complete(db, work, _vector(vector, self.space.dimensions)):
                    raise ValueError("Bulk completion unexpectedly became stale")

    def export_eligible(self, binding: Binding) -> tuple[tuple[Memory, tuple[float, ...]], ...]:
        """Benchmark-only full transfer, preserving the exact SQL search tie order."""
        with self.transaction() as db:
            parameters = self._eligible_parameters(db, binding)
            rows = db.execute(
                "WITH eligible AS MATERIALIZED (" + ELIGIBLE + ") "
                "SELECT memory_id,body,embedding::text FROM eligible ORDER BY seq DESC",
                parameters,
            ).fetchall()
            refs = self._refs(db, binding_key(binding), [row[0] for row in rows])
            return tuple(
                (
                    Memory(
                        row[0],
                        "semantic",
                        row[1],
                        tuple(
                            SourceVersion(
                                source.reference,
                                source.epoch,
                            )
                            for source in refs[row[0]]
                        ),
                    ),
                    tuple(float(value) for value in json.loads(row[2])),
                )
                for row in rows
            )

    def explain_search(
        self, binding: Binding, query_vector: tuple[float, ...], limit: int = 8
    ) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid search limit")
        serialized = _vector(query_vector, self.space.dimensions)
        with self.transaction() as db:
            parameters = self._eligible_parameters(db, binding)
            row = db.execute(
                "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + SEARCH,
                (*parameters, serialized, limit),
            ).fetchone()
            assert row is not None
            result: dict[str, Any] = row[0][0]
            return result

    def metadata(self) -> dict[str, object]:
        with self.transaction() as db:
            space, generation = self._active(db)
            version = db.execute(
                "SELECT current_setting('server_version'),extversion,"
                "pg_postmaster_start_time()::text FROM pg_extension "
                "WHERE extname='vector'"
            ).fetchone()
            assert version is not None
            counts = db.execute(
                "SELECT (SELECT count(*) FROM memories),(SELECT count(*) FROM embeddings)"
            ).fetchone()
            assert counts is not None
            size = db.execute(
                "SELECT coalesce(sum(pg_total_relation_size(c.oid)),0)::bigint "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=%s AND c.relkind='r'",
                (self.config.schema,),
            ).fetchone()
            assert size is not None
            return {
                "postgres_version": version[0],
                "pgvector_version": version[1],
                "postmaster_start_time": version[2],
                "schema": self.config.schema,
                "dimensions": space.dimensions,
                "space_generation": generation,
                "memory_rows": counts[0],
                "embedding_rows": counts[1],
                "relation_bytes": size[0],
            }
