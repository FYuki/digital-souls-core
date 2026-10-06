"""Storage refusal contracts through the conversation API and real memory stores."""

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from digital_souls_core.api import create_app
from digital_souls_core.application import CoreError, Inference
from digital_souls_core.character import AccessScope, Profile
from digital_souls_core.conversations import Conversations, request_fingerprint
from digital_souls_core.history import Binding, HistoryStore, SourceReference
from digital_souls_core.local_extractor import LocalExtractor
from digital_souls_core.memory import MemoryService
from digital_souls_core.memory_contracts import MemoryStore, SourceVersion
from digital_souls_core.privacy import PrivacyPolicy
from digital_souls_core.privacy_classifier import LocalClassifier
from digital_souls_core.sqlite_history import SQLiteHistory
from digital_souls_core.sqlite_memory import SQLiteMemory

from .support import TOOL, FakeProvider, character, chunk, completion
from .test_conversations import turn
from .test_history_stated_at import CID, FIRST, legacy_sqlite
from .test_memory import selection
from .test_privacy import BINDING, assessment, local_profile

pytestmark = pytest.mark.it1
BASE = "/v1/characters/synthetic/conversations"


@dataclass
class Harness:
    conversation: Conversations
    memory: MemoryService
    provider: FakeProvider
    extractor: FakeProvider
    policy: PrivacyPolicy
    http: TestClient


def make_harness(history: HistoryStore, memory: MemoryStore) -> Harness:
    provider, extractor, classifier = FakeProvider(), FakeProvider(), FakeProvider()
    classifier.response["choices"][0]["message"]["content"] = assessment()
    extractor.response["choices"][0]["message"]["content"] = selection()
    policy = PrivacyPolicy(LocalClassifier(classifier, local_profile(), model_digest="synthetic"))
    policy.configure({BINDING: frozenset({"history", "local", "external", "memory"})})
    char = character("synthetic")
    char = type(char)(
        char.config.model_copy(update={"profile": local_profile()}), char.system_prompt
    )
    inference = Inference((char,), provider, privacy=policy)
    conversation = Conversations(inference, history, policy)
    service = MemoryService(
        memory, policy, LocalExtractor(extractor, local_profile(), model_digest="synthetic")
    )
    return Harness(
        conversation,
        service,
        provider,
        extractor,
        policy,
        TestClient(
            create_app(inference, history_store=history, history_policy=policy),
            base_url="http://127.0.0.1",
            raise_server_exceptions=False,
        ),
    )


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    path = tmp_path / "private" / "db"
    value = make_harness(SQLiteHistory(path), SQLiteMemory(path))
    with value.http:
        yield value


def complete(harness: Harness, cid: str, **changes: Any) -> dict[str, Any]:
    body = turn(**changes)
    response = harness.http.post(
        f"{BASE}/{cid}/completions", json=body.model_dump(exclude_none=True)
    )
    assert response.status_code == 200, response.text
    if body.stream:
        events = response.text.split("\n\n")
        completed = [event for event in events if event.startswith("event: completed\ndata: ")]
        assert len(completed) == 1
        return json.loads(completed[0].split("\ndata: ", 1)[1])  # type: ignore[no-any-return]
    return response.json()  # type: ignore[no-any-return]


