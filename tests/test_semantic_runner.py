"""実モデル評価の設定検証だけを合成profileで確認する。接続しない。"""

import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import pytest

from evals.semantic import profile_preflight

pytestmark = pytest.mark.ut


def profile() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile_id": "synthetic",
        "embedding": {
            "profile_id": "synthetic-embedding",
            "model": "synthetic-embedding",
            "model_digest": "synthetic-v1",
            "dimensions": 4,
            "api_base": "http://127.0.0.1:9/v1",
            "enabled": True,
        },
        "chat": {
            "api_base": "http://127.0.0.1:9/v1",
            "model": "synthetic-chat",
            "model_digest": "synthetic-v1",
            "enabled": True,
        },
    }


@pytest.mark.parametrize(
    "change", ["no-chat", "remote", "disabled", "unknown-field", "invalid-json"]
)
def test_invalid_profile_fails_before_any_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    candidate = profile()
    if change == "no-chat":
        candidate["chat"] = None
    elif change == "remote":
        candidate["chat"]["api_base"] = "https://synthetic.invalid/v1"
    elif change == "disabled":
        candidate["embedding"]["enabled"] = False
    elif change == "unknown-field":
        candidate["api_key"] = "synthetic-unwanted-value"
    path = tmp_path / "synthetic-profile.json"
    path.write_text("{" if change == "invalid-json" else json.dumps(candidate))
    monkeypatch.setattr("sys.argv", ["profile_preflight.py", str(path)])
    assert profile_preflight.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "NOT_RUN",
        "reason": "invalid_local_profile",
    }


def test_valid_profile_is_only_configuration_readiness_not_model_quality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "synthetic-profile.json"
    path.write_text(json.dumps(profile()))
    monkeypatch.setattr("sys.argv", ["profile_preflight.py", str(path)])
    assert profile_preflight.main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "READY",
        "scope": "profile_validation_only",
        "inference_calls": 0,
    }


def test_profile_snapshot_fixes_validated_bytes_and_never_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "synthetic-profile.json"
    data = json.dumps(profile()).encode()
    source.write_bytes(data)
    snapshot = tmp_path / "snapshot.json"
    monkeypatch.setattr(
        "sys.argv", ["profile_preflight.py", str(source), "--snapshot", str(snapshot)]
    )
    assert profile_preflight.main() == 0
    assert snapshot.read_bytes() == data
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
    assert json.loads(capsys.readouterr().out)["profile_sha256"] == hashlib.sha256(data).hexdigest()
    source.write_text(json.dumps({**profile(), "profile_id": "synthetic-changed"}))
    assert profile_preflight.main() == 2
    assert snapshot.read_bytes() == data
