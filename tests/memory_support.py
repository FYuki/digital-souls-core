import json


def selection(indices: list[int] | None = None, *, kind: str = "semantic") -> str:
    return json.dumps(
        {
            "schema_version": "memory-v1",
            "candidates": [
                {"kind": kind, "basis": "explicit_user_statement", "source_indices": indices or [0]}
            ],
        }
    )
