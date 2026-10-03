"""Small SQLite adapter. No prompts, provider envelopes, or partial turns on disk."""

import json
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .application import CoreError
from .contracts import Message
from .history import Binding, Receipt, Snapshot


def default_history_path() -> Path:
    return Path.home() / ".local" / "share" / "digital-souls-core" / "history.sqlite3"


def _key(binding: Binding) -> str:
    scope = binding.scope
    return json.dumps([scope.subject, scope.client, scope.audience, binding.character_id])


class SQLiteHistory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or default_history_path()).absolute()
        # This release targets local Linux/WSL permissions, not Windows ACL emulation.
        if os.name != "posix":
            raise ValueError("history requires POSIX filesystem permissions")
        for ancestor in (self.path, *self.path.parents):
            if ancestor.is_symlink() or (ancestor / ".git").exists():
                raise ValueError("history must be outside Git and symbolic links")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._check_directory()
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with self._connection() as db:
            # Serialize initialization and atomically commit schema + version.
            # executescript would implicitly commit an existing transaction.
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("unsupported history schema")
            if version == 0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError("unrecognized history database")
                db.execute("""
                    CREATE TABLE conversations (
                        binding TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
                        PRIMARY KEY(binding, id)
                    )
                """)
                db.execute("""
                    CREATE TABLE turns (
                        binding TEXT NOT NULL, conversation TEXT NOT NULL,
                        request TEXT NOT NULL, fingerprint TEXT NOT NULL,
                        revision INTEGER NOT NULL, messages TEXT NOT NULL, finish TEXT NOT NULL,
                        PRIMARY KEY(binding, conversation, request),
                        UNIQUE(binding, conversation, revision),
                        FOREIGN KEY(binding, conversation) REFERENCES conversations(binding, id)
                            ON DELETE CASCADE
                    )
                """)
                db.execute("PRAGMA user_version=1")

    def _check_directory(self) -> None:
        info = self.path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("history directory must be private and owned by this user")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self._check_directory()
        info = self.path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise ValueError("history database must be a private regular file")
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA secure_delete=ON")
            with db:
                yield db
        finally:
            db.close()

    def create(self, binding: Binding) -> Snapshot:
        identifier = str(uuid4())
        with self._connection() as db:
            db.execute("INSERT INTO conversations VALUES (?, ?, 0)", (_key(binding), identifier))
        return Snapshot(identifier, 0, ())

    def list(self, binding: Binding) -> list[str]:
        with self._connection() as db:
            return [
                row[0]
                for row in db.execute(
                    "SELECT id FROM conversations WHERE binding=? ORDER BY rowid", (_key(binding),)
                )
            ]

    def read(self, binding: Binding, conversation_id: str) -> Snapshot:
        with self._connection() as db:
            db.execute("BEGIN")
            row = db.execute(
                "SELECT revision FROM conversations WHERE binding=? AND id=?",
                (_key(binding), conversation_id),
            ).fetchone()
            if row is None:
                raise CoreError(404, "conversation_not_found", "Unknown conversation")
            messages = tuple(
                Message.model_validate(value)
                for turn in db.execute(
                    "SELECT messages FROM turns WHERE binding=? AND conversation=? "
                    "ORDER BY revision",
                    (_key(binding), conversation_id),
                )
                for value in json.loads(turn[0])
            )
            return Snapshot(conversation_id, row[0], messages)

    def receipt(self, binding: Binding, conversation_id: str, request_id: str) -> Receipt | None:
        with self._connection() as db:
            return self._receipt(db, binding, conversation_id, request_id)

    def _receipt(
        self, db: sqlite3.Connection, binding: Binding, conversation_id: str, request_id: str
    ) -> Receipt | None:
        row = db.execute(
            "SELECT fingerprint, revision, messages, finish FROM turns "
            "WHERE binding=? AND conversation=? AND request=?",
            (_key(binding), conversation_id, request_id),
        ).fetchone()
        if row is None:
            return None
        return Receipt(row[0], row[1], Message.model_validate(json.loads(row[2])[-1]), row[3])

    def append(
        self,
        binding: Binding,
        conversation_id: str,
        request_id: str,
        fingerprint: str,
        expected_revision: int,
        messages: tuple[Message, ...],
        finish_reason: str,
    ) -> Receipt:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self._receipt(db, binding, conversation_id, request_id)
            if prior:
                if prior.fingerprint != fingerprint:
                    raise CoreError(409, "request_conflict", "Request id has different input")
                return prior
            cursor = db.execute(
                "UPDATE conversations SET revision=revision+1 "
                "WHERE binding=? AND id=? AND revision=?",
                (_key(binding), conversation_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise CoreError(409, "revision_conflict", "Conversation changed or was deleted")
            encoded = json.dumps([m.model_dump(exclude_none=True) for m in messages])
            db.execute(
                "INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _key(binding),
                    conversation_id,
                    request_id,
                    fingerprint,
                    expected_revision + 1,
                    encoded,
                    finish_reason,
                ),
            )
            return Receipt(fingerprint, expected_revision + 1, messages[-1], finish_reason)

    def delete(self, binding: Binding, conversation_id: str) -> None:
        with self._connection() as db:
            # Idempotent, including unknown IDs or another scope's IDs.
            db.execute(
                "DELETE FROM conversations WHERE binding=? AND id=?",
                (_key(binding), conversation_id),
            )
