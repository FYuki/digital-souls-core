"""合成 float32 の pgvector exact / Python primitive 比較。実モデル品質は測定しない。"""

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from psycopg import sql

from digital_souls_core.character import AccessScope
from digital_souls_core.history import Binding
from digital_souls_core.memory_contracts import Memory
from digital_souls_core.memory_ranking import EmbeddingSpace, rank_memories

from .store import PgvectorMemoryStore, PocConfig, SearchHit, SourceSnapshot
from .synthetic import SyntheticCorpus, Vector, cosine, make_corpus, vector32

BINDING = Binding(
    AccessScope(subject="synthetic-benchmark", client="synthetic-client"), "synthetic"
)
OTHER_BINDING = Binding(
    AccessScope(subject="synthetic-other-binding", client="synthetic-client"), "synthetic"
)
SCORE_TOLERANCE = 1e-5
POC_TABLES = ("metadata", "sources", "memories", "source_refs", "embeddings")


def timed[T](operation: Callable[[], T]) -> tuple[T, float]:
    started = time.perf_counter_ns()
    result = operation()
    return result, (time.perf_counter_ns() - started) / 1_000_000


def latency_summary(samples: Sequence[float]) -> dict[str, int | float]:
    if not samples or any(not math.isfinite(value) or value < 0 for value in samples):
        raise ValueError("latency samples must be finite, nonnegative, and nonempty")
    ordered = sorted(samples)

    def percentile(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {
        "samples": len(samples),
        "min_ms": ordered[0],
        "p50_ms": percentile(0.5),
        "p95_ms": percentile(0.95),
        "max_ms": ordered[-1],
        "mean_ms": statistics.fmean(samples),
    }


@dataclass(frozen=True)
class Comparison:
    ids_match: bool
    scores_within_tolerance: bool
    max_absolute_score_error: float


def compare_results(
    expected: tuple[tuple[str, float], ...],
    actual: tuple[tuple[str, float], ...],
    tolerance: float = SCORE_TOLERANCE,
) -> Comparison:
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("invalid score tolerance")
    if any(not math.isfinite(score) or not 0 < score <= 1 + tolerance for _, score in actual):
        raise ValueError("invalid positive cosine result")
    ids_match = tuple(mid for mid, _ in expected) == tuple(mid for mid, _ in actual)
    scores = dict(expected)
    errors = [abs(score - scores[mid]) for mid, score in actual if mid in scores]
    maximum = max(errors, default=0.0)
    return Comparison(
        ids_match,
        ids_match and all(error <= tolerance for error in errors),
        maximum,
    )


def _export(store: PgvectorMemoryStore) -> tuple[tuple[Memory, ...], tuple[Vector, ...]]:
    # PostgreSQL's textual float32 output is promoted to float64 by JSON parsing.
    # Quantize again so Python sees the exact same float32 components stored in PG.
    entries = store.export_eligible(BINDING)
    return tuple(row[0] for row in entries), tuple(vector32(row[1]) for row in entries)


def _python_rank(
    entries: tuple[tuple[Memory, ...], tuple[Vector, ...]],
    query: Vector,
    space: EmbeddingSpace,
    limit: int,
) -> tuple[Memory, ...]:
    return rank_memories(entries[0], (query, *entries[1]), space, limit)


def _match(
    expected: tuple[Memory, ...],
    actual: tuple[SearchHit, ...],
    query: Vector,
    corpus: SyntheticCorpus,
) -> Comparison:
    originals = {document.memory_id: document.vector for document in corpus.documents}
    return compare_results(
        tuple(
            (memory.memory_id, cosine(query, originals[memory.memory_id])) for memory in expected
        ),
        tuple((hit.memory_id, hit.score) for hit in actual),
    )


def _load(store: PgvectorMemoryStore, corpus: SyntheticCorpus) -> tuple[float, float]:
    sources = {source_id: SourceSnapshot(source_id, 1, 0) for source_id in corpus.source_ids}

    def register_sources() -> None:
        for source in sources.values():
            store.put_source(BINDING, source)

    _, source_ms = timed(register_sources)
    entries = tuple(
        (document.memory_id, document.text, (sources[document.source_id],), document.vector)
        for document in corpus.documents
    )
    _, load_ms = timed(lambda: store.bulk_load(BINDING, entries))
    return source_ms, load_ms


def _updates(store: PgvectorMemoryStore, corpus: SyntheticCorpus, repeats: int) -> dict[str, Any]:
    document = corpus.documents[0]
    source = SourceSnapshot(document.source_id, 1, 0)
    samples = []
    for index in range(repeats):
        vector = corpus.documents[(index + 1) % len(corpus.documents)].vector

        def update(vector: Vector = vector) -> None:
            store.put_memory(BINDING, document.memory_id, document.text, (source,))
            work = store.prepare(BINDING, document.memory_id)
            if work is None or not store.complete(work, vector):
                raise RuntimeError("synthetic update was not committed")

        _, elapsed = timed(update)
        samples.append(elapsed)
    return {"operation": "put_memory+prepare+complete", **latency_summary(samples)}


def _analyze(store: PgvectorMemoryStore) -> None:
    with store.transaction() as db:
        for table in POC_TABLES:
            db.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(store.config.schema, table)))


