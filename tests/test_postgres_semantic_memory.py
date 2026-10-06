"""Synthetic PostgreSQL/semantic-search contracts; no model-quality measurement."""

import asyncio
import json
from dataclasses import dataclass, replace

import httpx
import pytest

from digital_souls_core.application import CoreError, Inference
from digital_souls_core.character import AccessScope
from digital_souls_core.contracts import CompletionInput, Message
from digital_souls_core.conversations import Conversations
from digital_souls_core.history import Binding, ConversationControls, SourceReference
from digital_souls_core.local_embedding import LocalEmbedding
from digital_souls_core.local_extractor import LocalExtractor
from digital_souls_core.memory import MemoryContext, MemoryService
from digital_souls_core.memory_ranking import EmbeddingSpace
from digital_souls_core.postgres_db import PostgresDatabase
from digital_souls_core.postgres_memory import PostgresMemory
from digital_souls_core.privacy import PrivacyPolicy
from digital_souls_core.privacy_classifier import LocalClassifier

from . import test_postgres_stores
from .support import FakeProvider, character
from .test_conversations import turn
from .test_local_embedding_memory import profile, response
from .test_memory import selection
from .test_postgres_stores import BINDING, MESSAGES, Stores, revoke, seed
from .test_privacy import assessment, local_profile

pytestmark = pytest.mark.postgres
stores = test_postgres_stores.stores


class SyntheticEmbedding:
    def __init__(self) -> None:
        self.space = EmbeddingSpace("synthetic", "fixture-v1", 2)
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        vectors = []
        for text in texts:
            if text == "beverage" or "tea" in text:
                vectors.append((4.0, 0.0))
            elif "mint" in text:
                vectors.append((1.0, 1.0))
            elif "orthogonal" in text:
                vectors.append((0.0, 1.0))
            else:
                vectors.append((-1.0, 0.0))
        return tuple(vectors)


@dataclass
class Semantic:
    service: MemoryService
    conversation: Conversations
    provider: FakeProvider
    embedding: SyntheticEmbedding


@pytest.fixture
def semantic(stores: Stores) -> Semantic:
    classifier_provider = FakeProvider()
    classifier_provider.response["choices"][0]["message"]["content"] = assessment()
    policy = PrivacyPolicy(
        LocalClassifier(classifier_provider, local_profile(), model_digest="synthetic-digest")
    )
    policy.configure({BINDING: frozenset({"history", "local", "external", "memory"})})
    extractor_provider = FakeProvider()
    extractor_provider.response["choices"][0]["message"]["content"] = selection()
    embedding = SyntheticEmbedding()
    service = MemoryService(
        stores.memory,
        policy,
        LocalExtractor(extractor_provider, local_profile(), model_digest="synthetic-digest"),
        embedding=embedding,
    )
    provider = FakeProvider()
    inference = Inference(
        (character("synthetic"),), provider, privacy=policy, memory_context=MemoryContext(service)
    )
    return Semantic(service, Conversations(inference, stores.history, policy), provider, embedding)


async def test_nonliteral_ranking_preserves_postgres_provenance_and_positive_cosine(
    stores: Stores, semantic: Semantic
) -> None:
    tea = seed(stores, "I like synthetic tea.")
    expected = await semantic.service.extract(BINDING, (tea,))
    mint = await semantic.service.extract(BINDING, (seed(stores, "I grow synthetic mint."),))
    await semantic.service.extract(BINDING, (seed(stores, "Synthetic orthogonal evidence."),))
    await semantic.service.extract(BINDING, (seed(stores, "Synthetic negative evidence."),))
    seed(stores, "Synthetic unselected tea history.")
    assert stores.memory.search(BINDING, "beverage") == ()
    result = await semantic.service.search(BINDING, "beverage")
    assert result == expected + mint
    assert result[0].sources[0].reference == tea and result[0].sources[0].epoch == 0
    assert len(semantic.embedding.calls[0]) == 5
    assert "unselected" not in repr(semantic.embedding.calls)
    # A fresh adapter reopens PostgreSQL without changing identity or provenance.
    semantic.service.store = PostgresMemory(PostgresDatabase(stores.config))
    assert await semantic.service.search(BINDING, "beverage", limit=1) == expected
    assert len(semantic.embedding.calls) == 2


async def test_postgres_equal_relevance_prefers_latest_user_mention(
    stores: Stores, semantic: Semantic
) -> None:
    earlier = seed(stores, "I like synthetic tea in the morning.")
    later = seed(stores, "I like synthetic tea after lunch.")
    mentioned_later = await semantic.service.extract(BINDING, (later,))
    created_later = await semantic.service.extract(BINDING, (earlier,))
    result = await semantic.service.search(BINDING, "beverage")
    assert result == mentioned_later + created_later
    assert result[0].mentioned > result[1].mentioned


