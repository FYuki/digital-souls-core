import math
import sys
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from digital_souls_core.application import CoreError
from digital_souls_core.history import SourceReference
from digital_souls_core.memory_contracts import Memory, SourceVersion
from digital_souls_core.memory_ranking import (
    EmbeddingSpace,
    MemoryEmbedding,
    rank_memories,
    validate_embedding_space,
)

pytestmark = pytest.mark.ut

SPACE = EmbeddingSpace("synthetic-embedding", "revision-one", 2)


def memory(identifier: str, text: str = '["I enjoy synthetic tea."]') -> Memory:
    return Memory(
        identifier,
        "semantic",
        text,
        (SourceVersion(SourceReference("synthetic-conversation", 3, 0), 2),),
    )


class SyntheticEmbedding:
    @property
    def space(self) -> EmbeddingSpace:
        return SPACE

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple(
            (1.0, 0.0) if "infusion" in text or "tea" in text else (0.0, 1.0) for text in texts
        )


async def test_fake_synonym_embedding_preserves_original_memory_and_provenance() -> None:
    tea, unrelated = memory("tea"), memory("trees", '["I grow synthetic trees."]')
    embedder: MemoryEmbedding = SyntheticEmbedding()
    vectors = await embedder.embed(("synthetic infusion", tea.text, unrelated.text))
    result = rank_memories((unrelated, tea), (vectors[0], vectors[2], vectors[1]), SPACE, 8)
    assert result == (tea,)
    assert result[0] is tea
    assert result[0].sources is tea.sources
    assert result[0].sources[0].reference.turn_revision == 3
    assert result[0].sources[0].epoch == 2
    assert "infusion" not in tea.text
    assert "synthetic tea" not in repr(result)


def test_cosine_order_top_k_ties_and_nonpositive_scores() -> None:
    candidates = tuple(memory(str(index)) for index in range(6))
    vectors = ((1.0, 0.0), (0.6, 0.8), (4.0, 0.0), (2.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.8, 0.6))
    assert rank_memories(candidates, vectors, SPACE, 8) == (
        candidates[1],
        candidates[2],
        candidates[5],
        candidates[0],
    )
    assert rank_memories(candidates, vectors, SPACE, 2) == (candidates[1], candidates[2])


@pytest.mark.parametrize("scale", [sys.float_info.max, 1e200, 1e-200, math.ulp(0.0)])
def test_normalization_handles_large_and_small_finite_vectors(scale: float) -> None:
    positive, zero, negative = memory("positive"), memory("zero"), memory("negative")
    vectors = ((scale, scale), (scale, scale), (scale, -scale), (-scale, -scale))
    assert rank_memories((positive, zero, negative), vectors, SPACE, 8) == (positive,)


def test_integer_vectors_and_empty_candidates() -> None:
    item = memory("integer")
    assert rank_memories((item,), ((1, 2), (2, 4)), SPACE, 1) == (item,)
    assert rank_memories((), ((1, 0),), SPACE, 1) == ()


def test_invalid_candidate_beyond_limit_still_rejects_the_whole_result() -> None:
    candidates = (memory("first"), memory("second"))
    with pytest.raises(CoreError, match="^Memory embedding failed$"):
        rank_memories(candidates, ((1.0, 0.0), (1.0, 0.0), (0.0, 0.0)), SPACE, 1)