def _settings(store: PgvectorMemoryStore) -> dict[str, Any]:
    with store.transaction() as db:
        rows = db.execute(
            "SELECT name,setting,unit FROM pg_settings WHERE name=ANY(%s::text[]) ORDER BY name",
            (
                [
                    "jit",
                    "jit_above_cost",
                    "shared_buffers",
                    "work_mem",
                    "max_parallel_workers_per_gather",
                    "effective_cache_size",
                    "random_page_cost",
                    "seq_page_cost",
                    "default_statistics_target",
                ],
            ),
        ).fetchall()
    return {name: {"setting": setting, "unit": unit} for name, setting, unit in rows}


def plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    relations: set[str] = set()

    def visit(node: dict[str, Any]) -> None:
        counts[str(node["Node Type"])] += 1
        if "Relation Name" in node:
            relations.add(str(node["Relation Name"]))
        for child in node.get("Plans", []):
            visit(child)

    root = plan["Plan"]
    visit(root)
    # Do not emit Filter/Output/Sort Key: they can embed SQL literals or vectors.
    return {
        "node_counts": dict(counts),
        "relations": sorted(relations),
        "root": {
            key: root[key]
            for key in (
                "Actual Rows",
                "Plan Rows",
                "Actual Loops",
                "Total Cost",
                "Shared Hit Blocks",
                "Shared Read Blocks",
                "Temp Read Blocks",
                "Temp Written Blocks",
            )
            if key in root
        },
        "jit": {
            key: plan.get("JIT", {})[key]
            for key in ("Functions", "Timing")
            if key in plan.get("JIT", {})
        },
    }


def _filter_scenario(
    store: PgvectorMemoryStore,
    corpus: SyntheticCorpus,
    space: EmbeddingSpace,
    limit: int,
    repeats: int,
) -> dict[str, Any]:
    query = corpus.queries[0]
    hidden_ids: set[str] = set()
    for name in ("private", "excluded", "deleted"):
        source = SourceSnapshot(f"synthetic-filter-{name}", 1, 0)
        memory_id = f"synthetic-filter-{name}"
        store.put_source(BINDING, source)
        store.bulk_load(BINDING, ((memory_id, '["Synthetic filter marker."]', (source,), query),))
        if name == "private":
            denied = replace(source, epoch=1, private=True)
        elif name == "excluded":
            denied = replace(source, epoch=1, excluded=True)
        else:
            denied = replace(source, epoch=1, deleted=True)
        store.put_source(BINDING, denied)
        hidden_ids.add(memory_id)
    other_source = SourceSnapshot("synthetic-other-source", 1, 0)
    store.put_source(OTHER_BINDING, other_source)
    other_entries = tuple(
        (f"synthetic-other-{index:02d}", '["Synthetic other binding."]', (other_source,), query)
        for index in range(10)
    )
    store.bulk_load(OTHER_BINDING, other_entries)
    hidden_ids.update(entry[0] for entry in other_entries)
    exported = _export(store)
    eligible_ids = {memory.memory_id for memory in exported[0]}
    if eligible_ids != {document.memory_id for document in corpus.documents}:
        raise RuntimeError("synthetic eligible scope differs after filtering")
    reference = _python_rank(exported, query, space, limit)
    samples = []
    for _ in range(repeats):
        result, elapsed = timed(lambda: store.search(BINDING, query, limit))
        if hidden_ids & {hit.memory_id for hit in result}:
            raise RuntimeError("synthetic filter leaked a hidden memory")
        if tuple(hit.memory_id for hit in result) != tuple(item.memory_id for item in reference):
            raise RuntimeError("filtered exact ranking differs")
        samples.append(elapsed)
    return {
        "status": "PASS",
        "private_excluded_deleted_rows": 3,
        "other_binding_rows": 10,
        "eligible_rows": len(exported[0]),
        "hidden_rows_in_export_or_result": 0,
        "roundtrip": latency_summary(samples),
        "note": "Synthetic eligibility projection only; not a production privacy boundary.",
    }