def answer(
    harness: Harness, cid: str, revision: int, index: int, accept: bool, *, turn_revision: int = 1
) -> dict[str, Any]:
    response = harness.http.post(
        f"{BASE}/{cid}/memory-confirmations",
        json={
            "expected_revision": revision,
            "turn_revision": turn_revision,
            "message_index": index,
            "accept_private_mode": accept,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def objects(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "texts",
    [
        ("覚えないで 合成発話alpha", "don't record synthetic-message-beta"),
        ("記録しないで 合成発話gamma", "do not remember synthetic-message-delta"),
    ],
)
def test_refusal_signal_identifies_each_user_source_without_content(
    harness: Harness, stream: bool, texts: tuple[str, str]
) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    data = complete(
        harness,
        cid,
        stream=stream,
        messages=[{"role": "user", "content": text} for text in texts],
    )
    signal = data["memory_confirmation"]
    nodes = list(objects(signal))
    references = {
        (node["turn_revision"], node["message_index"])
        for node in nodes
        if "turn_revision" in node and "message_index" in node
    }
    assert references == {(1, 0), (1, 1)}
    encoded = json.dumps(signal, ensure_ascii=False).casefold()
    for text in texts:
        for word in text.casefold().split():
            if word not in {"do", "not", "don't"}:
                assert word not in encoded
    guides = set(strings(signal))
    assert f"{BASE}/{cid}/memory-confirmations" in guides
    assert f"{BASE}/{cid}" in guides
    snapshot = harness.http.get(f"{BASE}/{cid}").json()
    assert snapshot["private_mode"] is False
    assert snapshot["memory_confirmations"] == [
        {"turn_revision": 1, "message_index": 0},
        {"turn_revision": 1, "message_index": 1},
    ]
    assert [s["eligible"] for s in snapshot["memory_sources"][:2]] == [False, False]
    assert [m["content"] for m in snapshot["messages"][:2]] == list(texts)
    assert "memory_confirmation" not in harness.provider.calls[0][1]


@pytest.mark.parametrize("stream", [False, True])
def test_refusal_signal_guides_user_selected_turn_and_whole_history_deletion(
    harness: Harness, stream: bool
) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    data = complete(
        harness, cid, stream=stream, messages=[{"role": "user", "content": "覚えないで 合成発話"}]
    )
    signal = data["memory_confirmation"]
    assert signal["delete_history"] == {"method": "DELETE", "path": f"{BASE}/{cid}"}
    assert signal["delete_turns"] == {
        "method": "POST",
        "path": f"{BASE}/{cid}/turn-deletions",
        "scopes": ["selected", "following"],
    }
    snapshot = harness.http.get(f"{BASE}/{cid}").json()
    assert snapshot["revision"] == 1
    assert snapshot["private_mode"] is False
    assert [message["content"] for message in snapshot["messages"]] == [
        "覚えないで 合成発話",
        data["message"]["content"],
    ]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "reply",
    [
        '> 覚えないで / "don\'t record"',
        "`覚えないで` and `don't record`",
        "```text\n覚えないで\n```",
        "~~~text\ndon't record\n~~~",
        "> ```text\n> 覚えないで\n> ```",
        "```text\ndon't record",
    ],
)
def test_assistant_refusal_quotes_and_history_do_not_hold_new_user(
    harness: Harness, stream: bool, reply: str
) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    harness.provider.response["choices"][0]["message"]["content"] = reply
    harness.provider.chunks = [chunk({"content": reply}), chunk({}, "stop")]
    # A past user refusal and the assistant text must not affect this new turn.
    complete(harness, cid, messages=[{"role": "user", "content": "覚えないで"}])
    data = complete(harness, cid, request_id="r2", expected_revision=1, stream=stream)
    assert "memory_confirmation" not in data
    ref = SourceReference(cid, 2, 0)
    assert harness.conversation.store.source_eligible(BINDING, ref)
    assert harness.memory.store.sources(BINDING, (ref,))[0].text == "Synthetic hello"


def test_tool_refusal_text_does_not_create_confirmation(harness: Harness) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    harness.provider.response = completion(tool=True)
    complete(harness, cid, tools=[TOOL])
    harness.provider.response = completion()
    data = complete(
        harness,
        cid,
        request_id="r2",
        expected_revision=1,
        tools=[TOOL],
        messages=[{"role": "tool", "tool_call_id": "call_42", "content": "don't record"}],
    )
    assert "memory_confirmation" not in data


async def test_unanswered_source_is_rejected_before_extraction(harness: Harness) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    complete(harness, cid, messages=[{"role": "user", "content": "覚えないで"}])
    ref = SourceReference(cid, 1, 0)
    with pytest.raises(CoreError):
        harness.memory.store.sources(BINDING, (ref,))
    with pytest.raises(CoreError):
        await harness.memory.extract(BINDING, (ref,))
    assert harness.extractor.calls == []


async def test_decline_releases_only_target_and_preserves_explicit_exclusion(
    harness: Harness,
) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    texts = ["覚えないで 合成のお茶", "記録しないで 合成のミント", "don't record"]
    complete(
        harness,
        cid,
        messages=[{"role": "user", "content": text} for text in texts],
        memory_excluded_indices=[1],
    )
    refs = tuple(SourceReference(cid, 1, index) for index in range(3))
    assert all(not harness.conversation.store.source_eligible(BINDING, ref) for ref in refs)
    released = answer(harness, cid, 1, 0, False)
    assert released["revision"] == 2 and released["private_mode"] is False
    assert released["memory_confirmations"] == [
        {"turn_revision": 1, "message_index": 1},
        {"turn_revision": 1, "message_index": 2},
    ]
    assert harness.conversation.store.source_eligible(BINDING, refs[0])
    formed = await harness.memory.extract(BINDING, (refs[0],))
    assert json.loads(formed[0].text) == [texts[0]]
    answer(harness, cid, 2, 1, False)
    for ref in refs[1:]:
        assert not harness.conversation.store.source_eligible(BINDING, ref)
        with pytest.raises(CoreError):
            harness.memory.store.sources(BINDING, (ref,))
    assert [m.content for m in harness.conversation.read("synthetic", cid).messages[:3]] == texts


async def test_accept_erases_existing_memory_and_never_restores_accepted_source(
    harness: Harness,
) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    complete(harness, cid)
    old_ref = SourceReference(cid, 1, 0)
    old = await harness.memory.extract(BINDING, (old_ref,))
    assert harness.memory.store.valid(BINDING, old)
    assert await harness.memory.search(BINDING, "Synthetic") == old
    complete(
        harness,
        cid,
        request_id="r2",
        expected_revision=1,
        messages=[{"role": "user", "content": "覚えないで"}],
    )
    before = harness.conversation.read("synthetic", cid)
    accepted = answer(harness, cid, 2, 0, True, turn_revision=2)
    assert accepted["revision"] == 3 and accepted["private_mode"] is True
    assert harness.conversation.read("synthetic", cid).messages == before.messages
    assert not harness.memory.store.valid(BINDING, old)
    assert await harness.memory.search(BINDING, "Synthetic") == ()
    response = harness.http.patch(
        f"{BASE}/{cid}", json={"expected_revision": 3, "private_mode": False}
    )
    assert response.status_code == 200
    assert not harness.memory.store.valid(BINDING, old)
    assert await harness.memory.search(BINDING, "Synthetic") == ()
    with pytest.raises(CoreError):
        await harness.memory.extract(BINDING, (SourceReference(cid, 2, 0),))
    assert harness.conversation.read("synthetic", cid).messages == before.messages


def test_stale_and_repeated_confirmation_leave_state_unchanged(harness: Harness) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    complete(harness, cid, messages=[{"role": "user", "content": "覚えないで"}])
    before = harness.conversation.read("synthetic", cid)
    body = {
        "expected_revision": 0,
        "turn_revision": 1,
        "message_index": 0,
        "accept_private_mode": True,
    }
    response = harness.http.post(f"{BASE}/{cid}/memory-confirmations", json=body)
    assert response.status_code == 409
    assert harness.conversation.read("synthetic", cid) == before
    answer(harness, cid, 1, 0, False)
    resolved = harness.conversation.read("synthetic", cid)
    body["expected_revision"] = 2
    response = harness.http.post(f"{BASE}/{cid}/memory-confirmations", json=body)
    assert response.status_code == 409
    assert harness.conversation.read("synthetic", cid) == resolved


def test_confirmation_obeys_history_policy(harness: Harness) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    complete(harness, cid, messages=[{"role": "user", "content": "覚えないで"}])
    before = harness.conversation.read("synthetic", cid)
    harness.policy.configure({})
    response = harness.http.post(
        f"{BASE}/{cid}/memory-confirmations",
        json={
            "expected_revision": 1,
            "turn_revision": 1,
            "message_index": 0,
            "accept_private_mode": True,
        },
    )
    assert response.status_code == 403
    assert harness.conversation.store.read(BINDING, cid) == before


def test_confirmation_cannot_change_another_binding(harness: Harness) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    complete(harness, cid, messages=[{"role": "user", "content": "覚えないで"}])
    before = harness.conversation.store.read(BINDING, cid)
    other = Binding(AccessScope(client="synthetic-other"), "synthetic")
    harness.policy.configure({other: frozenset({"history", "local", "memory"})})
    harness.conversation.inference.scope = other.scope
    response = harness.http.post(
        f"{BASE}/{cid}/memory-confirmations",
        json={
            "expected_revision": 1,
            "turn_revision": 1,
            "message_index": 0,
            "accept_private_mode": True,
        },
    )
    assert response.status_code >= 400
    assert harness.conversation.store.read(BINDING, cid) == before


def test_decline_does_not_disable_private_mode(harness: Harness) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    complete(harness, cid, messages=[{"role": "user", "content": "覚えないで"}])
    response = harness.http.patch(
        f"{BASE}/{cid}", json={"expected_revision": 1, "private_mode": True}
    )
    assert response.status_code == 200
    after = answer(harness, cid, 2, 0, False)
    assert after["private_mode"] is True
    assert not harness.conversation.store.source_eligible(BINDING, SourceReference(cid, 1, 0))
    with pytest.raises(CoreError):
        harness.memory.store.sources(BINDING, (SourceReference(cid, 1, 0),))


async def test_confirmation_invalidates_inflight_completion(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    complete(harness, cid, messages=[{"role": "user", "content": "覚えないで"}])
    started, release = asyncio.Event(), asyncio.Event()
    original = harness.provider.complete

    async def waiting(profile: Profile, payload: dict[str, Any]) -> dict[str, Any]:
        started.set()
        await release.wait()
        return await original(profile, payload)

    monkeypatch.setattr(harness.provider, "complete", waiting)
    task = asyncio.create_task(
        harness.conversation.complete("synthetic", cid, turn(request_id="r2", expected_revision=1))
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        answer(harness, cid, 1, 0, False)
    finally:
        release.set()
        # Consume the task even when the API assertion fails during test-first execution.
        result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], CoreError)
    assert harness.conversation.read("synthetic", cid).revision == 2
    assert harness.conversation.store.receipt(BINDING, cid, "r2") is None


def test_resolved_confirmation_retry_keeps_receipt_dates_and_does_not_rehold(
    harness: Harness,
) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    body = turn(messages=[{"role": "user", "content": "覚えないで"}])
    first = complete(harness, cid, **body.model_dump())
    assert "memory_confirmation" in first
    before = harness.conversation.read("synthetic", cid)
    receipt = harness.conversation.store.receipt(BINDING, cid, "r1")
    assert receipt is not None
    assert receipt.fingerprint == request_fingerprint(
        body, harness.conversation.inference.characters["synthetic"].config
    )
    answer(harness, cid, 1, 0, False)
    assert complete(harness, cid, **body.model_dump()) == first
    after = harness.conversation.read("synthetic", cid)
    assert after.messages == before.messages
    assert [(s.reference, s.stated_at) for s in after.memory_sources] == [
        (s.reference, s.stated_at) for s in before.memory_sources
    ]
    assert len(harness.provider.calls) == 1
    assert after.revision == 2
    assert harness.conversation.store.source_eligible(BINDING, SourceReference(cid, 1, 0))


def test_pending_confirmation_and_receipt_survive_sqlite_restart(
    harness: Harness,
    tmp_path: Path,
) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    body = turn(messages=[{"role": "user", "content": "覚えないで"}])
    first = complete(harness, cid, **body.model_dump())
    before = harness.conversation.read("synthetic", cid)
    path = tmp_path / "private" / "db"
    restored = make_harness(SQLiteHistory(path), SQLiteMemory(path))
    with restored.http:
        assert restored.conversation.read("synthetic", cid) == before
        assert restored.http.get(f"{BASE}/{cid}").json()["memory_confirmations"] == [
            {"turn_revision": 1, "message_index": 0}
        ]
        assert not restored.conversation.store.source_eligible(BINDING, SourceReference(cid, 1, 0))
        with pytest.raises(CoreError):
            restored.memory.store.sources(BINDING, (SourceReference(cid, 1, 0),))
        assert complete(restored, cid, **body.model_dump()) == first
        assert restored.provider.calls == []
        answer(restored, cid, 1, 0, False)


async def test_sqlite_accept_rollback_preserves_memory_and_allows_retry(
    harness: Harness,
    tmp_path: Path,
) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    complete(harness, cid)
    old = await harness.memory.extract(BINDING, (SourceReference(cid, 1, 0),))
    complete(
        harness,
        cid,
        request_id="r2",
        expected_revision=1,
        messages=[{"role": "user", "content": "覚えないで"}],
    )
    before = harness.conversation.read("synthetic", cid)
    path = tmp_path / "private" / "db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TRIGGER reject_revoke BEFORE UPDATE OF body ON memories "
            "BEGIN SELECT RAISE(ABORT, 'synthetic'); END"
        )
    response = harness.http.post(
        f"{BASE}/{cid}/memory-confirmations",
        json={
            "expected_revision": 2,
            "turn_revision": 2,
            "message_index": 0,
            "accept_private_mode": True,
        },
    )
    assert response.status_code >= 400
    assert harness.conversation.read("synthetic", cid) == before
    assert harness.memory.store.valid(BINDING, old)
    assert harness.memory.store.events(BINDING) == ()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT body FROM memories").fetchone()[0] == old[0].text
        db.execute("DROP TRIGGER reject_revoke")
    answer(harness, cid, 2, 0, True, turn_revision=2)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT body FROM memories").fetchall() == [(None,)]
    assert not harness.memory.store.valid(BINDING, old)


