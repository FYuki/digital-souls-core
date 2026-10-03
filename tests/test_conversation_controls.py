import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from digital_souls_core.api import create_app
from digital_souls_core.application import CoreError
from digital_souls_core.character import AccessScope, Profile
from digital_souls_core.history import Binding, ConversationControls, SourceReference
from digital_souls_core.sqlite_history import SQLiteHistory

from .test_conversations import turn
from .test_privacy import BINDING, policy_setup

pytestmark = pytest.mark.it1


async def test_explicit_excluded_utterance_preserves_history_and_retry(tmp_path: Path) -> None:
    service, provider, _, _ = policy_setup(tmp_path)
    cid = service.create("synthetic").conversation_id
    body = turn(
        messages=[
            {"role": "user", "content": "Synthetic excluded"},
            {"role": "user", "content": "Synthetic ordinary"},
        ],
        memory_excluded_indices=[0],
    )
    receipt = await service.complete("synthetic", cid, body)
    assert await service.complete("synthetic", cid, body) == receipt
    assert len(provider.calls) == 1
    assert "memory_excluded_indices" not in provider.calls[0][1]
    assert len(service.read("synthetic", cid).messages) == 3
    assert not service.store.source_eligible(BINDING, SourceReference(cid, 1, 0))
    assert service.store.source_eligible(BINDING, SourceReference(cid, 1, 1))
    assert not service.store.source_eligible(BINDING, SourceReference(cid, 1, 2))
    with pytest.raises(CoreError):
        await service.complete(
            "synthetic", cid, body.model_copy(update={"memory_excluded_indices": []})
        )
    reopened = SQLiteHistory(tmp_path / "private" / "db")
    assert not reopened.source_eligible(BINDING, SourceReference(cid, 1, 0))
    assert reopened.source_eligible(BINDING, SourceReference(cid, 1, 1))


async def test_thread_private_then_public_does_not_retroactively_admit_private_turn(
    tmp_path: Path,
) -> None:
    service, _, _, _ = policy_setup(tmp_path)
    cid = service.create("synthetic").conversation_id
    await service.complete("synthetic", cid, turn())
    assert service.store.source_eligible(BINDING, SourceReference(cid, 1, 0))
    service.controls("synthetic", cid, ConversationControls(expected_revision=1, private_mode=True))
    assert not service.store.source_eligible(BINDING, SourceReference(cid, 1, 0))
    await service.complete("synthetic", cid, turn(request_id="r2", expected_revision=2))
    assert len(service.read("synthetic", cid).messages) == 4
    assert not service.store.source_eligible(BINDING, SourceReference(cid, 3, 0))
    service.controls(
        "synthetic", cid, ConversationControls(expected_revision=3, private_mode=False)
    )
    assert service.store.source_eligible(BINDING, SourceReference(cid, 1, 0))
    assert not service.store.source_eligible(BINDING, SourceReference(cid, 3, 0))


async def test_archive_only_changes_listing_and_preserves_memory_source(tmp_path: Path) -> None:
    service, _, _, policy = policy_setup(tmp_path)
    cid = service.create("synthetic").conversation_id
    await service.complete("synthetic", cid, turn())
    http = TestClient(
        create_app(service.inference, history_store=service.store, history_policy=policy),
        base_url="http://127.0.0.1",
    )
    base = "/v1/characters/synthetic/conversations"
    assert (
        http.patch(f"{base}/{cid}", json={"expected_revision": 1, "archived": True}).status_code
        == 200
    )
    assert http.get(base).json()["conversation_ids"] == []
    assert http.get(base + "?include_archived=true").json()["conversation_ids"] == [cid]
    assert http.get(f"{base}/{cid}").json()["archived"] is True
    assert service.store.source_eligible(BINDING, SourceReference(cid, 1, 0))
    assert (
        http.patch(f"{base}/{cid}", json={"expected_revision": 1, "archived": False}).status_code
        == 409
    )
    assert (
        http.patch(f"{base}/{cid}", json={"expected_revision": 2, "archived": False}).status_code
        == 200
    )
    assert service.list("synthetic") == [cid]


async def test_delete_atomically_notifies_and_invalidates_sources(tmp_path: Path) -> None:
    service, _, _, policy = policy_setup(tmp_path)
    cid = service.create("synthetic").conversation_id
    await service.complete("synthetic", cid, turn())
    source = SourceReference(cid, 1, 0)
    # Synthetic stage-3 consumer only; no production memory repository exists yet.
    derived = {"synthetic-memory": {source}}
    policy.configure({})
    service.delete("synthetic", cid)
    service.delete("synthetic", cid)
    reopened = SQLiteHistory(tmp_path / "private" / "db")
    events = reopened.deletions(BINDING)
    assert len(events) == 1 and events[0].through_revision == 1
    assert not reopened.source_eligible(BINDING, source)
    other = Binding(AccessScope(client="other"), "synthetic")
    assert reopened.deletions(other) == ()
    reopened.acknowledge_deletion(other, events[0].event_id)
    assert reopened.deletions(BINDING) == events
    for event in events:
        derived = {
            key: refs
            for key, refs in derived.items()
            if not any(
                ref.conversation_id == event.conversation_id
                and ref.turn_revision <= event.through_revision
                for ref in refs
            )
        }
        reopened.acknowledge_deletion(BINDING, event.event_id)
    assert derived == {} and reopened.deletions(BINDING) == ()


