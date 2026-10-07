import json

import pytest
from fastapi.testclient import TestClient

from digital_souls_core import conversations
from digital_souls_core.api import create_app
from digital_souls_core.application import CoreError
from digital_souls_core.contracts import Message

from . import test_postgres_stores
from .conversation_support import turn
from .support import CALL, TOOL, chunk, completion
from .test_postgres_conversations import setup
from .test_postgres_stores import Stores

pytestmark = pytest.mark.postgres
stores = test_postgres_stores.stores


@pytest.mark.parametrize("mode", ["huge", "unicode", "escaped", "tiny", "tool"])
async def test_byte_overflow_closes_stream_without_history(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    service, provider, _ = setup(stores)
    cid = service.create("synthetic").conversation_id
    monkeypatch.setattr(conversations, "MAX_BYTES", 1024)
    if mode == "tiny":
        provider.chunks = [chunk({"content": "x"}) for _ in range(1100)]
    elif mode == "tool":
        provider.chunks = [
            chunk({"tool_calls": [{"index": 0, "id": "call_x", "function": {"name": "weather"}}]})
        ]
        provider.chunks += [
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": "界"}}]})
            for _ in range(400)
        ]
    else:
        content = {"huge": "x" * 100000, "unicode": "界" * 400, "escaped": "\x00" * 200}[mode]
        provider.chunks = [chunk({"content": content})]
    provider.chunks.append(chunk({}, "tool_calls" if mode == "tool" else "stop"))
    with pytest.raises(CoreError) as error:
        await service.complete(
            "synthetic", cid, turn(stream=True, **({"tools": [TOOL]} if mode == "tool" else {}))
        )
    assert (error.value.status, error.value.code) == (413, "history_limit")
    assert provider.closed
    assert service.read("synthetic", cid).messages == ()
    assert service.store.receipt(service.binding("synthetic"), cid, "r1") is None


@pytest.mark.parametrize("overflow", [False, True])
async def test_final_stored_history_exact_byte_limit(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, overflow: bool
) -> None:
    service, provider, _ = setup(stores)
    cid = service.create("synthetic").conversation_id
    content = "界" * 100
    expected = [
        turn().messages[0].model_dump(),
        Message(role="assistant", content=content).model_dump(),
    ]
    monkeypatch.setattr(
        conversations,
        "MAX_BYTES",
        len(json.dumps(expected, ensure_ascii=False).encode()) - int(overflow),
    )
    provider.chunks = [chunk({"content": char}) for char in content] + [chunk({}, "stop")]
    if overflow:
        with pytest.raises(CoreError) as error:
            await service.complete("synthetic", cid, turn(stream=True))
        assert error.value.code == "history_limit"
        assert service.read("synthetic", cid).messages == ()
    else:
        assert (
            await service.complete("synthetic", cid, turn(stream=True))
        ).message.content == content


def test_combined_input_message_limit_is_http_413(stores: Stores) -> None:
    service, provider, policy = setup(stores)
    cid = service.create("synthetic").conversation_id
    service.store.append(
        service.binding("synthetic"),
        cid,
        "seed",
        "synthetic-fingerprint",
        0,
        tuple(Message(role="user", content="Synthetic") for _ in range(256)),
        "stop",
    )
    http = TestClient(
        create_app(service.inference, history_store=service.store, history_policy=policy),
        base_url="http://127.0.0.1",
    )
    response = http.post(
        f"/v1/characters/synthetic/conversations/{cid}/completions",
        json=turn(expected_revision=1).model_dump(),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "history_limit"
    assert provider.calls == []
    assert service.read("synthetic", cid).revision == 1


@pytest.mark.parametrize("count", [255, 256])
@pytest.mark.parametrize("tools", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_input_at_limit_accepts_response(
    stores: Stores, count: int, tools: bool, stream: bool
) -> None:
    service, provider, _ = setup(stores)
    cid = service.create("synthetic").conversation_id
    messages = tuple(Message(role="user", content="Synthetic") for _ in range(count - 2))
    service.store.append(
        service.binding("synthetic"),
        cid,
        "seed",
        "synthetic-fingerprint",
        0,
        (*messages, Message(role="assistant", content="Synthetic")),
        "stop",
    )
    provider.response = completion(tool=tools)
    if tools:
        provider.chunks = [chunk({"tool_calls": [{"index": 0, **CALL}]}), chunk({}, "tool_calls")]
    receipt = await service.complete(
        "synthetic",
        cid,
        turn(expected_revision=1, stream=stream, **({"tools": [TOOL]} if tools else {})),
    )
    assert receipt.revision == 2
    assert len(service.read("synthetic", cid).messages) == count + 1
