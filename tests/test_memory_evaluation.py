import asyncio
import copy
import json
import runpy
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from digital_souls_core import memory_evaluation
from digital_souls_core.application import CoreError
from digital_souls_core.memory_contracts import Memory
from digital_souls_core.memory_evaluation import (
    EvaluationFixture,
    FixtureEmbedding,
    evaluate_memory_search,
)
from digital_souls_core.memory_ranking import EmbeddingSpace, rank_memories

FIXTURE = Path(__file__).parent / "fixtures/memory-retrieval-evaluation.json"
CLI = Path(__file__).parents[1] / "tools/evaluate-memory-search.py"


def fixture_data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def fixture() -> EvaluationFixture:
    return EvaluationFixture.model_validate(fixture_data())


class RecordingEmbedding:
    def __init__(self, dataset: EvaluationFixture) -> None:
        self.delegate = FixtureEmbedding(dataset)
        self.space = self.delegate.space
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        return await self.delegate.embed(texts)


@pytest.mark.ut
async def test_synthetic_metrics_and_report_do_not_claim_model_quality() -> None:
    dataset = fixture()
    encoder = RecordingEmbedding(dataset)
    result = await evaluate_memory_search(dataset, encoder, k=2)
    assert result.mode == "fixture" and result.quality_evidence is False
    assert result.synthetic_only and not result.backend_identity_verified
    assert result.space == encoder.space
    assert result.query_count == 5 and result.answerable_count == 2
    assert result.embedding_call_count == 3
    assert result.unanswerable_count == 3
    assert result.empty_result_count == 3 and result.answerable_empty_result_count == 0
    assert result.unanswerable_empty_result_count == 3
    assert result.mean_recall_at_k == 1 and result.mean_precision_at_k == 0.75
    assert result.mrr_at_k == 1 and result.unanswerable_empty_rate == 1
    assert result.queries[0].retrieved_ids == ("tea-ja", "tea-en")
    assert result.queries[1].retrieved_ids == ("garden-en", "tea-en")
    assert result.queries[2].recall_at_k is None
    assert result.queries[2].precision_at_k is None
    assert result.queries[2].reciprocal_rank is None
    assert len(encoder.calls) == 3  # Empty and fully excluded scopes are never embedded.
    serialized = json.dumps(asdict(result), ensure_ascii=False)
    assert "vector" not in serialized and "text" not in serialized
    for item in (*dataset.documents, *dataset.queries):
        assert item.text not in serialized and item.text not in repr(dataset)


@pytest.mark.ut
async def test_exclusion_precedes_embedding_and_ranking_preserves_source_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = fixture()
    encoder = RecordingEmbedding(dataset)
    observations: list[tuple[tuple[Memory, ...], tuple[Memory, ...]]] = []

    def rank(
        candidates: tuple[Memory, ...],
        vectors: tuple[tuple[float, ...], ...],
        space: EmbeddingSpace,
        limit: int,
    ) -> tuple[Memory, ...]:
        result = rank_memories(candidates, vectors, space, limit)
        observations.append((candidates, result))
        return result

    monkeypatch.setattr(memory_evaluation, "rank_memories", rank)
    report = await evaluate_memory_search(dataset, encoder)
    excluded = next(
        document for document in dataset.documents if document.id == "excluded-placeholder"
    )
    assert all(excluded.text not in call for call in encoder.calls)
    assert all(excluded.id not in row.retrieved_ids for row in report.queries)
    assert all(excluded.id not in {item.memory_id for item in pair[0]} for pair in observations)
    candidates, ranked = observations[0]
    assert ranked[0] is next(memory for memory in candidates if memory.memory_id == "tea-ja")
    assert ranked[0].sources is candidates[2].sources
    source = ranked[0].sources[0]
    assert (source.reference.conversation_id, source.reference.turn_revision) == ("synthetic-ja", 3)
    assert source.reference.message_index == 0 and source.epoch == 2


@pytest.mark.ut
async def test_positive_cosine_descends_and_precision_denominator_is_k() -> None:
    report = await evaluate_memory_search(fixture(), FixtureEmbedding(fixture()), k=1)
    assert report.queries[0].retrieved_ids == ("tea-ja",)
    assert report.queries[0].recall_at_k == 0.5
    assert report.mean_recall_at_k == 0.75
    assert report.mean_precision_at_k == 1 and report.mrr_at_k == 1
    data = fixture_data()
    data["queries"] = [data["queries"][0]]
    data["queries"][0]["relevant_ids"] = ["tea-en"]
    dataset = EvaluationFixture.model_validate(data)
    result = await evaluate_memory_search(dataset, FixtureEmbedding(dataset), k=4)
    assert result.queries[0].retrieved_ids == ("tea-ja", "tea-en")
    assert result.mean_recall_at_k == 1
    assert result.mean_precision_at_k == 0.25 and result.mrr_at_k == 0.5
    assert result.unanswerable_empty_rate is None