def test_delete_event_and_history_deletion_rollback_together(tmp_path: Path) -> None:
    service, _, _, _ = policy_setup(tmp_path)
    cid = service.create("synthetic").conversation_id
    db_path = tmp_path / "private" / "db"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TRIGGER reject_delete BEFORE DELETE ON conversations "
            "BEGIN SELECT RAISE(ABORT, 'synthetic'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        service.delete("synthetic", cid)
    assert service.read("synthetic", cid).revision == 0
    assert service.store.deletions(BINDING) == ()


@pytest.mark.parametrize("crash_at", [None, "ALTER TABLE turns", "PRAGMA user_version=2"])
def test_v1_upgrade_preserves_history_and_receipt(tmp_path: Path, crash_at: str | None) -> None:
    path = tmp_path / "private" / "db"
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
        db.execute("PRAGMA user_version=1")
        binding = '["local-operator", "local", "local-private", "synthetic"]'
        db.execute("INSERT INTO conversations VALUES (?,?,?)", (binding, "synthetic-cid", 1))
        db.execute(
            "INSERT INTO turns VALUES (?,?,?,?,?,?,?)",
            (
                binding,
                "synthetic-cid",
                "r1",
                "original-fingerprint",
                1,
                '[{"role":"user","content":"Synthetic"},'
                '{"role":"assistant","content":"Synthetic reply"}]',
                "stop",
            ),
        )
    if crash_at:
        script = """
import os, sqlite3, sys
from pathlib import Path
from digital_souls_core.sqlite_history import SQLiteHistory
connect = sqlite3.connect
def crashing_connect(*args, **kwargs):
    db = connect(*args, **kwargs)
    db.set_trace_callback(lambda sql: os._exit(73) if sys.argv[2] in sql else None)
    return db
sqlite3.connect = crashing_connect
SQLiteHistory(Path(sys.argv[1]))
"""
        process = subprocess.run([sys.executable, "-c", script, str(path), crash_at], check=False)
        assert process.returncode == 73
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1
    store = SQLiteHistory(path)
    assert len(store.read(BINDING, "synthetic-cid").messages) == 2
    receipt = store.receipt(BINDING, "synthetic-cid", "r1")
    assert receipt and receipt.fingerprint == "original-fingerprint"
    assert store.source_eligible(BINDING, SourceReference("synthetic-cid", 1, 0))
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3


async def test_private_change_conflicts_with_inflight_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, provider, _, _ = policy_setup(tmp_path)
    cid = service.create("synthetic").conversation_id
    started, release = asyncio.Event(), asyncio.Event()
    original = provider.complete

    async def wait_complete(profile: Profile, payload: dict[str, Any]) -> dict[str, Any]:
        started.set()
        await release.wait()
        return await original(profile, payload)

    monkeypatch.setattr(provider, "complete", wait_complete)
    task = asyncio.create_task(service.complete("synthetic", cid, turn()))
    await started.wait()
    service.controls("synthetic", cid, ConversationControls(expected_revision=0, private_mode=True))
    release.set()
    with pytest.raises(CoreError):
        await task
    assert service.read("synthetic", cid).messages == ()


@pytest.mark.parametrize("indices", [[-1], [1], [0, 0], [True]])
def test_invalid_message_exclusions_rejected(indices: list[object]) -> None:
    with pytest.raises(ValueError):
        turn(memory_excluded_indices=indices)


@pytest.mark.parametrize("private", [False, True])
async def test_excluded_history_cannot_reenter_via_later_assistant(
    tmp_path: Path, private: bool
) -> None:
    service, provider, _, _ = policy_setup(tmp_path)
    cid = service.create("synthetic").conversation_id
    revision = 0
    if private:
        revision = service.controls(
            "synthetic", cid, ConversationControls(expected_revision=0, private_mode=True)
        ).revision
    first = await service.complete(
        "synthetic",
        cid,
        turn(expected_revision=revision, memory_excluded_indices=[] if private else [0]),
    )
    revision = first.revision
    if private:
        revision = service.controls(
            "synthetic", cid, ConversationControls(expected_revision=revision, private_mode=False)
        ).revision
    provider.response["choices"][0]["message"]["content"] = (
        "Synthetic quotation of excluded history"
    )
    second = await service.complete(
        "synthetic", cid, turn(request_id="r2", expected_revision=revision)
    )
    assert service.store.source_eligible(BINDING, SourceReference(cid, second.revision, 0))
    assert not service.store.source_eligible(BINDING, SourceReference(cid, second.revision, 1))
    snapshot = service.read("synthetic", cid)
    assert [state.eligible for state in snapshot.memory_sources][-2:] == [True, False]
