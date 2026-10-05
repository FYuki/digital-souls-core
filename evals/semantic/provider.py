"""promptfoo 0.117.2 用 entry point。モデル実行は明示 profile のみ。"""

import json
import os
import uuid
from pathlib import Path
from typing import Any, Literal, cast

from psycopg import sql

from evals.semantic.models import Corpus, LocalProfile
from evals.semantic.runtime import Backend, empty_output, evaluate_case
from experiments.pgvector_memory.store import PgvectorMemoryStore, PocConfig


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        config = options.get("config", {})
        if set(config) - {"suite", "mode", "profile_path", "basePath", "pythonExecutable"}:
            raise ValueError("Unsupported provider options")
        if set(context.get("vars", {})) != {"case_id"}:
            raise ValueError("Only case_id is accepted")
        case_id = context["vars"]["case_id"]
        if not isinstance(case_id, str) or prompt != case_id:
            raise ValueError("Case identifier mismatch")
        suite = config.get("suite")
        if suite not in {"retrieval", "answer"}:
            raise ValueError("Unsupported evaluation suite")
        mode = config.get("mode", "offline_fixture")
        profile_path = config.get("profile_path")
        if mode == "offline_fixture":
            if profile_path is not None:
                raise ValueError("Fixture mode does not accept a model profile")
            profile = None
        elif mode == "local_model":
            if not isinstance(profile_path, str) or not Path(profile_path).is_absolute():
                raise ValueError("Explicit absolute model profile required")
            profile = LocalProfile.model_validate_json(
                Path(profile_path).read_text(encoding="utf-8")
            )
        else:
            raise ValueError("Unsupported evaluation mode")
        if suite == "answer" and profile is not None and profile.chat is None:
            raise ValueError("The answer suite needs an explicit chat profile")
        corpus = Corpus.model_validate_json(
            Path(__file__).with_name("cases.json").read_text(encoding="utf-8")
        )
        case = next(item for item in corpus.cases if item.id == case_id)
        backend = Backend(profile)
        if case.binding.audience != "local-private":
            # Exercise the same explicit unsupported-audience boundary, before any I/O.
            try:
                case.binding.binding()
            except ValueError:
                output = empty_output(case, backend, suite)
                output["input_rejected"] = True
                return {"output": json.dumps(output, ensure_ascii=False, allow_nan=False)}
            raise RuntimeError("Unsupported audience was accepted")
        if any(name.startswith("PG") and value for name, value in os.environ.items()):
            raise ValueError("Inherited libpq configuration is not permitted")
        connection = PocConfig(
            socket=os.environ["DSC_PGVECTOR_POC_SOCKET"],
            port=int(os.environ.get("DSC_PGVECTOR_POC_PORT", "5432")),
            database=os.environ.get("DSC_PGVECTOR_POC_DATABASE", "core_pgvector_synthetic"),
            user=os.environ.get("DSC_PGVECTOR_POC_USER", "core_pgvector_synthetic"),
            schema=f"pgvector_poc_eval_{uuid.uuid4().hex}",
        )
        store = PgvectorMemoryStore(connection, backend.space)
        store.initialize()
        try:
            output = evaluate_case(
                case, backend, cast(Literal["retrieval", "answer"], suite), store
            )
        finally:
            with store.transaction() as db:
                db.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(connection.schema))
                )
        return {"output": json.dumps(output, ensure_ascii=False, allow_nan=False)}
    except Exception:
        # Never disclose provider/profile/input/HTTP bodies in error reports.
        return {"error": "semantic_evaluation_failed"}