def benchmark_size(
    config: PocConfig,
    *,
    count: int,
    dimensions: int,
    seed: int,
    query_count: int,
    warmup: int,
    repeats: int,
    limit: int,
) -> dict[str, Any]:
    corpus, generation_ms = timed(lambda: make_corpus(count, dimensions, seed, query_count))
    space = EmbeddingSpace("synthetic-float32", "pgvector-benchmark-v1", dimensions)
    store = PgvectorMemoryStore(config, space)
    _, initialize_ms = timed(store.initialize)
    before_run = store.metadata()
    source_ms, load_ms = _load(store, corpus)
    _, analyze_ms = timed(lambda: _analyze(store))
    settings = _settings(store)
    cached, first_export_ms = timed(lambda: _export(store))
    if tuple(memory.memory_id for memory in cached[0]) != tuple(
        document.memory_id for document in reversed(corpus.documents)
    ):
        raise RuntimeError("candidate order must be newest sequence first")
    if cached[1] != tuple(document.vector for document in reversed(corpus.documents)):
        raise RuntimeError("stored vectors differ from synthetic float32 corpus")
    measurements: dict[str, list[float]] = {
        "pg_exact_roundtrip": [],
        "candidate_transfer_and_float32_decode": [],
        "python_rank_after_transfer": [],
        "transfer_plus_python_rank": [],
        "python_rank_cached_candidates": [],
    }
    matches: list[Comparison] = []
    mismatches: list[dict[str, Any]] = []
    for repetition in range(warmup + repeats):
        for query_index, query in enumerate(corpus.queries):

            def postgres(query: Vector = query) -> tuple[tuple[SearchHit, ...], float]:
                return timed(lambda: store.search(BINDING, query, limit))

            def python(query: Vector = query) -> tuple[tuple[Memory, ...], float, float]:
                fetched, fetch_ms = timed(lambda: _export(store))
                ranked, rank_ms = timed(lambda: _python_rank(fetched, query, space, limit))
                return ranked, fetch_ms, rank_ms

            if (repetition + query_index) % 2:
                reference, fetch_ms, python_ms = python()
                result, postgres_ms = postgres()
            else:
                result, postgres_ms = postgres()
                reference, fetch_ms, python_ms = python()

            def cached_python(query: Vector = query) -> tuple[Memory, ...]:
                return _python_rank(cached, query, space, limit)

            cached_result, cached_ms = timed(cached_python)
            if cached_result != reference:
                raise RuntimeError("cached and transferred candidates differ")
            match = _match(reference, result, query, corpus)
            if not match.ids_match or not match.scores_within_tolerance:
                mismatches.append(
                    {
                        "query_index": query_index,
                        "repetition": repetition,
                        "expected_ids": [memory.memory_id for memory in reference],
                        "actual_ids": [hit.memory_id for hit in result],
                        **asdict(match),
                    }
                )
            if repetition < warmup:
                continue
            matches.append(match)
            for name, value in (
                ("pg_exact_roundtrip", postgres_ms),
                ("candidate_transfer_and_float32_decode", fetch_ms),
                ("python_rank_after_transfer", python_ms),
                ("transfer_plus_python_rank", fetch_ms + python_ms),
                ("python_rank_cached_candidates", cached_ms),
            ):
                measurements[name].append(value)
    server_execution, server_planning, plans = [], [], []
    for query in corpus.queries:
        plan = store.explain_search(BINDING, query, limit)
        server_execution.append(float(plan["Execution Time"]))
        server_planning.append(float(plan["Planning Time"]))
        plans.append(plan_summary(plan))
    before_update = store.metadata()
    updates = _updates(store, corpus, repeats)
    after_update = store.metadata()
    filters = _filter_scenario(store, corpus, space, limit, repeats)
    after_run = store.metadata()
    unchanged_start = verify_postmaster(before_run, after_run)
    fingerprint = hashlib.sha256()
    for document in corpus.documents:
        fingerprint.update(json.dumps(document.vector, separators=(",", ":")).encode())
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "rows": count,
        "source_rows": len(corpus.source_ids),
        "dimensions": dimensions,
        "corpus_vectors_sha256": fingerprint.hexdigest(),
        "source_distribution": "round-robin across min(rows,100) synthetic sources",
        "memory_service_limit_exceeded": count > 1000,
        "comparison_boundary": "rank_memories primitive, not MemoryService request latency",
        "synthetic_generation_ms": generation_ms,
        "schema_initialize_ms": initialize_ms,
        "source_registration_ms": source_ms,
        "vector_load_ms": load_ms,
        "analyze_ms": analyze_ms,
        "statistics_policy": (
            "Explicit ANALYZE of five PoC tables before comparison; "
            "cold/fresh statistics and production autoanalyze are NOT RUN."
        ),
        "postgres_settings": settings,
        "first_candidate_export_ms": first_export_ms,
        "latencies": {name: latency_summary(samples) for name, samples in measurements.items()},
        "server_explain_analyze": {
            "execution": latency_summary(server_execution),
            "planning": latency_summary(server_planning),
            "instrumentation_overhead_included": True,
            "repetitions_per_query": 1,
            "plans": plans,
        },
        "equivalence": {
            "queries_verified_including_warmup": query_count * (warmup + repeats),
            "absolute_score_tolerance": SCORE_TOLERANCE,
            "max_absolute_score_error": max(match.max_absolute_score_error for match in matches),
            "mismatches": mismatches,
        },
        "update_cycle": updates,
        "storage_before_update": before_update,
        "storage_after_update": after_update,
        "filter_scenario": filters,
        "postmaster_start_time": unchanged_start,
        "postmaster_unchanged": True,
    }


