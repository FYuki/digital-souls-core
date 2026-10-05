#!/usr/bin/env python3
"""合成fixtureで検索指標を集計する。実モデルは明示profile時だけ使用する。"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from digital_souls_core.memory_evaluation import (
    EvaluationFixture,
    EvaluationMode,
    FixtureEmbedding,
    evaluate_memory_search,
)
from digital_souls_core.memory_ranking import MemoryEmbedding


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "tests/fixtures/memory-retrieval-evaluation.json",
        help="合成データのみを収めた評価fixtureのJSON",
    )
    parser.add_argument("--profile", type=Path, help="既存ローカルモデルの明示設定JSON")
    parser.add_argument("--k", type=int, default=2)
    args = parser.parse_args()
    try:
        fixture = EvaluationFixture.model_validate_json(args.fixture.read_text(encoding="utf-8"))
        mode: EvaluationMode = "fixture"
        encoder: MemoryEmbedding
        if args.profile is None:
            encoder = FixtureEmbedding(fixture)
        else:
            from digital_souls_core.local_embedding import LocalEmbedding, LocalEmbeddingProfile

            profile = LocalEmbeddingProfile.model_validate(
                json.loads(args.profile.read_text(encoding="utf-8"))
            )
            encoder = LocalEmbedding(profile)
            mode = "local_model"
        result = await evaluate_memory_search(fixture, encoder, k=args.k, mode=mode)
        print(json.dumps(asdict(result), ensure_ascii=False, allow_nan=False, indent=2))
    except Exception:
        # SDK, validation errors and paths can contain input text or credentials.
        print(
            "評価に失敗しました。fixture・profile・ローカルモデル設定を確認してください。",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
