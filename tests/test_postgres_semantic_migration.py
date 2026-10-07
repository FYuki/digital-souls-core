"""Semantic memory contracts with PostgreSQL and deterministic in-process vectors."""

import asyncio
import json
from dataclasses import replace

import pytest

from digital_souls_core.application import CoreError
from digital_souls_core.contracts import CompletionInput, Message
from digital_souls_core.history import ConversationControls
from digital_souls_core.memory_ranking import EmbeddingSpace
from digital_souls_core.privacy_classifier import LocalClassifier

from . import postgres_memory_support
from .postgres_memory_support import (
    Stores,
    assert_memoryless_turn,
    reopen,
    selection,
    setup,
    source,
)
from .support import FakeProvider
from .test_conversations import turn
from .test_privacy import BINDING

stores = postgres_memory_support.stores
pytestmark = pytest.mark.postgres


class SyntheticEmbedding:
    def __init__(self) -> None:
        self.space = EmbeddingSpace("synthetic", "fixture-v1", 2)
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        return tuple((1.0, 0.0) if "tea" in t or "beverage" in t else (0.0, 1.0) for t in texts)


async def test_opt_in_synonym_ranking_preserves_memory_and_source_provenance(
    stores: Stores,
) -> None:
    service, conversation, _ = setup(stores)
    tea = await source(conversation)
    expected = await service.extract(BINDING, (tea,))
    await service.extract(BINDING, (await source(conversation, "I grow synthetic mint."),))
    await source(conversation, "Unselected synthetic tea history.")
    versions = service._versions()
    assert await service.search(BINDING, "beverage") == ()
    encoder = SyntheticEmbedding()
    service.embedding = encoder
    assert await service.search(BINDING, "beverage", limit=1) == expected
    assert service._versions() == versions
    assert len(encoder.calls) == 1 and len(encoder.calls[0]) == 3
    assert "Unselected" not in repr(encoder.calls)
    conversation.controls(
        "synthetic", tea.conversation_id, ConversationControls(expected_revision=1, archived=True)
    )
    assert await service.search(BINDING, "beverage") == expected
    service.store = reopen(stores)
    assert await service.search(BINDING, "beverage") == expected
    assert len(encoder.calls) == 3  # Every call recomputes; reopening does not introduce an index.


async def test_semantic_search_returns_at_most_poc_max_retrieved(stores: Stores) -> None:
    service, conversation, _ = setup(stores)
    for index in range(7):
        await service.extract(
            BINDING, (await source(conversation, f"I like synthetic tea number {index}."),)
        )
    service.embedding = SyntheticEmbedding()
    assert len(await service.search(BINDING, "beverage")) == 5
    assert len(await service.search(BINDING, "beverage", limit=16)) == 5
    assert len(await service.search(BINDING, "beverage", limit=2)) == 2


@pytest.mark.parametrize("action", ["private", "delete"])
async def test_revocation_and_rebuild_never_reembed_withdrawn_source(
    stores: Stores, action: str
) -> None:
    service, conversation, provider = setup(stores)
    tea = await source(conversation)
    mint = await source(conversation, "I grow synthetic mint.")
    provider.response["choices"][0]["message"]["content"] = selection([0, 1])
    old = await service.extract(BINDING, (tea, mint))
    encoder = SyntheticEmbedding()
    service.embedding = encoder
    assert await service.search(BINDING, "beverage") == old
    if action == "delete":
        conversation.delete("synthetic", tea.conversation_id)
    else:
        for revision, private in [(1, True), (2, False)]:
            conversation.controls(
                "synthetic",
                tea.conversation_id,
                ConversationControls(expected_revision=revision, private_mode=private),
            )
    encoder.calls.clear()
    assert await service.search(BINDING, "beverage") == ()
    assert encoder.calls == []
    provider.response["choices"][0]["message"]["content"] = selection()
    assert await service.rebuild(BINDING) == 1
    result = await service.search(BINDING, "plant")
    assert result[0].sources[0].reference == mint and result[0].memory_id != old[0].memory_id
    assert "tea" not in repr(encoder.calls)


