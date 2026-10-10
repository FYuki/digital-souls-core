import json
import os
import subprocess
from pathlib import Path

import pytest

from .support import ROOT

pytestmark = pytest.mark.it1


@pytest.mark.parametrize(
    "uid,load,state,digest,embedding_digest,allowed",
    [
        ("1001", "loaded", "inactive", "valid", "valid", True),
        ("0", "loaded", "inactive", "valid", "valid", False),
        ("1001", "loaded", "active", "valid", "valid", False),
        ("1001", "loaded", "activating", "valid", "valid", False),
        ("1001", "loaded", "failed", "valid", "valid", False),
        ("1001", "not-found", "inactive", "valid", "valid", False),
        ("1001", "loaded", "inactive", "wrong", "valid", False),
        ("1001", "loaded", "inactive", "valid", "wrong", False),
        ("1001", "loaded", "inactive", "valid", "missing", False),
    ],
)
def test_local_start_requires_known_stopped_ollama_and_exact_model(
    tmp_path: Path,
    uid: str,
    load: str,
    state: str,
    digest: str,
    embedding_digest: str,
    allowed: bool,
) -> None:
    # Execute the actual shell guard with inert external commands. No Docker or sudo runs.
    shim = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
if name == "id":
    print(os.environ["TEST_UID"])
elif name == "systemctl":
    assert sys.argv[1:3] == ["show", "digital-souls-ollama.service"]
    key = "TEST_LOAD" if "--property=LoadState" in sys.argv else "TEST_STATE"
    print(os.environ[key])
elif name == "sha256sum":
    expected = "1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606"
    key = "TEST_DIGEST"
    if sys.argv[-1].endswith("embedding.gguf"):
        expected = "aa473d51f451a22f0fcf39ba3330c14bed38a385712b1113440f69df4047a173"
        key = "TEST_EMBEDDING_DIGEST"
    digest = expected if os.environ[key] == "valid" else "wrong"
    print(digest + "  synthetic.gguf")
elif name == "docker":
    with open(os.environ["TEST_CALLS"], "a") as handle:
        handle.write(json.dumps(sys.argv[1:]) + "\\n")
else:
    raise AssertionError(name)
"""
    for name in ("id", "systemctl", "sha256sum", "docker"):
        file = tmp_path / name
        file.write_text(shim)
        file.chmod(0o755)
    calls = tmp_path / "calls.jsonl"
    env = os.environ | {
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "CORE_LLAMACPP_MODEL": str(tmp_path / "synthetic.gguf"),
        "CORE_LLAMACPP_EMBEDDING_MODEL": str(tmp_path / "embedding.gguf"),
        "TEST_EMBEDDING_DIGEST": embedding_digest,
        "TEST_UID": uid,
        "TEST_LOAD": load,
        "TEST_STATE": state,
        "TEST_DIGEST": digest,
        "TEST_CALLS": str(calls),
    }
    if embedding_digest == "missing":
        env.pop("CORE_LLAMACPP_EMBEDDING_MODEL")
    result = subprocess.run(
        ["bash", str(ROOT / "tools/start-llamacpp.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (result.returncode == 0) is allowed
    if allowed:
        invoked = [json.loads(line) for line in calls.read_text().splitlines()]
        assert len(invoked) == 2
        assert invoked[0][-2:] == ["config", "--quiet"]
        assert invoked[1][-5:] == ["up", "-d", "--no-build", "--pull", "never"]
    else:
        assert not calls.exists()
