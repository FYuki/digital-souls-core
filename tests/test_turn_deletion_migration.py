"""SQLite v5 history survives atomic addition of partial deletion storage."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from digital_souls_core.history import SourceReference
from digital_souls_core.sqlite_history import SQLiteHistory
from digital_souls_core.sqlite_memory import SQLiteMemory

from .test_history_stated_at import CID, FIRST, legacy_sqlite
from .test_memory_confirmation import make_harness
from .test_privacy import BINDING
from .test_turn_deletion import delete_turns


def install_v5(path: Path, timestamp: str | None, state: str) -> None:
    legacy_sqlite(path, 3)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE turns ADD COLUMN stated_at TEXT")
        db.execute("ALTER TABLE turns ADD COLUMN memory_confirmation TEXT NOT NULL DEFAULT '{}'")
        db.execute(
            "UPDATE turns SET stated_at=?,memory_confirmation=?",
            (timestamp, state),
        )
        db.execute("PRAGMA user_version=5")


@pytest.mark.parametrize("timestamp", [None, FIRST.isoformat()])
@pytest.mark.parametrize("state", ['{"0":null}', '{"0":false}', '{"0":true}'])
@pytest.mark.it1
def test_v5_migration_preserves_stored_time_confirmation_and_receipt(
    tmp_path: Path,
    timestamp: str | None,
    state: str,
) -> None:
    path = tmp_path / "private" / "db"
    install_v5(path, timestamp, state)
    with sqlite3.connect(path) as db:
        original = db.execute("SELECT * FROM turns").fetchall()
    h = make_harness(SQLiteHistory(path), SQLiteMemory(path))
    with h.http:
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT * FROM turns").fetchall() == original
        snapshot = h.conversation.read("synthetic", CID)
        assert snapshot.memory_sources[0].stated_at == (None if timestamp is None else FIRST)
        assert snapshot.memory_confirmations == (
            (SourceReference(CID, 1, 0),) if json.loads(state)["0"] is None else ()
        )
        assert h.conversation.store.source_eligible(BINDING, SourceReference(CID, 1, 0)) == (
            json.loads(state)["0"] is False
        )
        receipt = h.conversation.store.receipt(BINDING, CID, "r1")
        assert receipt is not None and receipt.fingerprint == "original-fingerprint"
        delete_turns(h, CID, 1, 1, "selected")
        assert h.conversation.read("synthetic", CID).messages == ()


@pytest.mark.ut
def test_v5_migration_interruption_rolls_back_and_allows_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "private" / "db"
    install_v5(path, FIRST.isoformat(), '{"0":null}')
    with sqlite3.connect(path) as db:
        original = db.execute("SELECT * FROM turns").fetchall()
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    connect = sqlite3.connect

    class InterruptedConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            cursor = super().execute(sql, parameters)
            if sql.lstrip().upper().startswith("CREATE TABLE"):
                raise RuntimeError("Synthetic migration interruption")
            return cursor

    def interrupted(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return connect(*args, **kwargs, factory=InterruptedConnection)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", interrupted)
        with pytest.raises(RuntimeError, match="Synthetic migration interruption"):
            SQLiteHistory(path)
    with connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert db.execute("SELECT * FROM turns").fetchall() == original
        assert (
            db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            == tables
        )
    restored = SQLiteHistory(path).read(BINDING, CID)
    assert restored.revision == 1
    assert restored.memory_sources[0].stated_at == FIRST
    assert restored.memory_confirmations == (SourceReference(CID, 1, 0),)
