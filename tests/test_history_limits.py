import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from digital_souls_core import conversations
from digital_souls_core.api import create_app
from digital_souls_core.application import CoreError
from digital_souls_core.contracts import Message

from .support import CALL, TOOL, chunk, completion
from .test_conversations import setup, turn

pytestmark = pytest.mark.it1


@pytest.mark.parametrize("extra", [-1, 0, 1])
@pytest.mark.parametrize("tools", [False, True])
async def test_exact_stream_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: int, tools: bool
) -> None:
    service, provider, _ = setup(tmp_path)
    content = '日本😀"\\\n\t\x00' * 3
    calls: dict[int, Any] = {
        0: {
            "id": "call_a",
            "type": "function",
            "function": {
                "name": "weather",
                "arguments": json.dumps({"city": content}, ensure_ascii=False),
            },
        }
    }
    expected = ["" if tools else content, calls if tools else {}]
    limit = len(json.dumps(expected, ensure_ascii=False).encode("utf-8"))
    monkeypatch.setattr(conversations, "MAX_BYTES", limit + extra)
    if tools:
        provider.chunks = [
            chunk({"tool_calls": [{"index": 0, "id": "call_", "function": {"name": "wea"}}]})
        ]
        provider.chunks += [
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": char}}]})
            for char in calls[0]["function"]["arguments"]
        ]
        provider.chunks += [
            chunk({"tool_calls": [{"index": 0, "id": "a", "function": {"name": "ther"}}]})
        ]
    else:
        provider.chunks = [chunk({"content": char}) for char in content]
    provider.chunks.append(chunk({}, "tool_calls" if tools else "stop"))
    profile = service.inference.characters["synthetic"].config.profile
    if extra < 0:
        with pytest.raises(CoreError) as error:
            await service._stream(profile, {})
        assert (error.value.status, error.value.code) == (413, "history_limit")
    else:
        message, _ = await service._stream(profile, {})
        if tools:
            assert message.tool_calls and message.tool_calls[0].model_dump() == calls[0]
        else:
            assert message.content == content
    assert provider.closed


async def test_tiny_chunks_have_linear_serialization_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, provider, _ = setup(tmp_path)
    count = 10000
    provider.chunks = [chunk({"content": "界"}) for _ in range(count)] + [chunk({}, "stop")]
    original = json.dumps
    processed = 0

    def measured(value: Any, **kwargs: Any) -> str:
        nonlocal processed
        result = original(value, **kwargs)
        processed += len(result)
        return result

    monkeypatch.setattr(json, "dumps", measured)
    message, finish = await service._stream(
        service.inference.characters["synthetic"].config.profile, {}
    )
    assert message.content == "界" * count and finish == "stop"
    assert processed < count * 8  # Work is linear, independent of wall-clock timing.
    assert provider.closed


@pytest.mark.parametrize("mode", ["huge", "unicode", "escaped", "tiny", "tool"])
async def test_byte_overflow_closes_stream_without_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    service, provider, _ = setup(tmp_path)
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overflow: bool
) -> None:
    service, provider, _ = setup(tmp_path)
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


def test_combined_input_message_limit_is_http_413(tmp_path: Path) -> None:
    service, provider, policy = setup(tmp_path)
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


@pytest.mark.parametrize("extra", [-1, 0, 1])
async def test_multiple_tool_structural_byte_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: int
) -> None:
    service, provider, _ = setup(tmp_path)
    calls = {
        i: {
            "id": f"call_{i}",
            "type": "function",
            "function": {"name": "weather", "arguments": "{}"},
        }
        for i in range(12)
    }
    exact = len(json.dumps(["", calls], ensure_ascii=False).encode())
    monkeypatch.setattr(conversations, "MAX_BYTES", exact + extra)
    provider.chunks = [chunk({"tool_calls": [{"index": i, **call}]}) for i, call in calls.items()]
    provider.chunks.append(chunk({}, "tool_calls"))
    profile = service.inference.characters["synthetic"].config.profile
    if extra < 0:
        with pytest.raises(CoreError) as error:
            await service._stream(profile, {})
        assert error.value.code == "history_limit"
    else:
        message, _ = await service._stream(profile, {})
        assert message.tool_calls and len(message.tool_calls) == 12
    assert provider.closed


@pytest.mark.parametrize("count", [255, 256])
@pytest.mark.parametrize("tools", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_input_at_limit_accepts_response(
    tmp_path: Path, count: int, tools: bool, stream: bool
) -> None:
    service, provider, _ = setup(tmp_path)
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
