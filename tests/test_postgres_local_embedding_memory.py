import asyncio
import json

import httpx
import pytest

from digital_souls_core.application import CoreError
from digital_souls_core.history import ConversationControls
from digital_souls_core.local_embedding import LocalEmbedding

from . import test_postgres_stores
from .postgres_memory_support import setup, source
from .privacy_support import BINDING
from .test_local_embedding_memory import profile, response
from .test_postgres_stores import Stores

pytestmark = pytest.mark.postgres
stores = test_postgres_stores.stores


async def test_sdk_receives_only_current_authorized_evidence(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, conversation, _ = setup(stores)
    wanted = await service.extract(BINDING, (await source(conversation),))
    revoked_ref = await source(conversation, "Synthetic revoked tea.")
    await service.extract(BINDING, (revoked_ref,))
    await source(conversation, "Synthetic unselected tea.")
    conversation.controls(
        "synthetic",
        revoked_ref.conversation_id,
        ConversationControls(expected_revision=1, private_mode=True),
    )
    calls: list[list[str]] = []

    async def send(transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        calls.append(texts)
        return response(texts)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    service.embedding = LocalEmbedding(profile())
    assert await service.search(BINDING, "beverage") == wanted
    assert calls == [["beverage", wanted[0].text]]
    conversation.delete("synthetic", wanted[0].sources[0].reference.conversation_id)
    assert await service.search(BINDING, "beverage") == ()
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["delete", "endpoint", "model", "dimensions"])
async def test_sdk_await_rechecks_sources_and_deployment_configuration(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    service, conversation, _ = setup(stores)
    ref = await source(conversation)
    await service.extract(BINDING, (ref,))
    encoder = LocalEmbedding(profile())
    service.embedding = encoder
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        entered.set()
        await release.wait()
        return response(texts)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    task = asyncio.create_task(service.search(BINDING, "beverage"))
    await entered.wait()
    if change == "delete":
        conversation.delete("synthetic", ref.conversation_id)
    elif change == "endpoint":
        encoder._profile = encoder._profile.model_copy(
            update={"api_base": "http://127.0.0.1:18182/v1"}
        )
    elif change == "model":
        encoder._profile = encoder._profile.model_copy(update={"model": "synthetic-other"})
    else:
        encoder._profile = encoder._profile.model_copy(update={"dimensions": 3})
    release.set()
    with pytest.raises(CoreError):
        await task


async def test_endpoint_change_during_candidate_authorization_never_dispatches(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, conversation, _ = setup(stores)
    await service.extract(BINDING, (await source(conversation),))
    encoder = LocalEmbedding(profile())
    service.embedding = encoder
    classifier = service.policy.classifier
    assert classifier is not None
    original = classifier.safe

    async def classify(value: object, version: str) -> bool:
        result = await original(value, version)
        if isinstance(value, list):
            encoder._profile = encoder._profile.model_copy(
                update={"api_base": "http://127.0.0.1:18182/v1"}
            )
        return result

    async def forbidden(
        transport: httpx.AsyncHTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        pytest.fail("Stale configuration must not dispatch to SDK")

    monkeypatch.setattr(classifier, "safe", classify)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    with pytest.raises(CoreError):
        await service.search(BINDING, "beverage")
