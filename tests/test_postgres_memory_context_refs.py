"""Synthetic UUID collisions must not alter content screening or identity guards."""

import json
from uuid import UUID

import pytest

from digital_souls_core import postgres_history, postgres_memory
from digital_souls_core.application import CoreError
from digital_souls_core.contracts import CompletionInput, Message
from digital_souls_core.privacy_scan import scan

from . import postgres_memory_support
from .postgres_memory_support import Stores, selection, setup, source
from .test_privacy import BINDING

stores = postgres_memory_support.stores
pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("local", [False, True])
@pytest.mark.parametrize("identity", ["conversation", "memory"])
@pytest.mark.parametrize(
    "synthetic_id",
    ["aaaaaaaa-aaaa-4aaa-8aaa-a09012345678", "aaaaaaaa-aaaa-4aaa-a000-000000000000"],
)
async def test_generated_identifier_collision_preserves_content_policy_and_guard(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, local: bool, identity: str, synthetic_id: str
) -> None:
    # A valid v4 UUID can contain a phone-shaped or Luhn-valid decimal run.
    collision = UUID(synthetic_id)
    assert collision.version == 4 and scan(synthetic_id).secret
    adapter = postgres_history if identity == "conversation" else postgres_memory
    monkeypatch.setattr(adapter, "uuid4", lambda: collision)
    service, conversation, _ = setup(stores, local=local)
    ref = await source(conversation)
    memory = (await service.extract(BINDING, (ref,)))[0]
    assert (ref.conversation_id if identity == "conversation" else memory.memory_id) == synthetic_id
    # Public retrieval still returns actual storage IDs and full source identity.
    assert (await service.search(BINDING, "tea"))[0] == memory
    assert (
        conversation.read("synthetic", ref.conversation_id).conversation_id == ref.conversation_id
    )
    inference = conversation.inference
    prepared = await inference.prepare(
        "synthetic",
        CompletionInput(messages=[Message(role="user", content="tea")]),
        alias=False,
        conversation_id=ref.conversation_id,
    )
    encoded = json.dumps(prepared.payload)
    assert memory.memory_id not in encoded and ref.conversation_id not in encoded
    data = json.loads(prepared.payload["messages"][1]["content"].split("\n", 1)[1])
    assert data[0]["memory_ref"] == "memory-1"
    assert data[0]["sources"][0]["conversation_ref"] == "conversation-1"
    assert data[0]["user_evidence"] == ["I like synthetic tea."]
    # Identical characters in user content remain denied: no UUID whitelist.
    with pytest.raises(CoreError) as denied:
        await inference.prepare(
            "synthetic",
            CompletionInput(messages=[Message(role="user", content=synthetic_id)]),
            alias=False,
            conversation_id=ref.conversation_id,
        )
    assert denied.value.code == "privacy_denied"
    conversation.delete("synthetic", ref.conversation_id)
    with pytest.raises(CoreError):
        inference.check(prepared)
    assert await service.search(BINDING, "tea") == ()


async def test_context_references_preserve_shared_source_relationships(stores: Stores) -> None:
    service, conversation, provider = setup(stores)
    a = await source(conversation, "I like synthetic tea alpha.")
    b = await source(conversation, "I like synthetic tea beta.")
    await service.extract(BINDING, (a,))
    provider.response["choices"][0]["message"]["content"] = selection([0, 1])
    await service.extract(BINDING, (a, b))
    public = await service.search(BINDING, "tea")
    prepared = await conversation.inference.prepare(
        "synthetic",
        CompletionInput(messages=[Message(role="user", content="tea")]),
        alias=False,
        conversation_id=a.conversation_id,
    )
    data = json.loads(prepared.payload["messages"][1]["content"].split("\n", 1)[1])
    assert [m["memory_ref"] for m in data] == ["memory-1", "memory-2"]
    references: dict[str, str] = {}
    for actual, framed in zip(public, data, strict=True):
        assert framed["user_evidence"] == json.loads(actual.text)
        for original, sent in zip(actual.sources, framed["sources"], strict=True):
            cid = original.reference.conversation_id
            prior = references.setdefault(cid, sent["conversation_ref"])
            assert sent["conversation_ref"] == prior
            assert sent["turn_revision"] == original.reference.turn_revision
            assert sent["message_index"] == original.reference.message_index
            assert sent["epoch"] == original.epoch
    assert set(references) == {a.conversation_id, b.conversation_id}
    assert len(set(references.values())) == 2