def test_pending_source_is_not_current_for_memory_commit(harness: Harness) -> None:
    cid = harness.conversation.create("synthetic").conversation_id
    complete(harness, cid, messages=[{"role": "user", "content": "覚えないで"}])
    version = SourceVersion(SourceReference(cid, 1, 0), 0)
    assert not harness.memory.store.current(BINDING, (version,))


@pytest.mark.parametrize("timestamp", [None, FIRST.isoformat()])
def test_sqlite_v4_migration_keeps_old_dates_receipts_and_does_not_scan_history(
    tmp_path: Path,
    timestamp: str | None,
) -> None:
    path = tmp_path / "private" / "db"
    legacy_sqlite(path, 3)
    messages = [
        {"role": "user", "content": "覚えないで"},
        {"role": "assistant", "content": "Synthetic reply"},
    ]
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE turns ADD COLUMN stated_at TEXT")
        db.execute(
            "UPDATE turns SET stated_at=?,messages=?",
            (timestamp, json.dumps(messages, ensure_ascii=False)),
        )
        db.execute("PRAGMA user_version=4")
    restored = make_harness(SQLiteHistory(path), SQLiteMemory(path))
    with restored.http:
        snapshot = restored.conversation.read("synthetic", CID)
        assert [m.model_dump(exclude_none=True) for m in snapshot.messages] == messages
        assert snapshot.memory_sources[0].reference == SourceReference(CID, 1, 0)
        assert snapshot.memory_sources[0].stated_at == (None if timestamp is None else FIRST)
        assert restored.conversation.store.source_eligible(BINDING, SourceReference(CID, 1, 0))
        evidence = restored.memory.store.sources(BINDING, (SourceReference(CID, 1, 0),))[0]
        assert evidence.text == "覚えないで"
        assert evidence.stated_at == snapshot.memory_sources[0].stated_at
        receipt = restored.conversation.store.receipt(BINDING, CID, "r1")
        assert receipt is not None and receipt.fingerprint == "original-fingerprint"
