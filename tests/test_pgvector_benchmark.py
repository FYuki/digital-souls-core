import math
from typing import Any

import pytest

from experiments.pgvector_memory.benchmark import (
    compare_results,
    latency_summary,
    plan_summary,
    verify_postmaster,
)
from experiments.pgvector_memory.synthetic import cosine, float32, make_corpus, vector32

pytestmark = pytest.mark.ut


def test_plan_summary_does_not_emit_sql_expressions_or_vectors() -> None:
    plan = {
        "Plan": {
            "Node Type": "Limit",
            "Actual Rows": 8,
            "Total Cost": 100,
            "Output": ["sensitive-marker"],
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "embeddings",
                    "Filter": "sensitive-marker",
                }
            ],
        },
        "JIT": {"Functions": 3, "Timing": {"Total": 40.0}},
    }
    summary = plan_summary(plan)
    assert summary["node_counts"] == {"Limit": 1, "Seq Scan": 1}
    assert summary["relations"] == ["embeddings"]
    assert summary["root"] == {"Actual Rows": 8, "Total Cost": 100}
    assert summary["jit"] == {"Functions": 3, "Timing": {"Total": 40.0}}
    assert "sensitive-marker" not in str(summary)


@pytest.mark.parametrize(
    "before,after",
    [
        ({}, {}),
        ({"postmaster_start_time": "a"}, {}),
        ({"postmaster_start_time": "a"}, {"postmaster_start_time": "b"}),
        ({"postmaster_start_time": ""}, {"postmaster_start_time": ""}),
    ],
)
def test_restart_or_missing_identity_discards_measurement(
    before: dict[str, Any], after: dict[str, Any]
) -> None:
    with pytest.raises(RuntimeError, match="discard all timing samples"):
        verify_postmaster(before, after)


def test_unchanged_postmaster_is_reported() -> None:
    assert verify_postmaster({"postmaster_start_time": "a"}, {"postmaster_start_time": "a"}) == "a"


def test_corpus_and_queries_are_reproducible_float32_prefixes() -> None:
    small = make_corpus(100, dimensions=128, seed=42, query_count=8)
    large = make_corpus(1000, dimensions=128, seed=42, query_count=8)
    assert small == make_corpus(100, 128, 42, 8)
    assert small.documents == large.documents[:100]
    assert small.queries == large.queries
    assert small.queries != make_corpus(100, 128, 43, 8).queries
    assert len(large.source_ids) == 100
    for document in small.documents:
        assert len(document.vector) == 128 and any(document.vector)
        assert vector32(document.vector) == document.vector
        assert document.source_id in small.source_ids
        assert "Synthetic retrieval fact" in document.text


def test_float32_restores_postgres_decimal_output_to_identical_components() -> None:
    original = float32(0.203854083333333)
    decimal_text = float(format(original, ".8g"))
    assert decimal_text != original
    assert float32(decimal_text) == original


@pytest.mark.parametrize(
    "kwargs",
    [
        {"count": 0},
        {"count": 10001},
        {"count": True},
        {"count": 10, "dimensions": 0},
        {"count": 10, "dimensions": 2001},
        {"count": 10, "seed": -1},
        {"count": 10, "query_count": 0},
        {"count": 10, "query_count": 17},
    ],
)
def test_invalid_corpus_arguments_fail_before_allocating(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="invalid synthetic"):
        make_corpus(**kwargs)


def test_latency_percentiles_are_linear_and_accept_a_single_sample() -> None:
    assert latency_summary([0, 10, 20, 30, 40])["p50_ms"] == 20
    assert latency_summary([0, 10, 20, 30, 40])["p95_ms"] == 38
    assert latency_summary([4]) == {
        "samples": 1,
        "min_ms": 4,
        "p50_ms": 4,
        "p95_ms": 4,
        "max_ms": 4,
        "mean_ms": 4,
    }


@pytest.mark.parametrize("samples", [[], [math.inf], [math.nan], [-1]])
def test_latency_summary_never_turns_missing_or_invalid_data_into_success(
    samples: list[float],
) -> None:
    with pytest.raises(ValueError, match="latency samples"):
        latency_summary(samples)


def test_equivalence_requires_ids_order_and_tolerated_positive_cosine_scores() -> None:
    reference = (("first", 1.0), ("second", 0.75))
    match = compare_results(reference, (("first", 1.0), ("second", 0.750001)))
    assert match.ids_match and match.scores_within_tolerance
    assert match.max_absolute_score_error == pytest.approx(0.000001)
    assert not compare_results(reference, tuple(reversed(reference))).ids_match
    assert not compare_results(
        reference, (("first", 0.9), ("second", 0.75))
    ).scores_within_tolerance
    assert not compare_results(reference, reference[:1]).scores_within_tolerance
    assert compare_results((), ()).scores_within_tolerance


@pytest.mark.parametrize("score", [0, -0.2, math.nan, math.inf, 1.1])
def test_nonpositive_nonfinite_or_out_of_range_database_score_is_rejected(score: float) -> None:
    with pytest.raises(ValueError, match="invalid positive cosine"):
        compare_results((("first", 0.5),), (("first", score),))


def test_cosine_verification_uses_similarity_not_distance() -> None:
    assert cosine((2.0, 0.0), (5.0, 0.0)) == 1
    assert cosine((2.0, 0.0), (-5.0, 0.0)) == -1
    assert cosine((2.0, 0.0), (0.0, 5.0)) == 0
    with pytest.raises(ValueError, match="dimensions differ"):
        cosine((1.0,), (1.0, 0.0))
    with pytest.raises(ValueError, match="zero vector"):
        cosine((0.0,), (1.0,))