def verify_postmaster(before: dict[str, Any], after: dict[str, Any]) -> str:
    start = before.get("postmaster_start_time")
    if not isinstance(start, str) or not start or start != after.get("postmaster_start_time"):
        raise RuntimeError("PostgreSQL restart or missing identity: discard all timing samples")
    return start


def source_evidence() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    paths = (
        "experiments/pgvector_memory/benchmark.py",
        "experiments/pgvector_memory/synthetic.py",
        "experiments/pgvector_memory/store.py",
        "experiments/pgvector_memory/schema.py",
        "src/digital_souls_core/memory_ranking.py",
        "uv.lock",
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    return {
        "git_head_base_revision": head,
        "worktree_dirty": dirty,
        "files_sha256": {
            path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths
        },
    }


def _resources() -> dict[str, Any]:
    affinity = sorted(os.sched_getaffinity(0))[:2]
    os.sched_setaffinity(0, affinity)
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    cap = 1024**3 if hard == resource.RLIM_INFINITY else min(1024**3, hard)
    resource.setrlimit(resource.RLIMIT_AS, (cap, hard))
    return {"client_cpu_affinity": affinity, "client_address_space_limit_bytes": cap}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, help="使い捨て PoC DB の Unix socket directory")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="core_pgvector_synthetic")
    parser.add_argument("--user", default="core_pgvector_synthetic")
    parser.add_argument("--schema-prefix", default=f"pgvector_poc_bench_{uuid.uuid4().hex[:8]}")
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 10000])
    parser.add_argument("--dimensions", type=int, choices=[128, 384], default=128)
    parser.add_argument("--seed", type=int, default=20261005)
    parser.add_argument("--queries", type=int, default=8)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (
        not args.sizes
        or len(set(args.sizes)) != len(args.sizes)
        or any(not 1 <= size <= 10000 for size in args.sizes)
        or not 1 <= args.queries <= 16
        or not 0 <= args.warmup <= 10
        or not 1 <= args.repeats <= 50
        or not 1 <= args.limit <= 16
    ):
        parser.error("件数・warmup・反復・limit が実験の上限を超えています")
    constraints = _resources()
    evidence = source_evidence()
    started_at = datetime.now(UTC).isoformat()
    results = [
        benchmark_size(
            PocConfig(
                socket=args.socket,
                port=args.port,
                database=args.database,
                user=args.user,
                schema=f"{args.schema_prefix}_{size}",
            ),
            count=size,
            dimensions=args.dimensions,
            seed=args.seed,
            query_count=args.queries,
            warmup=args.warmup,
            repeats=args.repeats,
            limit=args.limit,
        )
        for size in args.sizes
    ]
    if evidence["files_sha256"] != source_evidence()["files_sha256"]:
        raise RuntimeError(
            "Benchmark source changed during measurement: discard all timing samples"
        )
    report = {
        "status": "PASS" if all(row["status"] == "PASS" for row in results) else "FAIL",
        "mode": "synthetic_pgvector_exact_primitive_benchmark",
        "model_quality_evidence": False,
        "real_embedding_generation": "NOT RUN",
        "hnsw": "NOT RUN",
        "source": evidence,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "psycopg": version("psycopg"),
        "seed": args.seed,
        "query_count": args.queries,
        "warmup_rounds": args.warmup,
        "measured_rounds": args.repeats,
        "limit": args.limit,
        "percentile_method": "linear interpolation at (n-1)*p; no confidence interval",
        "trial_order": "alternate PostgreSQL and transfer+Python by query/repetition parity",
        "resource_limits": constraints,
        "client_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "results": results,
    }
    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
