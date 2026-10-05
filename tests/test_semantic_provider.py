"""評価 harness のモデル送信境界を、実モデルを使わず検証する。"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from digital_souls_core.application import CoreError
from evals.semantic import runtime
from evals.semantic.models import Case, LocalProfile
from evals.semantic.provider import call_api
from evals.semantic.runtime import Backend, evaluate_case
from experiments.pgvector_memory.store import PgvectorMemoryStore, SearchHit, WorkItem

pytestmark = pytest.mark.ut


def case_data() -> dict[str, Any]:
    return {
        "id": "unit",
        "category": "unit",
        "query": "Synthetic question",
        "query_vector": [1.0, 0.0, 0.0, 0.0],
        "binding": {
            "subject": "synthetic",
            "client": "test",
            "audience": "local-private",
            "character_id": "a",
        },
        "sources": [
            {
                "id": "s",
                "revision": 1,
                "epoch": 0,
                "conversation_id": "c",
                "turn_revision": 3,
                "message_index": 2,
                "private": False,
                "excluded": False,
                "deleted": False,
                "role": "user",
            }
        ],
        "memories": [
            {
                "id": "m",
                "text": "Synthetic allowed evidence",
                "source_ids": ["s"],
                "vector": [1.0, 0.0, 0.0, 0.0],
            }
        ],
        "mutations": [],
        "limit": 8,
    }


def scenario(case: Case) -> tuple[MagicMock, Backend, SearchHit]:
    store = MagicMock(spec=PgvectorMemoryStore)
    backend = Backend()
    memory = case.memories[0]
    owner = (memory.binding or case.binding).binding()
    work = WorkItem(
        owner,
        memory.id,
        1,
        "0" * 64,
        1,
        (case.sources[0].snapshot(),),
        backend.space,
        1,
        memory.text,
    )
    hit = SearchHit(memory.id, memory.text, 1.0, work.token)
    store.prepare.return_value = work
    store.complete.return_value = True
    store.search.return_value = (hit,)
    store.valid.return_value = True
    return store, backend, hit


def test_fixture_answers_only_from_retrieved_evidence_and_preserves_provenance() -> None:
    case = Case.model_validate(case_data())
    store, backend, _ = scenario(case)
    output = evaluate_case(case, backend, "answer", store)
    assert output["answer"]["text"] == "[m] Synthetic allowed evidence"
    assert output["retrieved"][0]["sources"][0] == {
        "source_id": "s",
        "revision": 1,
        "epoch": 0,
        "conversation_id": "c",
        "turn_revision": 3,
        "message_index": 2,
    }
    assert output["dispatch"]["memory_ids"] == ["m"]
    assert output["calls"] == {"embedding_requests": 0, "embedding_texts": 0, "chat_requests": 0}
    assert output["quality_evidence"] is False and output["embedded_memory_ids"] == []
    assert output["embedding_input_ids"] == ["m"]
    assert store.valid.call_count == 2


@pytest.mark.parametrize(
    "phase,valid,discarded",
    [
        ("after_search", [False, False], False),
        ("after_answer", [True, False], True),
    ],
)
def test_revocation_blocks_dispatch_or_discards_the_generated_answer(
    phase: str,
    valid: list[bool],
    discarded: bool,
) -> None:
    data = case_data()
    data["mutations"] = [
        {
            "phase": phase,
            "op": "source_replace",
            "source_id": "s",
            "changes": {"private": True, "epoch": 1},
        }
    ]
    case = Case.model_validate(data)
    store, backend, _ = scenario(case)
    store.valid.side_effect = valid
    backend.answer = MagicMock(return_value="DO NOT PUBLISH THIS REVOKED ANSWER")  # type: ignore[method-assign]
    output = evaluate_case(case, backend, "answer", store)
    assert output["answer"]["text"] is None and output["answer"]["discarded"] is discarded
    assert output["dispatch"]["allowed"] is False and output["dispatch"]["memory_ids"] == []
    assert output["dispatch"]["invalid_tokens"] == ["m"]
    assert "DO NOT PUBLISH" not in json.dumps(output)
    assert backend.answer.call_count == (1 if discarded else 0)


def test_before_search_revocation_prevents_text_from_reaching_embedding() -> None:
    data = case_data()
    data["mutations"] = [
        {
            "phase": "before_search",
            "op": "source_replace",
            "source_id": "s",
            "changes": {"excluded": True, "epoch": 1},
        }
    ]
    case = Case.model_validate(data)
    store, backend, _ = scenario(case)
    store.prepare.return_value = None
    store.search.return_value = ()
    store.export_eligible.return_value = ()
    backend.vector = MagicMock(return_value=(1.0, 0.0, 0.0, 0.0))  # type: ignore[method-assign]
    output = evaluate_case(case, backend, "answer", store)
    backend.vector.assert_not_called()
    assert output["answer"]["text"] == "根拠となる記憶がありません。"
    assert output["dispatch"]["allowed"] is False


def test_other_binding_memory_is_never_sent_to_embedding() -> None:
    data = case_data()
    foreign = {**data["binding"], "subject": "other-subject"}
    data["sources"][0]["binding"] = foreign
    data["memories"][0]["binding"] = foreign
    case = Case.model_validate(data)
    store, backend, _ = scenario(case)
    store.search.return_value = ()
    store.export_eligible.return_value = ()
    backend.vector = MagicMock(return_value=(1.0, 0.0, 0.0, 0.0))  # type: ignore[method-assign]
    evaluate_case(case, backend, "retrieval", store)
    backend.vector.assert_not_called()
    store.complete.assert_called_once()


def test_initial_private_write_is_verified_as_rejected_without_embedding() -> None:
    data = case_data()
    data["sources"][0]["private"] = True
    case = Case.model_validate(data)
    store, backend, _ = scenario(case)
    store.put_memory.side_effect = ValueError("not eligible")
    store.search.return_value = ()
    store.export_eligible.return_value = ()
    backend.vector = MagicMock(return_value=(1.0, 0.0, 0.0, 0.0))  # type: ignore[method-assign]
    output = evaluate_case(case, backend, "retrieval", store)
    assert output["rejected_memory_ids"] == ["m"]
    store.prepare.assert_not_called()
    backend.vector.assert_not_called()


@pytest.mark.parametrize("extra", ["expect", "expected_ids", "gold", "profile_path"])
def test_cases_reject_expected_data_and_runtime_controls(extra: str) -> None:
    with pytest.raises(ValidationError):
        Case.model_validate({**case_data(), extra: "not an input"})


@pytest.mark.parametrize(
    "options,context",
    [
        ({"config": {"suite": "answer", "expect": "leak"}}, {"vars": {"case_id": "unit"}}),
        ({"config": {"suite": "answer"}}, {"vars": {"case_id": "unit", "gold": "leak"}}),
        ({"config": {"suite": "unknown"}}, {"vars": {"case_id": "unit"}}),
        ({"config": {"suite": "answer", "mode": "local_model"}}, {"vars": {"case_id": "unit"}}),
        (
            {"config": {"suite": "answer", "profile_path": "/private/profile"}},
            {"vars": {"case_id": "unit"}},
        ),
    ],
)
def test_provider_rejects_unexpected_controls_without_disclosing_inputs(
    options: dict[str, Any],
    context: dict[str, Any],
) -> None:
    assert call_api("unit", options, context) == {"error": "semantic_evaluation_failed"}


def profile_data() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile_id": "test-local",
        "embedding": {
            "profile_id": "embed",
            "api_base": "http://127.0.0.1:18082/v1",
            "model": "embed-model",
            "model_digest": "synthetic-digest",
            "dimensions": 4,
            "enabled": True,
        },
        "chat": {
            "api_base": "http://127.0.0.1:18081/v1",
            "model": "chat-model",
            "model_digest": "synthetic-digest",
            "enabled": True,
        },
    }


@pytest.mark.parametrize("field", ["embedding", "chat"])
@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com/v1",
        "http://localhost:18081/v1",
        "http://user:password@127.0.0.1:18081/v1",
    ],
)
def test_profile_rejects_nonliteral_loopback_or_credentials(field: str, endpoint: str) -> None:
    data = profile_data()
    data[field]["api_base"] = endpoint
    with pytest.raises((ValidationError, CoreError)):
        LocalProfile.model_validate(data)


def test_model_identity_contains_hashes_but_no_raw_endpoint_or_digest() -> None:
    backend = Backend(LocalProfile.model_validate(profile_data()))
    serialized = json.dumps(backend.identity())
    assert "127.0.0.1" not in serialized and "synthetic-digest" not in serialized
    assert backend.identity()["embedding"]["model"] == "embed-model"
    assert backend.calls["embedding_requests"] == 0


def test_retrieval_does_not_generate_an_answer() -> None:
    case = Case.model_validate(case_data())
    store, backend, _ = scenario(case)
    backend.answer = MagicMock(side_effect=AssertionError("answer backend must not run"))  # type: ignore[method-assign]
    output = evaluate_case(case, backend, "retrieval", store)
    assert output["answer"] == {"text": None, "mode": "not_run", "discarded": False}


def test_failed_revalidation_never_falls_back_to_fixture_answer() -> None:
    case = Case.model_validate(case_data())
    store, backend, hit = scenario(case)
    store.search.return_value = (replace(hit, token=hit.token),)
    store.valid.side_effect = RuntimeError("database unavailable")
    backend.answer = MagicMock(side_effect=AssertionError("must not call"))  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="database unavailable"):
        evaluate_case(case, backend, "answer", store)


@pytest.mark.parametrize(
    "field,value",
    [
        ("finish_reason", "length"),
        ("finish_reason", "content_filter"),
        ("refusal", "refused"),
        ("tool_calls", ["tool"]),
        ("function_call", {"name": "tool"}),
    ],
)
def test_local_chat_rejects_incomplete_or_nontext_responses(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    message = SimpleNamespace(
        content="Synthetic answer", refusal=None, tool_calls=None, function_call=None
    )
    choice = SimpleNamespace(finish_reason="stop", message=message)
    setattr(choice if field == "finish_reason" else message, field, value)
    response = SimpleNamespace(model="chat-model", choices=[choice])
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    )

    @asynccontextmanager
    async def fake_client(*args: Any) -> AsyncIterator[Any]:
        yield client

    monkeypatch.setattr(runtime, "local_openai_client", fake_client)
    case = Case.model_validate(case_data())
    _, _, hit = scenario(case)
    backend = Backend(LocalProfile.model_validate(profile_data()))
    with pytest.raises(ValueError, match="complete text answer"):
        backend.answer(case.query, (hit,))
    assert backend.calls["chat_requests"] == 1
    sent = client.chat.completions.create.call_args.kwargs["messages"][-1]["content"]
    assert json.loads(sent) == {
        "query": case.query,
        "evidence": [{"memory_id": "m", "text": hit.text}],
    }


def test_local_empty_candidates_abstain_without_claiming_model_execution() -> None:
    case = Case.model_validate(case_data())
    store, _, _ = scenario(case)
    backend = Backend(LocalProfile.model_validate(profile_data()))
    store.prepare.return_value = None
    store.export_eligible.return_value = ()
    backend.vector = MagicMock(side_effect=AssertionError("must not embed"))  # type: ignore[method-assign]
    backend.answer = MagicMock(side_effect=AssertionError("must not chat"))  # type: ignore[method-assign]
    output = evaluate_case(case, backend, "answer", store)
    assert output["answer"] == {
        "text": "根拠となる記憶がありません。",
        "mode": "template",
        "discarded": False,
    }
    assert all(value == 0 for value in output["calls"].values())
    assert output["embedding_input_ids"] == output["embedded_memory_ids"] == []
    assert output["dispatch"]["model_called"] is False


def test_local_answer_requires_chat_profile_before_database_access(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = {**profile_data(), "chat": None}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    forbidden_io = MagicMock(side_effect=AssertionError("must not create database store"))
    monkeypatch.setattr("evals.semantic.provider.PgvectorMemoryStore", forbidden_io)
    result = call_api(
        "synonym-warm-drink-ja",
        {"config": {"suite": "answer", "mode": "local_model", "profile_path": str(path)}},
        {"vars": {"case_id": "synonym-warm-drink-ja"}},
    )
    assert result == {"error": "semantic_evaluation_failed"}
    forbidden_io.assert_not_called()
