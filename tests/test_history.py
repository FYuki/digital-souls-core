import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from digital_souls_core.application import CoreError
from digital_souls_core.character import AccessScope
from digital_souls_core.contracts import Message
from digital_souls_core.history import Binding
from digital_souls_core.sqlite_history import SQLiteHistory, default_history_path

pytestmark = pytest.mark.ut
BINDING = Binding(AccessScope(), "synthetic")
MESSAGES = (
    Message(role="user", content="Synthetic hello"),
    Message(role="assistant", content="Synthetic answer"),
)


def test_order_reopen_idempotency_conflict_and_delete(tmp_path: Path) -> None:
    path = tmp_path / "private" / "history.sqlite3"
    store = SQLiteHistory(path)
    first = store.create(BINDING)
    second = store.create(BINDING)
    assert store.list(BINDING) == [first.conversation_id, second.conversation_id]
    receipt = store.append(BINDING, first.conversation_id, "r1", "fp1", 0, MESSAGES, "stop")
    store = SQLiteHistory(path)
    assert store.append(BINDING, first.conversation_id, "r1", "fp1", 0, MESSAGES, "stop") == receipt
    for request_id, fp in [("r1", "different"), ("r2", "fp2")]:
        with pytest.raises(CoreError):
            store.append(BINDING, first.conversation_id, request_id, fp, 0, MESSAGES, "stop")
    store.append(BINDING, first.conversation_id, "r2", "fp2", 1, MESSAGES, "stop")
    assert store.read(BINDING, first.conversation_id).messages == MESSAGES * 2
    store.delete(BINDING, first.conversation_id)
    store.delete(BINDING, first.conversation_id)
    assert store.receipt(BINDING, first.conversation_id, "r1") is None
    assert store.list(BINDING) == [second.conversation_id]
    with pytest.raises(CoreError):
        store.append(BINDING, first.conversation_id, "r3", "fp3", 2, MESSAGES, "stop")
    assert b"Synthetic hello" not in path.read_bytes()
    assert not Path(str(path) + "-wal").exists()
    assert not Path(str(path) + "-journal").exists()


@pytest.mark.parametrize(
    "other",
    [
        Binding(AccessScope(subject="other"), "synthetic"),
        Binding(AccessScope(client="other"), "synthetic"),
        replace(BINDING, character_id="other"),
    ],
)
def test_every_store_operation_is_scoped(tmp_path: Path, other: Binding) -> None:
    store = SQLiteHistory(tmp_path / "private" / "history.sqlite3")
    cid = store.create(BINDING).conversation_id
    store.append(BINDING, cid, "r1", "fp", 0, MESSAGES, "stop")
    assert store.list(other) == []
    assert store.receipt(other, cid, "r1") is None
    with pytest.raises(CoreError):
        store.read(other, cid)
    with pytest.raises(CoreError):
        store.append(other, cid, "r2", "fp", 1, MESSAGES, "stop")
    store.delete(other, cid)
    assert store.read(BINDING, cid).revision == 1


def test_secure_defaults_and_reject_unsafe_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_history_path() == tmp_path / ".local/share/digital-souls-core/history.sqlite3"
    store = SQLiteHistory()
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.path.parent.stat().st_mode & 0o777 == 0o700
    store.path.chmod(0o644)
    with pytest.raises(ValueError):
        store.list(BINDING)
    store.path.chmod(0o600)
    os.link(store.path, store.path.parent / "hardlink")
    with pytest.raises(ValueError):
        SQLiteHistory(store.path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: somewhere")
    with pytest.raises(ValueError):
        SQLiteHistory(repo / "private" / "db")
    link = tmp_path / "link"
    link.symlink_to(repo, target_is_directory=True)
    with pytest.raises(ValueError):
        SQLiteHistory(link / "private" / "db")
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    with pytest.raises(ValueError):
        SQLiteHistory(public / "db")


def test_unknown_schema_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "private" / "db"
    store = SQLiteHistory(path)
    store.create(BINDING)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError):
        SQLiteHistory(path)


def test_request_fingerprint_survives_process_hash_seed() -> None:
    script = """
from digital_souls_core.conversations import request_fingerprint
from digital_souls_core.history import TurnInput
from digital_souls_core.contracts import Message
from tests.support import character
body = TurnInput(request_id="retry", expected_revision=0,
                 messages=[Message(role="user", content="Synthetic")])
print(request_fingerprint(body, character("synthetic").config))
"""
    values = [
        subprocess.check_output(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONHASHSEED": seed},
            text=True,
        ).strip()
        for seed in ("1", "2")
    ]
    assert len(values[0]) == 64
    assert values[0] == values[1]


@pytest.mark.parametrize(
    "crash_at",
    ["CREATE TABLE turns", "PRAGMA user_version=1", "ALTER TABLE turns", "PRAGMA user_version=2"],
)
def test_first_schema_creation_recovers_after_process_exit(tmp_path: Path, crash_at: str) -> None:
    path = tmp_path / "private" / "db"
    script = """
import os, sqlite3, sys
from pathlib import Path
from digital_souls_core.sqlite_history import SQLiteHistory
connect = sqlite3.connect
def crashing_connect(*args, **kwargs):
    db = connect(*args, **kwargs)
    def trace(sql):
        if sys.argv[2] in sql:
            os._exit(73)
    db.set_trace_callback(trace)
    return db
sqlite3.connect = crashing_connect
SQLiteHistory(Path(sys.argv[1]))
"""
    result = subprocess.run([sys.executable, "-c", script, str(path), crash_at], check=False)
    assert result.returncode == 73
    store = SQLiteHistory(path)
    assert store.create(BINDING).revision == 0
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert {
            row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        } == {
            "conversations",
            "turns",
            "source_deletions",
            "memory_events",
            "memory_jobs",
            "memories",
            "memory_sources",
        }


def test_unknown_unversioned_schema_still_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "private" / "db"
    path.parent.mkdir(mode=0o700)
    path.touch(mode=0o600)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unknown (value TEXT)")
        db.execute("INSERT INTO unknown VALUES ('Synthetic preserved value')")
    with pytest.raises(ValueError, match="unrecognized history database"):
        SQLiteHistory(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM unknown").fetchone()[0] == "Synthetic preserved value"
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
