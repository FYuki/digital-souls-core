"""Deterministic synthetic float32 inputs; no model or conversation history."""

import json
import math
import random
import struct
from dataclasses import dataclass, field

type Vector = tuple[float, ...]


def float32(value: float) -> float:
    return struct.unpack("!f", struct.pack("!f", value))[0]  # type: ignore[no-any-return]


def vector32(values: Vector) -> Vector:
    return tuple(float32(value) for value in values)


@dataclass(frozen=True)
class SyntheticDocument:
    memory_id: str
    source_id: str
    text: str = field(repr=False)
    vector: Vector = field(repr=False)


@dataclass(frozen=True)
class SyntheticCorpus:
    seed: int
    dimensions: int
    source_ids: tuple[str, ...]
    documents: tuple[SyntheticDocument, ...]
    queries: tuple[Vector, ...] = field(repr=False)


def make_corpus(
    count: int, dimensions: int = 128, seed: int = 20261005, query_count: int = 8
) -> SyntheticCorpus:
    if (
        type(count) is not int
        or not 1 <= count <= 10000
        or type(dimensions) is not int
        or not 1 <= dimensions <= 2000
        or type(seed) is not int
        or not 0 <= seed < 2**32
        or type(query_count) is not int
        or not 1 <= query_count <= 16
    ):
        raise ValueError("invalid synthetic corpus configuration")
    # Independent streams keep query vectors and corpus prefixes identical across sizes.
    document_random = random.Random(seed)
    query_random = random.Random(seed ^ 0x6A09E667)

    def vector(generator: random.Random) -> Vector:
        result = tuple(float32(generator.uniform(-1, 1)) for _ in range(dimensions))
        if not any(result):
            raise ValueError("synthetic vector must be nonzero")
        return result

    source_ids = tuple(f"synthetic-source-{index:04d}" for index in range(min(count, 100)))
    return SyntheticCorpus(
        seed,
        dimensions,
        source_ids,
        tuple(
            SyntheticDocument(
                f"synthetic-memory-{index:06d}",
                source_ids[index % len(source_ids)],
                json.dumps([f"Synthetic retrieval fact {index:06d}."], separators=(",", ":")),
                vector(document_random),
            )
            for index in range(count)
        ),
        tuple(vector(query_random) for _ in range(query_count)),
    )


def cosine(left: Vector, right: Vector) -> float:
    if len(left) != len(right):
        raise ValueError("vector dimensions differ")
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    if not left_norm or not right_norm:
        raise ValueError("zero vector")
    return math.fsum(a * b for a, b in zip(left, right, strict=True)) / left_norm / right_norm
