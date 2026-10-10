"""Independent synthetic tuning inputs, never the fixed acceptance dataset."""

import re
from collections import Counter
from pathlib import Path
from unicodedata import normalize

import pytest

from digital_souls_core.memory_ranking import EmbeddingSpace, RetrievalPolicy, rank_records
from digital_souls_core.memory_record_store import RetrievalCandidate
from digital_souls_core.semantic_evaluation_cases import (
    FactUpdateMutation,
    SemanticEvaluationData,
    load_evaluation_cases,
    registration_batches,
)
from digital_souls_core.semantic_retrieval_evaluation import independent_relevance

pytestmark = pytest.mark.ut
ROOT = Path(__file__).resolve().parents[1] / "evals/semantic"
TUNING = ROOT / "tuning"
COUNTS = {
    "synonym": 10,
    "paraphrase": 10,
    "cross_language": 24,
    "unrelated": 20,
    "threshold": 12,
    "private": 1,
    "excluded": 1,
    "deleted_source": 1,
    "deleted_memory": 1,
    "binding_character": 1,
    "binding_subject": 1,
    "binding_client": 1,
    "after_search": 1,
    "after_answer": 1,
    "epoch_change": 1,
    "equivalent_order": 1,
}


def tuning() -> SemanticEvaluationData:
    return load_evaluation_cases(TUNING / "cases.json", TUNING / "expectations.json")


def texts(data: SemanticEvaluationData) -> set[str]:
    return {
        text
        for c in data.cases.cases
        for text in (
            c.query,
            *(r.normalized_text for r in (*c.episodes, *c.facts, *c.semantics)),
            *(m.fact.normalized_text for m in c.mutations if isinstance(m, FactUpdateMutation)),
        )
    }


def test_tuning_schema_categories_and_documentation() -> None:
    data = tuning()
    assert data.cases.schema_version == 1 and data.expectations.schema_version == 2
    assert data.cases.dataset_type == "synthetic"
    assert len(data.cases.cases) == 87
    assert Counter(g.category for g in data.expectations.cases) == COUNTS
    table = {
        category: int(count)
        for category, count in re.findall(
            r"^\| ([a-z_]+) \| (\d+) \|$", (TUNING / "README.md").read_text(), re.MULTILINE
        )
    }
    assert table == COUNTS
    assert all(c.legacy_id is None for c in data.cases.cases)
    assert all(registration_batches(c) for c in data.cases.cases)


@pytest.mark.parametrize("normalization", ["exact", "NFKC", "NFKC-casefold"])
def test_no_query_or_record_overlap_with_acceptance_cases(normalization: str) -> None:
    fixed = load_evaluation_cases(ROOT / "cases.json", ROOT / "expectations.json")

    def canonical(text: str) -> str:
        if normalization == "exact":
            return text
        text = normalize("NFKC", text)
        return text.casefold() if normalization == "NFKC-casefold" else text

    assert not {canonical(t) for t in texts(fixed)} & {canonical(t) for t in texts(tuning())}


def test_cross_language_has_twelve_cases_in_each_direction() -> None:
    data = tuning()
    by_id = {c.id: c for c in data.cases.cases}
    directions: Counter[str] = Counter()
    for gold in data.expectations.cases:
        if gold.category != "cross_language":
            continue
        c = by_id[gold.id]
        query_ja = bool(re.search(r"[ぁ-んァ-ヶ一-龯]", c.query))
        for r in c.episodes:
            assert bool(re.search(r"[ぁ-んァ-ヶ一-龯]", r.normalized_text)) != query_ja
        directions["ja-to-en" if query_ja else "en-to-ja"] += 1
    assert directions == {"ja-to-en": 12, "en-to-ja": 12}


def test_unrelated_and_threshold_use_near_topic_distractors_and_both_sides() -> None:
    data = tuning()
    by_id = {c.id: c for c in data.cases.cases}
    near_scores = []
    for gold in data.expectations.cases:
        if gold.category not in {"unrelated", "threshold"}:
            continue
        c = by_id[gold.id]
        assert len(c.episodes) >= 2
        assert all("ネモラ" in r.normalized_text for r in c.episodes)
        assert "ネモラ" in c.query
        # Each pair shares a domain marker, beyond sharing only the person.
        domain = c.episodes[0].five_w.where
        assert domain and domain in c.query
        assert all(domain in r.normalized_text for r in c.episodes)
        if gold.category == "unrelated":
            assert gold.no_match and gold.forbidden_ids
        else:
            score = independent_relevance(c.query_vector, c.episodes[0].vector)
            assert 0.539 <= score <= 0.5411
            assert (score >= 0.54) != gold.no_match
            near_scores.append(score)
    assert len(near_scores) == 12
    assert sum(s >= 0.54 for s in near_scores) == 6


def test_unmutated_tuning_vectors_match_production_ranking_and_fixed_gold() -> None:
    data = tuning()
    gold = {g.id: g for g in data.expectations.cases}
    checked = 0
    for c in data.cases.cases:
        if c.mutations:
            continue
        records = tuple(r for r in c.episodes if r.binding == c.binding)
        ranked = rank_records(
            tuple(RetrievalCandidate(r.to_domain()) for r in records),
            (c.query_vector, *(r.vector for r in records)),
            EmbeddingSpace("fixture", "v1", data.cases.dimensions),
            RetrievalPolicy(),
        )
        ids = tuple(r.identifier for r in ranked)
        g = gold[c.id]
        assert set(g.relevant_ids) <= set(ids), c.id
        assert not set(g.forbidden_ids) & set(ids), c.id
        if g.no_match:
            assert not ids, c.id
        if g.expected_order is not None:
            assert ids == g.expected_order, c.id
        checked += 1
    assert checked == 80