@pytest.mark.ut
async def test_answerable_miss_is_zero_not_unanswerable_success() -> None:
    data = fixture_data()
    data["queries"] = [data["queries"][0]]
    data["queries"][0]["vector"] = [-1, 0, 0, 0]
    dataset = EvaluationFixture.model_validate(data)
    report = await evaluate_memory_search(dataset, FixtureEmbedding(dataset))
    assert report.answerable_empty_result_count == report.empty_result_count == 1
    assert report.unanswerable_count == report.unanswerable_empty_result_count == 0
    assert report.mean_recall_at_k == report.mean_precision_at_k == report.mrr_at_k == 0
    assert report.unanswerable_empty_rate is None


@pytest.mark.ut
async def test_unanswerable_false_positive_counts_against_empty_result_rate() -> None:
    data = fixture_data()
    data["queries"] = [data["queries"][2]]
    data["queries"][0]["vector"] = [1, 0, 0, 0]
    dataset = EvaluationFixture.model_validate(data)
    report = await evaluate_memory_search(dataset, FixtureEmbedding(dataset))
    assert report.queries[0].retrieved_ids == ("tea-ja", "tea-en")
    assert report.answerable_count == 0 and report.unanswerable_count == 1
    assert report.unanswerable_empty_rate == 0 and report.empty_result_count == 0
    assert report.mean_recall_at_k is report.mean_precision_at_k is report.mrr_at_k is None


@pytest.mark.ut
async def test_no_documents_is_valid_and_never_calls_encoder() -> None:
    data = fixture_data()
    data["documents"] = []
    data["queries"] = [data["queries"][-1]]
    dataset = EvaluationFixture.model_validate(data)
    encoder = RecordingEmbedding(dataset)
    report = await evaluate_memory_search(dataset, encoder)
    assert encoder.calls == [] and report.unanswerable_empty_rate == 1
    assert report.queries[0].candidate_count == 0
    assert report.mean_recall_at_k is report.mean_precision_at_k is report.mrr_at_k is None
    local_report = await evaluate_memory_search(dataset, encoder, mode="local_model")
    assert local_report.mode == "local_model"
    assert local_report.embedding_call_count == 0 and not local_report.quality_evidence
    assert encoder.calls == []


@pytest.mark.ut
@pytest.mark.parametrize(
    "invalid",
    [
        "duplicate-document",
        "duplicate-query",
        "unknown-candidate",
        "unknown-relevant",
        "unknown-excluded",
        "duplicate-candidate",
        "duplicate-relevant",
        "duplicate-excluded",
        "excluded-relevant",
        "relevant-not-candidate",
        "excluded-not-candidate",
        "no-queries",
        "zero-vector",
        "wrong-dimensions",
        "nan-vector",
        "bool-vector",
        "conflicting-text",
        "non-synthetic",
        "invalid-id",
        "unknown-field",
        "invalid-source",
    ],
)
def test_fixture_validation_rejects_ambiguous_or_invalid_gold_data(invalid: str) -> None:
    data = copy.deepcopy(fixture_data())
    query, document = data["queries"][0], data["documents"][0]
    if invalid == "duplicate-document":
        data["documents"].append(document)
    elif invalid == "duplicate-query":
        data["queries"].append(query)
    elif invalid.startswith("unknown-") and invalid != "unknown-field":
        field = invalid.removeprefix("unknown-") + "_ids"
        query[field].append("unknown")
    elif invalid.startswith("duplicate-"):
        field = invalid.removeprefix("duplicate-") + "_ids"
        query[field].append(query[field][0])
    elif invalid == "excluded-relevant":
        query["excluded_ids"].append("tea-ja")
    elif invalid == "relevant-not-candidate":
        query["candidate_ids"].remove("tea-ja")
    elif invalid == "excluded-not-candidate":
        query["candidate_ids"].remove("excluded-placeholder")
    elif invalid == "no-queries":
        data["queries"] = []
    elif invalid == "zero-vector":
        document["vector"] = [0, 0, 0, 0]
    elif invalid == "wrong-dimensions":
        document["vector"] = [1, 0]
    elif invalid == "nan-vector":
        query["vector"][0] = float("nan")
    elif invalid == "bool-vector":
        query["vector"][0] = True
    elif invalid == "conflicting-text":
        data["documents"][1]["text"] = document["text"]
    elif invalid == "non-synthetic":
        data["dataset_type"] = "history"
    elif invalid == "invalid-id":
        document["id"] = "free text cannot be a report identifier"
    elif invalid == "unknown-field":
        query["unexpected"] = "ignored"
    else:
        document["source"]["epoch"] = -1
    with pytest.raises(ValidationError):
        EvaluationFixture.model_validate(data)


@pytest.mark.ut
@pytest.mark.parametrize("field", ["model", "revision", "dimensions", "configuration"])
async def test_embedding_space_changes_fail_closed(field: str) -> None:
    dataset = fixture()

    class ChangedEmbedding(RecordingEmbedding):
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            vectors = await super().embed(texts)
            if field == "dimensions":
                self.space = replace(self.space, dimensions=3)
            elif field == "model":
                self.space = replace(self.space, model="changed")
            elif field == "revision":
                self.space = replace(self.space, revision="changed")
            else:
                self.space = replace(self.space, configuration="changed")
            return vectors

    with pytest.raises(CoreError, match="^Memory embedding failed$"):
        await evaluate_memory_search(dataset, ChangedEmbedding(dataset))


