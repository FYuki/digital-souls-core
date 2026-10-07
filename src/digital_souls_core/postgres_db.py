"""Explicit local PostgreSQL configuration and bounded storage transactions."""

import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Annotated, Any

import psycopg
from psycopg import Connection, sql
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .application import CoreError
from .history import Binding
from .postgres_schema import CONSTRAINTS, TABLE_COLUMNS, TURN_DELETION_DDL, create


class PostgresConfig(BaseModel):
    """Trusted startup configuration; never accepted from conversation requests."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    host: str = "127.0.0.1"
    port: Annotated[int, Field(ge=1, le=65535)] = 5432
    database: Annotated[str, Field(min_length=1, max_length=63, repr=False)]
    user: Annotated[str, Field(min_length=1, max_length=63, repr=False)]
    password: SecretStr | None = Field(default=None, repr=False)
    schema_name: str = "digital_souls_core"
    connect_timeout: Annotated[int, Field(ge=1, le=30)] = 5
    statement_timeout_ms: Annotated[int, Field(ge=1, le=30000)] = 5000
    lock_timeout_ms: Annotated[int, Field(ge=1, le=30000)] = 3000

    @field_validator("host")
    @classmethod
    def local_host(cls, value: str) -> str:
        if value == "127.0.0.1":
            return value
        if (
            not value.startswith("/")
            or len(value) > 1024
            or str(PurePosixPath(value)) != value
            or ".." in PurePosixPath(value).parts
            or any(character.isspace() or ord(character) < 32 for character in value)
            or any(character in value for character in ",=\\")
        ):
            raise ValueError(
                "PostgreSQL requires an explicit loopback host or Unix socket directory"
            )
        return value

    @field_validator("database", "user")
    @classmethod
    def simple_name(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,62}", value) is None:
            raise ValueError("PostgreSQL database and user must be explicit simple names")
        return value

    @field_validator("schema_name")
    @classmethod
    def dedicated_schema(cls, value: str) -> str:
        if (
            re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value) is None
            or value.startswith("pg_")
            or value in {"public", "information_schema"}
        ):
            raise ValueError("PostgreSQL requires a dedicated schema name")
        return value


def key(binding: Binding) -> str:
    scope = binding.scope
    return json.dumps([scope.subject, scope.client, scope.audience, binding.character_id])


def _lock_key(kind: str, schema_name: str, binding_key: str = "") -> int:
    payload = json.dumps(["digital-souls-core", kind, schema_name, binding_key]).encode()
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big", signed=True)


class PostgresDatabase:
    def __init__(self, config: PostgresConfig) -> None:
        # Revalidate even model_construct/model_copy instances supplied by trusted code.
        self.config = PostgresConfig.model_validate(config.model_dump())

    @contextmanager
    def _connect(self) -> Iterator[Connection[tuple[Any, ...]]]:
        # No implicit libpq routing, credentials, service files or session options.
        if any(name.startswith("PG") and value for name, value in os.environ.items()):
            raise CoreError(503, "storage_configuration", "PostgreSQL environment is not explicit")
        config = self.config
        try:
            with psycopg.connect(
                host=config.host,
                port=config.port,
                dbname=config.database,
                user=config.user,
                password=config.password.get_secret_value() if config.password is not None else "",
                passfile="/dev/null/no-passfile",
                connect_timeout=config.connect_timeout,
                sslmode="disable",
                gssencmode="disable",
                channel_binding="disable",
                require_auth="none,password,md5,scram-sha-256",
                options=(
                    f"-c statement_timeout={config.statement_timeout_ms} "
                    f"-c lock_timeout={config.lock_timeout_ms}"
                ),
            ) as db:
                db.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                db.execute(
                    sql.SQL("SET LOCAL search_path TO {}, pg_temp").format(
                        sql.Identifier(config.schema_name)
                    )
                )
                yield db
        except (psycopg.Error, OSError):
            raise CoreError(
                503, "storage_unavailable", "PostgreSQL storage is unavailable"
            ) from None

    def initialize(self) -> None:
        """Validate each supported schema before atomic migration to v4."""
        name = self.config.schema_name
        with self._connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (_lock_key("schema", name),))
            exists = db.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (name,)).fetchone()
            if exists is None:
                db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
            relations = db.execute(
                "SELECT c.relname,c.relkind FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s",
                (name,),
            ).fetchall()
            other = db.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n "
                "ON n.oid=p.pronamespace WHERE n.nspname=%s) OR EXISTS "
                "(SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
                "WHERE n.nspname=%s AND t.typrelid=0 AND t.typelem=0)",
                (name, name),
            ).fetchone()
            if other is None or other[0]:
                raise CoreError(503, "storage_schema", "Unsupported PostgreSQL schema")
            if not relations:
                create(db)
                return
            if ("schema_version", "r") not in relations:
                raise CoreError(503, "storage_schema", "Unsupported PostgreSQL schema")
            versions = db.execute("SELECT version FROM schema_version").fetchall()
            if versions not in ([(1,)], [(2,)], [(3,)], [(4,)]):
                raise CoreError(503, "storage_schema", "Unsupported PostgreSQL schema")
            version = versions[0][0]
            tables = self._tables(version)
            expected_relations = {(table, "r") for table in tables}
            expected_relations.update((table + "_pkey", "i") for table in tables)
            for table in tables:
                if table != "schema_version":
                    expected_relations.add((table + "_seq_seq", "S"))
                    expected_relations.add((table + "_seq_key", "i"))
            expected_relations.update(
                {("turns_binding_conversation_revision_key", "i"), ("memory_source_lookup", "i")}
            )
            if set(relations) != expected_relations:
                raise CoreError(503, "storage_schema", "Unsupported PostgreSQL schema")
            self._validate_schema(db, version)
            if version == 1:
                db.execute("ALTER TABLE turns ADD COLUMN stated_at TIMESTAMPTZ")
                db.execute("UPDATE schema_version SET version=2")
                self._validate_schema(db, 2)
            if version in (1, 2):
                db.execute(
                    "ALTER TABLE turns ADD COLUMN memory_confirmation TEXT NOT NULL DEFAULT '{}'"
                )
                db.execute("UPDATE schema_version SET version=3")
                self._validate_schema(db, 3)
            if version in (1, 2, 3):
                for statement in TURN_DELETION_DDL:
                    db.execute(statement)
                db.execute("UPDATE schema_version SET version=4")
                self._validate_schema(db, 4)

    @staticmethod
    def _tables(version: int) -> dict[str, tuple[str, ...]]:
        return {
            table: columns
            for table, columns in TABLE_COLUMNS.items()
            if version >= 4 or table not in {"turn_tombstones", "turn_deletions"}
        }

    def _validate_schema(self, db: Connection[tuple[Any, ...]], version: int) -> None:
        name = self.config.schema_name
        columns = db.execute(
            "SELECT table_name,column_name,data_type,is_nullable,is_identity,column_default "
            "FROM information_schema.columns "
            "WHERE table_schema=%s ORDER BY table_name,ordinal_position",
            (name,),
        ).fetchall()
        tables = self._tables(version)
        for table, expected in tables.items():
            if version == 1 and table == "turns":
                expected = tuple(column for column in expected if column != "stated_at")
            if version < 3 and table == "turns":
                expected = tuple(column for column in expected if column != "memory_confirmation")
            owned = [row for row in columns if row[0] == table]
            if tuple(row[1] for row in owned) != expected:
                raise CoreError(503, "storage_schema", "Unsupported PostgreSQL schema")
            for _, column, kind, nullable, identity, default in owned:
                wanted_type = "text"
                wanted_default = None
                if column == "seq":
                    wanted_type = "bigint"
                elif column in {
                    "revision",
                    "memory_epoch",
                    "through_revision",
                    "epoch",
                    "position",
                    "version",
                }:
                    wanted_type = "integer"
                elif column in {"private_mode", "archived", "processed"}:
                    wanted_type = "boolean"
                    wanted_default = "false"
                elif column == "stated_at":
                    wanted_type = "timestamp with time zone"
                if column == "memory_epoch":
                    wanted_default = "0"
                elif column == "memory_excluded":
                    wanted_default = "'[]'::text"
                elif column == "memory_confirmation":
                    wanted_default = "'{}'::text"
                if (
                    kind != wanted_type
                    or nullable
                    != ("YES" if column in {"body", "revoked_by", "stated_at"} else "NO")
                    or identity != ("YES" if column == "seq" else "NO")
                    or default != wanted_default
                ):
                    raise CoreError(503, "storage_schema", "Unsupported PostgreSQL schema")
        constraints = db.execute(
            "SELECT t.relname,c.conname,pg_get_constraintdef(c.oid),"
            "c.convalidated,c.condeferrable,c.condeferred "
            "FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid "
            "JOIN pg_namespace n ON n.oid=t.relnamespace "
            "WHERE n.nspname=%s AND c.contype IN ('p','u','f','c','x')",
            (name,),
        ).fetchall()
        actual = {
            (table, constraint): definition
            for table, constraint, definition, _, _, _ in constraints
        }
        expected_constraints = {
            address: definition
            for address, definition in CONSTRAINTS.items()
            if address[0] in tables
        }
        if actual != expected_constraints or any(
            not valid or deferred or deferrable
            for _, _, _, valid, deferrable, deferred in constraints
        ):
            raise CoreError(503, "storage_schema", "Unsupported PostgreSQL schema")
        hooks = db.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid "
            "JOIN pg_namespace n ON n.oid=t.relnamespace "
            "WHERE n.nspname=%s AND NOT g.tgisinternal) OR EXISTS "
            "(SELECT 1 FROM pg_rewrite r JOIN pg_class t ON t.oid=r.ev_class "
            "JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=%s)",
            (name, name),
        ).fetchone()
        if hooks is None or hooks[0]:
            raise CoreError(503, "storage_schema", "Unsupported PostgreSQL schema")
        if db.execute("SELECT version FROM schema_version").fetchall() != [(version,)]:
            raise CoreError(503, "storage_schema", "Unsupported PostgreSQL schema")

    @contextmanager
    def transaction(self, binding: Binding) -> Iterator[Connection[tuple[Any, ...]]]:
        with self._connect() as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (_lock_key("binding", self.config.schema_name, key(binding)),),
            )
            yield db