@pytest.mark.parametrize("excluded", ["specified", "private_turn"])
async def test_ineligible_history_is_never_promoted_by_semantic_search(
    stores: Stores, excluded: str
) -> None:
    service, conversation, _ = setup(stores)
    cid = conversation.create("synthetic").conversation_id
    if excluded == "private_turn":
        conversation.controls(
            "synthetic", cid, ConversationControls(expected_revision=0, private_mode=True)
        )
    await conversation.complete(
        "synthetic",
        cid,
        turn(
            expected_revision=1 if excluded == "private_turn" else 0,
            messages=[{"role": "user", "content": "I like synthetic tea."}],
            memory_excluded_indices=[0] if excluded == "specified" else [],
        ),
    )
    if excluded == "private_turn":
        conversation.controls(
            "synthetic", cid, ConversationControls(expected_revision=2, private_mode=False)
        )
    snapshot = conversation.read("synthetic", cid)
    assert not snapshot.memory_sources[0].eligible
    with pytest.raises(CoreError):
        await service.extract(BINDING, (snapshot.memory_sources[0].reference,))
    encoder = SyntheticEmbedding()
    service.embedding = encoder
    assert await service.search(BINDING, "beverage") == () and encoder.calls == []


@pytest.mark.parametrize(
    "change,stage",
    [
        (change, stage)
        for stage in ("candidate_authorization", "embedding")
        for change in (
            "private",
            "delete",
            "policy",
            "classifier",
            "embedding",
            "space",
            "mutated_space",
            "scope",
            "store",
        )
        if not (stage == "embedding" and change in {"store", "embedding", "space"})
    ],
)
async def test_changes_during_await_fail_closed(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, change: str, stage: str
) -> None:
    service, conversation, _ = setup(stores)
    ref = await source(conversation)
    await service.extract(BINDING, (ref,))
    encoder = SyntheticEmbedding()
    service.embedding = encoder
    entered, release = asyncio.Event(), asyncio.Event()
    allowed = True
    original_embed = encoder.embed
    classifier = service.policy.classifier
    assert classifier is not None
    original_classify = classifier.safe

    async def classify(value: object, version: str) -> bool:
        if isinstance(value, list):
            entered.set()
            await release.wait()
        return await original_classify(value, version)

    async def embed(texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        result = await original_embed(texts)
        entered.set()
        await release.wait()
        return result

    if stage == "candidate_authorization":
        monkeypatch.setattr(classifier, "safe", classify)
    else:
        monkeypatch.setattr(encoder, "embed", embed)
    task = asyncio.create_task(service.search(BINDING, "beverage", authorized=lambda: allowed))
    await entered.wait()
    if change == "private":
        conversation.controls(
            "synthetic",
            ref.conversation_id,
            ConversationControls(expected_revision=1, private_mode=True),
        )
    elif change == "delete":
        conversation.delete("synthetic", ref.conversation_id)
    elif change == "policy":
        service.policy.configure({})
    elif change == "classifier":
        service.policy.classifier = service.policy.classifier
    elif change == "embedding":
        service.embedding = encoder  # Same-instance reassignment still changes generation.
    elif change == "space":
        encoder.space = replace(encoder.space, revision="fixture-v2")
    elif change == "mutated_space":
        object.__setattr__(encoder.space, "revision", "fixture-v2")
    elif change == "scope":
        allowed = False
    else:
        service.store = reopen(stores)
    release.set()
    with pytest.raises(CoreError) as caught:
        await task
    assert caught.value.code != "memory_query_unavailable"
    assert len(encoder.calls) == (1 if stage == "embedding" else 0)


@pytest.mark.parametrize("failure", ["error", "timeout", "cancel", "bad_vectors"])
async def test_embedding_failure_is_bounded_content_free_and_never_optional(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    service, conversation, _ = setup(stores)
    ref = await source(conversation)
    await service.extract(BINDING, (ref,))
    encoder = SyntheticEmbedding()
    service.embedding = encoder
    entered = asyncio.Event()
    real_timeout = asyncio.timeout

    def immediate_timeout(delay: float) -> asyncio.Timeout:
        assert delay == 15
        return real_timeout(0)

    async def fail(texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        entered.set()
        if failure == "error":
            raise RuntimeError("SYNTHETIC_CONTENT_MUST_NOT_LEAK")
        if failure == "bad_vectors":
            return ()
        await asyncio.Event().wait()
        return ()

    monkeypatch.setattr(encoder, "embed", fail)
    if failure == "timeout":
        monkeypatch.setattr(asyncio, "timeout", immediate_timeout)
        # Other local classifiers also use asyncio.timeout; skip only their fake timing.
        classifier = service.policy.classifier
        assert classifier is not None

        async def safe(value: object, version: str) -> bool:
            return True

        monkeypatch.setattr(classifier, "safe", safe)
    task = asyncio.create_task(service.search(BINDING, "beverage"))
    await entered.wait()
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(CoreError) as caught:
            await task
        assert caught.value.code == "memory_embedding_failed"
        assert "SYNTHETIC_CONTENT" not in str(caught.value)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure", ["error", "timeout", "bad_vectors", "metadata"])
async def test_embedding_failure_allows_memoryless_conversation(
    stores: Stores,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
    stream: bool,
) -> None:
    service, conversation, _ = setup(stores)
    ref = await source(conversation, "SYNTHETIC_EVIDENCE_MARKER tea")
    await service.extract(BINDING, (ref,))
    encoder = SyntheticEmbedding()
    service.embedding = encoder

    async def fail(texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if failure == "error":
            raise RuntimeError("SYNTHETIC_ERROR_MARKER " + " ".join(texts))
        if failure == "bad_vectors":
            return ()
        await asyncio.Event().wait()
        return ()

    monkeypatch.setattr(encoder, "embed", fail)
    if failure == "timeout":
        real_timeout = asyncio.timeout

        def immediate_embedding_timeout(delay: float | None) -> asyncio.Timeout:
            return real_timeout(0 if delay == 15 else delay)

        monkeypatch.setattr(asyncio, "timeout", immediate_embedding_timeout)
    elif failure == "metadata":

        class BrokenEmbedding:
            @property
            def space(self) -> EmbeddingSpace:
                raise RuntimeError("SYNTHETIC_ERROR_MARKER")

            async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
                raise AssertionError("must not embed invalid metadata")

        service.embedding = BrokenEmbedding()
    caplog.set_level("DEBUG")
    caplog.clear()
    await assert_memoryless_turn(conversation, "SYNTHETIC_QUERY_MARKER beverage", stream)
    for marker in ("synthetic_query_marker", "synthetic_evidence_marker", "synthetic_error_marker"):
        assert marker not in caplog.text.casefold()


async def test_conversation_cancel_during_embedding_propagates_without_append(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, conversation, _ = setup(stores)
    await service.extract(BINDING, (await source(conversation),))
    encoder = SyntheticEmbedding()
    service.embedding = encoder
    entered, closed = asyncio.Event(), asyncio.Event()

    async def wait(texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
        return ()

    monkeypatch.setattr(encoder, "embed", wait)
    provider = conversation.inference.provider
    assert isinstance(provider, FakeProvider)
    provider.calls.clear()
    cid = conversation.create("synthetic").conversation_id
    body = turn(messages=[{"role": "user", "content": "beverage"}])
    task = asyncio.create_task(conversation.complete("synthetic", cid, body))
    try:
        await asyncio.wait_for(entered.wait(), 3)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert provider.calls == []
    assert conversation.read("synthetic", cid).revision == 0
    assert conversation.store.receipt(BINDING, cid, body.request_id) is None


@pytest.mark.parametrize(
    "query,limit", [("", 1), ("x" * 257, 1), ("tea", 0), ("tea", 17), ("tea", True)]
)
async def test_invalid_search_rejected_before_classifier_or_embedding(
    stores: Stores, query: str, limit: int
) -> None:
    service, _, _ = setup(stores)
    encoder = SyntheticEmbedding()
    service.embedding = encoder
    classifier = service.policy.classifier
    assert isinstance(classifier, LocalClassifier) and isinstance(
        classifier._provider, FakeProvider
    )
    with pytest.raises(CoreError) as caught:
        await service.search(BINDING, query, limit)
    assert caught.value.code == "memory_query_invalid"
    assert encoder.calls == [] and classifier._provider.calls == []


@pytest.mark.parametrize("denial", ["query", "candidates", "permission", "budget", "count"])
async def test_denied_content_and_oversize_scope_never_reach_embedding(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, denial: str
) -> None:
    service, conversation, _ = setup(stores)
    memories = await service.extract(BINDING, (await source(conversation),))
    encoder = SyntheticEmbedding()
    service.embedding = encoder
    classifier = service.policy.classifier
    assert classifier is not None
    original = classifier.safe

    async def deny(value: object, version: str) -> bool:
        if (denial == "query" and isinstance(value, str)) or (
            denial == "candidates" and isinstance(value, list)
        ):
            return False
        return await original(value, version)

    monkeypatch.setattr(classifier, "safe", deny)
    if denial == "permission":
        service.policy.configure({BINDING: frozenset({"history", "local"})})
    elif denial == "budget":
        monkeypatch.setattr(
            service.store, "candidates", lambda _: (replace(memories[0], text="茶" * 90000),)
        )
    elif denial == "count":
        monkeypatch.setattr(service.store, "candidates", lambda _: memories * 1001)
    with pytest.raises(CoreError):
        await service.search(BINDING, "beverage")
    assert encoder.calls == []


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("change", ["private", "embedding", "space"])
async def test_semantic_context_retains_dispatch_guard_and_stateless_compatibility(
    stores: Stores, empty: bool, change: str
) -> None:
    service, conversation, _ = setup(stores)
    ref = await source(conversation)
    if not empty:
        await service.extract(BINDING, (ref,))
    encoder = SyntheticEmbedding()
    service.embedding = encoder
    inference = conversation.inference
    request = CompletionInput(messages=[Message(role="user", content="beverage")])
    await inference.prepare("synthetic", request, alias=False)
    assert encoder.calls == []
    prepared = await inference.prepare(
        "synthetic", request, alias=False, conversation_id=ref.conversation_id
    )
    if not empty:
        data = json.loads(prepared.payload["messages"][1]["content"].split("\n", 1)[1])
        assert data[0]["user_evidence"] == ["I like synthetic tea."]
    if change == "embedding":
        service.embedding = encoder
    elif change == "space":
        encoder.space = replace(encoder.space, model="synthetic-new")
    else:
        conversation.controls(
            "synthetic",
            ref.conversation_id,
            ConversationControls(expected_revision=1, private_mode=True),
        )
    if not empty or change != "private":
        with pytest.raises(CoreError):
            inference.check(prepared)


async def test_broken_embedding_metadata_is_content_free(stores: Stores) -> None:
    service, _, _ = setup(stores)

    class BrokenEmbedding:
        @property
        def space(self) -> EmbeddingSpace:
            raise RuntimeError("SYNTHETIC_PRIVATE_METADATA")

        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            raise AssertionError("must not embed")

    service.embedding = BrokenEmbedding()
    with pytest.raises(CoreError) as caught:
        await service.search(BINDING, "beverage")
    assert caught.value.code == "memory_embedding_failed"
    assert "SYNTHETIC_PRIVATE_METADATA" not in str(caught.value)


async def test_nonselected_source_revoked_during_result_authorization_rejects_search(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, conversation, _ = setup(stores)
    tea = await source(conversation)
    mint = await source(conversation, "I grow synthetic mint.")
    await service.extract(BINDING, (tea,))
    await service.extract(BINDING, (mint,))
    service.embedding = SyntheticEmbedding()
    classifier = service.policy.classifier
    assert classifier is not None
    original = classifier.safe

    async def revoke(value: object, version: str) -> bool:
        allowed = await original(value, version)
        # Two candidates were embedded, but only tea is in the selected result.
        if isinstance(value, list) and len(value) == 1:
            conversation.delete("synthetic", mint.conversation_id)
        return allowed

    monkeypatch.setattr(classifier, "safe", revoke)
    with pytest.raises(CoreError):
        await service.search(BINDING, "beverage", limit=1)