@pytest.mark.ut
async def test_timeout_is_sanitized_and_cancellation_propagates() -> None:
    dataset = fixture()
    entered, release = asyncio.Event(), asyncio.Event()

    class BlockedEmbedding(RecordingEmbedding):
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            entered.set()
            await release.wait()
            return await super().embed(texts)

    encoder = BlockedEmbedding(dataset)
    with pytest.raises(CoreError, match="^Memory embedding failed$") as caught:
        await evaluate_memory_search(dataset, encoder, timeout_seconds=0.001)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    entered.clear()
    task = asyncio.create_task(evaluate_memory_search(dataset, encoder))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.ut
async def test_backend_failure_and_invalid_vectors_never_expose_content() -> None:
    dataset = fixture()

    class BrokenEmbedding(RecordingEmbedding):
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            raise ValueError(texts)

    class InvalidVectors(RecordingEmbedding):
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            return ((1.0,),) * len(texts)

    for encoder in (BrokenEmbedding(dataset), InvalidVectors(dataset)):
        with pytest.raises(CoreError, match="^Memory embedding failed$") as caught:
            await evaluate_memory_search(dataset, encoder)
        assert caught.value.__cause__ is None and caught.value.__suppress_context__


@pytest.mark.ut
async def test_local_mode_is_declared_synthetic_measurement_without_identity_attestation() -> None:
    dataset = fixture()
    report = await evaluate_memory_search(dataset, RecordingEmbedding(dataset), mode="local_model")
    assert report.quality_evidence and report.mode == "local_model"
    assert report.synthetic_only and not report.backend_identity_verified
    with pytest.raises(ValueError, match="fixture vectors are not model-quality evidence"):
        await evaluate_memory_search(dataset, FixtureEmbedding(dataset), mode="local_model")


@pytest.mark.ut
@pytest.mark.parametrize("k", [0, -1, 17, True])
async def test_invalid_k_is_rejected(k: int) -> None:
    with pytest.raises(ValueError, match="invalid evaluation configuration"):
        await evaluate_memory_search(fixture(), FixtureEmbedding(fixture()), k=k)


@pytest.mark.it1
def test_cli_defaults_to_offline_fixture_and_prints_content_free_json() -> None:
    process = subprocess.run(
        [sys.executable, str(CLI)], capture_output=True, text=True, check=False, timeout=30
    )
    assert process.returncode == 0 and process.stderr == ""
    report = json.loads(process.stdout)
    assert report["mode"] == "fixture" and report["quality_evidence"] is False
    assert report["query_count"] == 5 and report["mean_recall_at_k"] == 1
    assert "架空" not in process.stdout and "vector" not in process.stdout


@pytest.mark.it1
def test_cli_failure_hides_malformed_fixture_content_and_paths(tmp_path: Path) -> None:
    path = tmp_path / "synthetic-sensitive-name.json"
    path.write_text('{"sensitive-content-marker": "malformed"}', encoding="utf-8")
    process = subprocess.run(
        [sys.executable, str(CLI), "--fixture", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert process.returncode == 1 and process.stdout == ""
    assert "評価に失敗" in process.stderr
    assert "sensitive" not in process.stderr and "Traceback" not in process.stderr


@pytest.mark.it1
def test_cli_explicit_profile_selects_local_adapter_without_real_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from digital_souls_core import local_embedding

    profiles: list[local_embedding.LocalEmbeddingProfile] = []
    encoders: list[RecordingEmbedding] = []

    class ProfileEmbedding(RecordingEmbedding):
        def __init__(self, profile: local_embedding.LocalEmbeddingProfile) -> None:
            super().__init__(fixture())
            profiles.append(profile)
            encoders.append(self)

    path = tmp_path / "local-profile.json"
    path.write_text(
        json.dumps(
            {
                "profile_id": "synthetic-evaluation",
                "model": "synthetic",
                "model_digest": "fixture-v1",
                "dimensions": 4,
                "api_base": "http://127.0.0.1:12345/v1",
                "enabled": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(local_embedding, "LocalEmbedding", ProfileEmbedding)
    monkeypatch.setattr(sys, "argv", [str(CLI), "--profile", str(path)])
    with pytest.raises(SystemExit) as completed:
        runpy.run_path(str(CLI), run_name="__main__")
    assert completed.value.code == 0
    output = capsys.readouterr()
    assert output.err == ""
    report = json.loads(output.out)
    assert report["mode"] == "local_model" and report["quality_evidence"] is True
    assert report["backend_identity_verified"] is False
    assert len(profiles) == len(encoders) == 1 and len(encoders[0].calls) == 3
    assert profiles[0].profile_id == "synthetic-evaluation"
