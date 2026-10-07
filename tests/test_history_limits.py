import json
from typing import Any, cast

import pytest

from digital_souls_core import conversations
from digital_souls_core.application import CoreError, Inference
from digital_souls_core.conversations import Conversations
from digital_souls_core.history import HistoryStore

from .support import FakeProvider, character, chunk

pytestmark = pytest.mark.it1


@pytest.mark.parametrize("extra", [-1, 0, 1])
@pytest.mark.parametrize("tools", [False, True])
async def test_exact_stream_boundary(
    monkeypatch: pytest.MonkeyPatch, extra: int, tools: bool
) -> None:
    provider = FakeProvider()
    service = Conversations(
        Inference((character("synthetic"),), provider), cast(HistoryStore, None)
    )
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


async def test_tiny_chunks_have_linear_serialization_work(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    service = Conversations(
        Inference((character("synthetic"),), provider), cast(HistoryStore, None)
    )
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


@pytest.mark.parametrize("extra", [-1, 0, 1])
async def test_multiple_tool_structural_byte_boundary(
    monkeypatch: pytest.MonkeyPatch, extra: int
) -> None:
    provider = FakeProvider()
    service = Conversations(
        Inference((character("synthetic"),), provider), cast(HistoryStore, None)
    )
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
