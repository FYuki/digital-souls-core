"""Private stdio scoring bridge for the pinned promptfoo JavaScript adapter."""

import json
import sys
from pathlib import Path
from typing import Any

from .semantic_answer_evaluation import aggregate_answers, score_answer
from .semantic_answer_runtime import runtime_identity
from .semantic_evaluation_cases import load_evaluation_cases
from .semantic_retrieval_evaluation import case_version, execution_commit

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "evals/semantic"


def bridge(request: dict[str, Any]) -> dict[str, Any]:
    data = load_evaluation_cases(EVAL / "cases.json", EVAL / "expectations.json")
    gold = {g.id: g for g in data.expectations.cases}
    op = request["operation"]
    if op == "score":
        return score_answer(gold[request["id"]], request["observation"])
    if op == "batch":
        rows = [score_answer(gold[o["id"]], o) for o in request["observations"]]
        return aggregate_answers(data, rows)
    if op == "manifest":
        return {
            "schema_version": 1,
            "commit": execution_commit(ROOT).model_dump(),
            **runtime_identity(request["mode"], request.get("profile")),
            "case_version": case_version(
                data, EVAL / "cases.json", EVAL / "expectations.json"
            ).model_dump(),
            "promptfoo_version": "0.117.2",
        }
    raise ValueError("Invalid bridge operation")


def main() -> int:
    try:
        request = json.load(sys.stdin)
        result = bridge(request)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception:
        print('{"error":"answer_evaluation_failed"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
