"""Turn timestamps across persistence, legacy migration and HTTP snapshots."""

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from digital_souls_core.api import create_app
from digital_souls_core.application import CoreError, Inference
from digital_souls_core.contracts import Message
from digital_souls_core.conversations import Conversations, request_fingerprint
from digital_souls_core.history import ConversationControls, SourceReference, as_utc, current_utc
from digital_souls_core.memory_sql import initialize
from digital_souls_core.sqlite_history import SQLiteHistory, _key
from digital_souls_core.sqlite_memory import SQLiteMemory

from .support import CALL, TOOL, FakeProvider, character, chunk, completion
from .test_conversations import SyntheticPolicy, turn
from .test_history import BINDING, MESSAGES

FIRST = datetime(2024, 2, 29, 12, 34, 56, 123456, tzinfo=UTC)
SECOND = FIRST + timedelta(days=2)
CID = "synthetic-legacy"


@pytest.mark.ut
def test_utc_normalization_preserves_instant_and_rejects_naive_time() -> None:
    assert as_utc(FIRST.astimezone(timezone(timedelta(hours=9)))) == FIRST
    assert as_utc(FIRST).tzinfo == UTC
    with pytest.raises(ValueError):
        as_utc(FIRST.replace(tzinfo=None))


@pytest.mark.ut
def test_current_utc_returns_current_aware_time() -> None:
    before = datetime.now(UTC)
    value = current_utc()
    assert before <= value <= datetime.now(UTC)
    assert value.tzinfo == UTC


def legacy_sqlite(path: Path, version: int, fingerprint: str = "original-fingerprint") -> None:
    """Frozen history schema, independent of the current history constructor."""
    path.parent.mkdir(mode=0o700)
    path.touch(mode=0o600)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE conversations (binding TEXT NOT NULL,id TEXT NOT NULL,"
            "revision INTEGER NOT NULL,PRIMARY KEY(binding,id))"
        )
        db.execute(
            "CREATE TABLE turns (binding TEXT NOT NULL,conversation TEXT NOT NULL,"
            "request TEXT NOT NULL,fingerprint TEXT NOT NULL,revision INTEGER NOT NULL,"
            "messages TEXT NOT NULL,finish TEXT NOT NULL,"
            "PRIMARY KEY(binding,conversation,request),UNIQUE(binding,conversation,revision),"
            "FOREIGN KEY(binding,conversation) REFERENCES conversations(binding,id) "
            "ON DELETE CASCADE)"
        )
        db.execute("INSERT INTO conversations VALUES (?,?,1)", (_key(BINDING), CID))
        db.execute(
            "INSERT INTO turns VALUES (?,?,?,?,1,?,?)",
            (
                _key(BINDING),
                CID,
                "r1",
                fingerprint,
                json.dumps([m.model_dump(exclude_none=True) for m in MESSAGES]),
                "stop",
            ),
        )
        db.execute("PRAGMA user_version=1")
        if version >= 2:
            db.execute("ALTER TABLE conversations ADD private_mode INTEGER NOT NULL DEFAULT 0")
            db.execute("ALTER TABLE conversations ADD archived INTEGER NOT NULL DEFAULT 0")
            db.execute("ALTER TABLE turns ADD memory_excluded TEXT NOT NULL DEFAULT '[]'")
            db.execute("ALTER TABLE turns ADD private_mode INTEGER NOT NULL DEFAULT 0")
            db.execute(
                "CREATE TABLE source_deletions (event TEXT PRIMARY KEY,binding TEXT NOT NULL,"
                "conversation TEXT NOT NULL,through_revision INTEGER NOT NULL)"
            )
            db.execute("PRAGMA user_version=2")
        if version == 3:
            initialize(db)


@pytest.mark.ut
def test_clock_is_sampled_per_turn_and_restored_for_every_message(tmp_path: Path) -> None:
    times = iter((FIRST.astimezone(timezone(timedelta(hours=9))), SECOND))
    path = tmp_path / "private" / "db"
    store = SQLiteHistory(path, clock=lambda: next(times))
    cid = store.create(BINDING).conversation_id
    messages = (
        MESSAGES[0],
        Message(role="tool", content="Synthetic result", tool_call_id="c"),
        MESSAGES[-1],
    )
    receipt = store.append(BINDING, cid, "r1", "fp1", 0, messages, "stop")
    store.controls(BINDING, cid, ConversationControls(expected_revision=1, archived=True))
    store.append(BINDING, cid, "r2", "fp2", 2, MESSAGES, "stop")
    assert store.append(BINDING, cid, "r1", "fp1", 0, messages, "stop") == receipt
    restored = SQLiteHistory(path).read(BINDING, cid)
    assert restored.messages == messages + MESSAGES
    assert [s.reference.turn_revision for s in restored.memory_sources] == [1, 1, 1, 3, 3]
    assert [s.stated_at for s in restored.memory_sources] == [FIRST] * 3 + [SECOND] * 2
    assert all(
        s.stated_at is not None and s.stated_at.utcoffset() == timedelta(0)
        for s in restored.memory_sources
    )


