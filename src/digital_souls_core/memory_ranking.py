"""In-process embedding port and pure, content-free cosine ranking."""

import math
from dataclasses import dataclass, field
from typing import Protocol

from .application import CoreError
from .memory_contracts import Memory
from .privacy_scan import scan


@dataclass(frozen=True)
class EmbeddingSpace:
    model: str = field(repr=False)
    revision: str = field(repr=False)
    dimensions: int

    def __post_init__(self) -> None:
        validate_embedding_space(self)


def validate_embedding_space(value: object) -> EmbeddingSpace:
    """Recheck adapter metadata at runtime, including forged dataclass instances."""
    try:
        if type(value) is not EmbeddingSpace:
            raise ValueError
        for identifier in (value.model, value.revision):
            if (
                type(identifier) is not str
                or not 0 < len(identifier) <= 128
                or identifier != identifier.strip()
            ):
                raise ValueError
            finding = scan(identifier)
            if finding.secret or finding.failed:
                raise ValueError
        if type(value.dimensions) is not int or not 1 <= value.dimensions <= 4096:
            raise ValueError
        return value
    except Exception:
        raise CoreError(502, "memory_embedding_failed", "Memory embedding failed") from None


class MemoryEmbedding(Protocol):
    """Trusted startup-injected in-process implementation; no transport adapter."""

    @property
    def space(self) -> EmbeddingSpace: ...

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


def _unit_vector(vector: object, dimensions: int) -> tuple[float, ...]:
    if type(vector) is not tuple or len(vector) != dimensions:
        raise ValueError
    if any(type(component) not in (float, int) for component in vector):
        raise ValueError
    values = tuple(float(component) for component in vector)
    if not all(math.isfinite(component) for component in values):
        raise ValueError
    scale = max(abs(component) for component in values)
    if scale == 0:
        raise ValueError
    # Scaling before squaring keeps finite extremes and subnormal vectors usable.
    scaled = tuple(component / scale for component in values)
    norm = math.sqrt(math.fsum(component * component for component in scaled))
    return tuple(component / norm for component in scaled)


def rank_memories(
    memories: tuple[Memory, ...],
    vectors: tuple[tuple[float, ...], ...],
    space: EmbeddingSpace,
    limit: int,
) -> tuple[Memory, ...]:
    """Rank positive cosine matches; query vector first, stable candidate-order ties."""
    try:
        validate_embedding_space(space)
        if (
            type(memories) is not tuple
            or any(type(memory) is not Memory for memory in memories)
            or type(vectors) is not tuple
            or len(vectors) != len(memories) + 1
            or type(limit) is not int
            or limit < 1
        ):
            raise ValueError
        query, *candidates = tuple(_unit_vector(vector, space.dimensions) for vector in vectors)
        scored = [
            (math.fsum(left * right for left, right in zip(query, vector, strict=True)), memory)
            for memory, vector in zip(memories, candidates, strict=True)
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        return tuple(memory for score, memory in scored if score > 0)[:limit]
    except Exception:
        raise CoreError(502, "memory_embedding_failed", "Memory embedding failed") from None