@pytest.mark.parametrize(
    "other",
    [
        Binding(AccessScope(subject="other"), "synthetic"),
        Binding(AccessScope(client="other"), "synthetic"),
        Binding(AccessScope(audience="other"), "synthetic"),  # type: ignore[arg-type]
        replace(BINDING, character_id="other"),
    ],
)
async def test_semantic_search_never_embeds_another_postgres_scope(
    stores: Stores, semantic: Semantic, other: Binding
) -> None:
    await semantic.service.extract(BINDING, (seed(stores),))
    semantic.service.policy.configure(
        {BINDING: frozenset({"memory", "local"}), other: frozenset({"memory", "local"})}
    )
    assert await semantic.service.search(other, "beverage") == ()
    assert semantic.embedding.calls == []


@pytest.mark.parametrize(
    "excluded", ["private", "delete", "specified", "private_turn", "unselected"]
)
async def test_official_sdk_receives_only_authorized_postgres_memories(
    stores: Stores, semantic: Semantic, monkeypatch: pytest.MonkeyPatch, excluded: str
) -> None:
    wanted = await semantic.service.extract(BINDING, (seed(stores),))
    if excluded in {"specified", "private_turn"}:
        conversation = stores.history.create(BINDING).conversation_id
        if excluded == "private_turn":
            stores.history.controls(
                BINDING, conversation, ConversationControls(expected_revision=0, private_mode=True)
            )
        revision = 1 if excluded == "private_turn" else 0
        stores.history.append(
            BINDING,
            conversation,
            "excluded",
            "synthetic-excluded",
            revision,
            (Message(role="user", content="Synthetic excluded tea."), MESSAGES[-1]),
            "stop",
            memory_excluded_indices=(0,) if excluded == "specified" else (),
        )
        ref = SourceReference(conversation, revision + 1, 0)
        if excluded == "private_turn":
            stores.history.controls(
                BINDING, conversation, ConversationControls(expected_revision=2, private_mode=False)
            )
        with pytest.raises(CoreError):
            await semantic.service.extract(BINDING, (ref,))
    else:
        ref = seed(stores, "Synthetic excluded tea.")
        if excluded != "unselected":
            await semantic.service.extract(BINDING, (ref,))
            revoke(stores.history, ref, excluded)
    calls: list[list[str]] = []

    async def send(transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:18181/v1/embeddings"
        assert request.headers["authorization"] == "Bearer local-no-auth"
        body = json.loads(request.content)
        assert body["model"] == "synthetic-embedding" and body["encoding_format"] == "float"
        calls.append(body["input"])
        return response(body["input"])

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    semantic.service.embedding = LocalEmbedding(profile())
    assert await semantic.service.search(BINDING, "beverage") == wanted
    assert calls == [["beverage", wanted[0].text]]
    stores.history.delete(BINDING, wanted[0].sources[0].reference.conversation_id)
    assert await semantic.service.search(BINDING, "beverage") == ()
    assert len(calls) == 1


@pytest.mark.parametrize("action", ["private", "delete"])
@pytest.mark.parametrize("stream", [False, True])
async def test_revocation_during_embedding_allows_memoryless_conversation(
    stores: Stores, semantic: Semantic, monkeypatch: pytest.MonkeyPatch, action: str, stream: bool
) -> None:
    ref = seed(stores)
    await semantic.service.extract(BINDING, (ref,))
    target = semantic.conversation.create("synthetic").conversation_id
    entered, release = asyncio.Event(), asyncio.Event()
    original = semantic.embedding.embed

    async def blocked(texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        result = await original(texts)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(semantic.embedding, "embed", blocked)
    task = asyncio.create_task(
        semantic.conversation.complete(
            "synthetic",
            target,
            turn(messages=[{"role": "user", "content": "beverage"}], stream=stream),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 3)
        revoke(stores.history, ref, action)
    finally:
        release.set()
    receipt = await task
    assert receipt.revision == 1 and receipt.message.content == "こんにちは"
    assert len(semantic.provider.calls) == 1
    assert semantic.provider.calls[0][1]["messages"] == [
        {
            "role": "system",
            "content": semantic.conversation.inference.characters["synthetic"].system_prompt,
        },
        {"role": "user", "content": "beverage"},
    ]
    snapshot = stores.history.read(BINDING, target)
    assert snapshot.revision == 1
    assert snapshot.messages == (Message(role="user", content="beverage"), receipt.message)
    assert len(semantic.embedding.calls) == 1


@pytest.mark.parametrize("change", ["store", "generation", "space"])
async def test_postgres_search_rechecks_storage_and_embedding_generation_after_await(
    stores: Stores, semantic: Semantic, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    await semantic.service.extract(BINDING, (seed(stores),))
    entered, release = asyncio.Event(), asyncio.Event()
    original = semantic.embedding.embed

    async def blocked(texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        result = await original(texts)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(semantic.embedding, "embed", blocked)
    task = asyncio.create_task(semantic.service.search(BINDING, "beverage"))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == "store":
            semantic.service.store = PostgresMemory(PostgresDatabase(stores.config))
        elif change == "generation":
            semantic.service.embedding = semantic.embedding
        else:
            semantic.embedding.space = replace(semantic.embedding.space, revision="fixture-v2")
    finally:
        release.set()
    with pytest.raises(CoreError) as caught:
        await task
    assert caught.value.code == "memory_denied"


@pytest.mark.parametrize("action", ["private", "delete"])
@pytest.mark.parametrize("stream", [False, True])
async def test_revocation_after_context_assembly_prevents_model_dispatch(
    stores: Stores, semantic: Semantic, monkeypatch: pytest.MonkeyPatch, action: str, stream: bool
) -> None:
    ref = seed(stores)
    await semantic.service.extract(BINDING, (ref,))
    classifier = semantic.service.policy.classifier
    assert classifier is not None
    original = classifier.safe
    context_checked = False

    async def revoke_after_classification(value: object, version: str) -> bool:
        nonlocal context_checked
        allowed = await original(value, version)
        if isinstance(value, dict) and "retrieved_memory_data" in json.dumps(value):
            context_checked = True
            revoke(stores.history, ref, action)
        return allowed

    monkeypatch.setattr(classifier, "safe", revoke_after_classification)
    target = semantic.conversation.create("synthetic").conversation_id
    with pytest.raises(CoreError):
        await semantic.conversation.complete(
            "synthetic",
            target,
            turn(messages=[{"role": "user", "content": "beverage"}], stream=stream),
        )
    assert context_checked and len(semantic.embedding.calls) == 1
    assert semantic.provider.calls == []
    assert stores.history.read(BINDING, target).revision == 0


@pytest.mark.parametrize("empty", ["unselected", "nonpositive"])
async def test_empty_semantic_result_retains_dispatch_generation_guard(
    stores: Stores, semantic: Semantic, empty: str
) -> None:
    ref = seed(stores, "Synthetic negative evidence.")
    if empty == "nonpositive":
        await semantic.service.extract(BINDING, (ref,))
    request = CompletionInput(messages=[Message(role="user", content="beverage")])
    prepared = await semantic.conversation.inference.prepare(
        "synthetic", request, alias=False, conversation_id=ref.conversation_id
    )
    assert "memory_ref" not in json.dumps(prepared.payload)
    assert len(semantic.embedding.calls) == (1 if empty == "nonpositive" else 0)
    semantic.service.embedding = semantic.embedding
    with pytest.raises(CoreError) as caught:
        semantic.conversation.inference.check(prepared)
    assert caught.value.code == "context_revoked"
    assert semantic.provider.calls == []


@pytest.mark.parametrize("mismatch", ["model", "dimensions"])
async def test_sdk_model_and_dimension_mismatch_never_return_postgres_memory(
    stores: Stores, semantic: Semantic, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    await semantic.service.extract(BINDING, (seed(stores),))
    calls = 0

    async def send(transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = response(json.loads(request.content)["input"]).json()
        if mismatch == "model":
            body["model"] = "synthetic-other-model"
        else:
            body["data"][0]["embedding"] = [1.0, 0.0, 0.0]
        return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    semantic.service.embedding = LocalEmbedding(profile())
    with pytest.raises(CoreError) as caught:
        await semantic.service.search(BINDING, "beverage")
    assert caught.value.code == "memory_embedding_failed"
    assert calls == 1
    assert semantic.provider.calls == []


async def test_sdk_profile_change_during_http_await_invalidates_postgres_search(
    stores: Stores, semantic: Semantic, monkeypatch: pytest.MonkeyPatch
) -> None:
    await semantic.service.extract(BINDING, (seed(stores),))
    encoder = LocalEmbedding(profile())
    semantic.service.embedding = encoder
    entered, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []

    async def send(transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        entered.set()
        await release.wait()
        return response(json.loads(request.content)["input"])

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    task = asyncio.create_task(semantic.service.search(BINDING, "beverage"))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        encoder._profile = encoder._profile.model_copy(
            update={"api_base": "http://127.0.0.1:18182/v1"}
        )
    finally:
        release.set()
    with pytest.raises(CoreError) as caught:
        await task
    assert caught.value.code == "memory_embedding_failed"
    assert calls == ["http://127.0.0.1:18181/v1/embeddings"]