@pytest.mark.ut
def test_default_clock_records_current_utc_at_append(tmp_path: Path) -> None:
    store = SQLiteHistory(tmp_path / "private" / "db")
    cid = store.create(BINDING).conversation_id
    before = datetime.now(UTC)
    store.append(BINDING, cid, "r1", "fp", 0, MESSAGES, "stop")
    after = datetime.now(UTC)
    timestamp = store.read(BINDING, cid).memory_sources[0].stated_at
    assert timestamp is not None
    assert before <= timestamp <= after
    assert timestamp.utcoffset() == timedelta(0)


@pytest.mark.ut
def test_naive_clock_rejects_without_turn_or_revision_and_allows_retry(tmp_path: Path) -> None:
    times = iter((FIRST.replace(tzinfo=None), FIRST))
    store = SQLiteHistory(tmp_path / "private" / "db", clock=lambda: next(times))
    created = store.create(BINDING)
    with pytest.raises((ValueError, CoreError)):
        store.append(BINDING, created.conversation_id, "r1", "fp", 0, MESSAGES, "stop")
    assert store.read(BINDING, created.conversation_id) == created
    assert store.receipt(BINDING, created.conversation_id, "r1") is None
    store.append(BINDING, created.conversation_id, "r1", "fp", 0, MESSAGES, "stop")
    assert store.read(BINDING, created.conversation_id).memory_sources[0].stated_at == FIRST