@pytest.mark.parametrize(
    "vectors",
    [
        None,
        [],
        (),
        ((1.0, 0.0),),
        ((1.0, 0.0), (1.0, 0.0), (1.0, 0.0)),
        [(1.0, 0.0), (1.0, 0.0)],
        ([1.0, 0.0], (1.0, 0.0)),
        ((1.0, 0.0), [1.0, 0.0]),
        ((1.0,), (1.0, 0.0)),
        ((1.0, 0.0), (1.0, 0.0, 0.0)),
        ((0.0, 0.0), (1.0, 0.0)),
        ((1.0, 0.0), (0.0, -0.0)),
        ((True, 0.0), (1.0, 0.0)),
        ((1.0, 0.0), (False, 1.0)),
        ((1.0, 0.0), ("private synthetic content", 1.0)),
        ((1.0, 0.0), (None, 1.0)),
        ((1.0, 0.0), (complex(1.0), 1.0)),
        ((1.0, 0.0), (math.inf, 1.0)),
        ((-math.inf, 0.0), (1.0, 1.0)),
        ((1.0, 0.0), (math.nan, 1.0)),
        ((1.0, 0.0), (10**400, 1.0)),
    ],
)
def test_invalid_vectors_fail_without_content_or_exception_chain(vectors: Any) -> None:
    with pytest.raises(CoreError) as caught:
        rank_memories((memory("synthetic"),), vectors, SPACE, 8)
    error = caught.value
    assert (error.status, error.code, error.message) == (
        502,
        "memory_embedding_failed",
        "Memory embedding failed",
    )
    assert error.__cause__ is None and error.__suppress_context__
    assert "private synthetic content" not in repr(error)


@pytest.mark.parametrize("limit", [None, True, False, 0, -1, 1.0, "1"])
def test_invalid_limit_fails_closed(limit: Any) -> None:
    with pytest.raises(CoreError, match="^Memory embedding failed$"):
        rank_memories((memory("synthetic"),), ((1.0, 0.0), (1.0, 0.0)), SPACE, limit)


@pytest.mark.parametrize(
    ("model", "revision", "dimensions"),
    [
        ("", "revision", 2),
        ("  ", "revision", 2),
        (" model", "revision", 2),
        ("model", "revision ", 2),
        ("model", "", 2),
        ("m" * 129, "revision", 2),
        ("model", "r" * 129, 2),
        (None, "revision", 2),
        ("model", 4, 2),
        ("api_key=synthetic-secret", "revision", 2),
        ("model", "api_key=synthetic-secret", 2),
        ("[invalid-json", "revision", 2),
        ("model", "[invalid-json", 2),
        ("model", "revision", True),
        ("model", "revision", 2.0),
        ("model", "revision", "2"),
        ("model", "revision", 0),
        ("model", "revision", -1),
        ("model", "revision", 4097),
    ],
)
def test_space_rejects_invalid_metadata(model: Any, revision: Any, dimensions: Any) -> None:
    with pytest.raises(CoreError, match="^Memory embedding failed$"):
        EmbeddingSpace(model, revision, dimensions)


def test_space_is_frozen_bounded_and_hides_identifiers_in_repr() -> None:
    assert validate_embedding_space(SPACE) is SPACE
    assert EmbeddingSpace("m" * 128, "r" * 128, 4096).dimensions == 4096
    assert EmbeddingSpace("m", "r", 1).dimensions == 1
    assert repr(SPACE) == "EmbeddingSpace(dimensions=2)"
    with pytest.raises(FrozenInstanceError):
        SPACE.dimensions = 3  # type: ignore[misc]


@pytest.mark.parametrize("value", [None, {}, ("model", "revision", 2), "private synthetic content"])
def test_runtime_space_validation_rejects_wrong_types(value: object) -> None:
    with pytest.raises(CoreError, match="^Memory embedding failed$"):
        validate_embedding_space(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [("model", "api_key=synthetic-secret"), ("revision", "[invalid-json"), ("dimensions", True)],
)
def test_runtime_space_validation_rechecks_forged_dataclass(field: str, value: object) -> None:
    forged = EmbeddingSpace("model", "revision", 2)
    object.__setattr__(forged, field, value)
    with pytest.raises(CoreError, match="^Memory embedding failed$"):
        validate_embedding_space(forged)
    with pytest.raises(CoreError, match="^Memory embedding failed$"):
        rank_memories((memory("synthetic"),), ((1.0, 0.0), (1.0, 0.0)), forged, 8)


def test_runtime_space_validation_rejects_uninitialized_dataclass() -> None:
    forged = object.__new__(EmbeddingSpace)
    with pytest.raises(CoreError, match="^Memory embedding failed$"):
        validate_embedding_space(forged)