@pytest.mark.ut
@pytest.mark.parametrize("version", [1, 2, 3])
def test_legacy_migration_preserves_null_receipt_fingerprint_and_evidence(
    tmp_path: Path,
    version: int,
) -> None:
    path = tmp_path / "private" / "db"
    legacy_sqlite(path, version)
    store = SQLiteMemory(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT stated_at FROM turns").fetchall() == [(None,)]
    before = store.read(BINDING, CID)
    assert before.messages == MESSAGES and before.revision == 1
    assert [s.stated_at for s in before.memory_sources] == [None, None]
    receipt = store.receipt(BINDING, CID, "r1")
    assert receipt is not None and receipt.fingerprint == "original-fingerprint"
    assert store.append(BINDING, CID, "r1", "original-fingerprint", 0, MESSAGES, "stop") == receipt
    assert store.read(BINDING, CID) == before
    evidence = store.sources(BINDING, (SourceReference(CID, 1, 0),))
    assert evidence[0].stated_at is None
    assert evidence[0].text == MESSAGES[0].content and evidence[0].source.epoch == 0
    current = SQLiteMemory(path, clock=lambda: FIRST)
    current.append(BINDING, CID, "r2", "fp2", 1, MESSAGES, "stop")
    assert [s.stated_at for s in current.read(BINDING, CID).memory_sources] == [
        None,
        None,
        FIRST,
        FIRST,
    ]
    assert current.receipt(BINDING, CID, "r1") == receipt


@pytest.mark.ut
@pytest.mark.parametrize("crash_at", ["PRAGMA user_version=4", "COMMIT"])
def test_v4_migration_process_exit_rolls_back_then_retries(tmp_path: Path, crash_at: str) -> None:
    path = tmp_path / "private" / "db"
    legacy_sqlite(path, 3)
    with sqlite3.connect(path) as db:
        original = db.execute("SELECT * FROM turns").fetchall()
    # Exiting before the version update observes rollback after ALTER; exiting
    # before COMMIT observes rollback after both schema and version changed.
    script = """
import os, sqlite3, sys
from pathlib import Path
from digital_souls_core.sqlite_history import SQLiteHistory
connect = sqlite3.connect
def crashing_connect(*args, **kwargs):
    db = connect(*args, **kwargs)
    db.set_trace_callback(lambda sql: os._exit(73)
        if ''.join(sql.upper().split()) == ''.join(sys.argv[2].upper().split()) else None)
    return db
sqlite3.connect = crashing_connect
SQLiteHistory(Path(sys.argv[1]))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), crash_at], check=False, timeout=15
    )
    assert result.returncode == 73
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert "stated_at" not in {r[1] for r in db.execute("PRAGMA table_info(turns)")}
        assert db.execute("SELECT * FROM turns").fetchall() == original
    restored = SQLiteHistory(path)
    assert restored.read(BINDING, CID).messages == MESSAGES
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT stated_at FROM turns").fetchall() == [(None,)]


@pytest.mark.ut
def test_evidence_uses_saved_time_without_changing_source_or_job_identity(tmp_path: Path) -> None:
    path = tmp_path / "private" / "db"
    store = SQLiteMemory(path, clock=lambda: FIRST)
    cid = store.create(BINDING).conversation_id
    store.append(BINDING, cid, "r1", "fp", 0, MESSAGES, "stop")
    ref = SourceReference(cid, 1, 0)
    evidence = store.sources(BINDING, (ref,))[0]
    job = store.begin(BINDING, (evidence.source,), "synthetic-v1")
    restored = SQLiteMemory(path, clock=lambda: SECOND)
    reread = restored.sources(BINDING, (ref,))[0]
    assert reread.stated_at == FIRST
    assert reread.source == evidence.source and reread.text == evidence.text
    assert restored.current(BINDING, job.sources)
    assert restored.begin(BINDING, job.sources, job.versions) == job


@pytest.mark.it1
@pytest.mark.parametrize("stream", [False, True])
def test_http_completion_get_and_patch_preserve_turn_times(tmp_path: Path, stream: bool) -> None:
    times = iter((FIRST, SECOND))
    store = SQLiteHistory(tmp_path / "private" / "db", clock=lambda: next(times))
    provider = FakeProvider()
    inference = Inference((character("synthetic"),), provider)
    with TestClient(
        create_app(inference, history_store=store, history_policy=SyntheticPolicy()),
        base_url="http://127.0.0.1",
    ) as http:
        base = "/v1/characters/synthetic/conversations"
        cid = http.post(base).json()["conversation_id"]
        url = f"{base}/{cid}"
        provider.response = completion(tool=True)
        provider.chunks = [chunk({"tool_calls": [{"index": 0, **CALL}]}), chunk({}, "tool_calls")]
        assert (
            http.post(
                url + "/completions", json=turn(tools=[TOOL], stream=stream).model_dump()
            ).status_code
            == 200
        )
        provider.response = completion()
        provider.chunks = [chunk({"content": "Synthetic response"}), chunk({}, "stop")]
        body = turn(
            request_id="r2",
            expected_revision=1,
            tools=[TOOL],
            stream=stream,
            messages=[
                {"role": "tool", "content": "Synthetic result", "tool_call_id": CALL["id"]},
                {"role": "user", "content": "Synthetic next"},
            ],
        ).model_dump()
        response = http.post(url + "/completions", json=body)
        assert response.status_code == 200
        assert http.post(url + "/completions", json=body).text == response.text
        for snapshot in (
            http.get(url),
            http.patch(url, json={"expected_revision": 2, "archived": True}),
        ):
            assert snapshot.status_code == 200
            data = snapshot.json()
            assert [s["turn_revision"] for s in data["memory_sources"]] == [1, 1, 2, 2, 2]
            assert [datetime.fromisoformat(s["stated_at"]) for s in data["memory_sources"]] == [
                FIRST
            ] * 2 + [SECOND] * 3
            assert all("stated_at" not in message for message in data["messages"])
    assert len(provider.calls) == 2


@pytest.mark.it1
async def test_legacy_http_null_and_service_retry_do_not_infer_again(tmp_path: Path) -> None:
    config = character("synthetic")
    path = tmp_path / "private" / "db"
    legacy_sqlite(path, 3, request_fingerprint(turn(), config.config))
    store = SQLiteHistory(path)
    provider = FakeProvider()
    service = Conversations(Inference((config,), provider), store, SyntheticPolicy())
    receipt = store.receipt(BINDING, CID, "r1")
    assert await service.complete("synthetic", CID, turn()) == receipt
    assert provider.calls == []
    with TestClient(
        create_app(service.inference, history_store=store, history_policy=service.policy),
        base_url="http://127.0.0.1",
    ) as http:
        response = http.get(f"/v1/characters/synthetic/conversations/{CID}")
        assert response.status_code == 200
        assert [s["stated_at"] for s in response.json()["memory_sources"]] == [None, None]
