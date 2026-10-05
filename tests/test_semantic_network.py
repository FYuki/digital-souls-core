"""CI namespaceのargvと権限境界を合成検証。sudoは実行しない。"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import pytest

from evals.semantic import network_namespace as network

pytestmark = pytest.mark.ut


class Executed(Exception):
    pass


@pytest.fixture
def captured(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[tuple[str, list[str], dict[str, str]]]]:
    calls: list[tuple[str, list[str], dict[str, str]]] = []

    def execve(path: str, args: list[str], environment: dict[str, str]) -> NoReturn:
        calls.append((path, args, environment))
        raise Executed

    monkeypatch.setattr(os, "execve", execve)
    for name in tuple(os.environ):
        monkeypatch.delenv(name)
    for name, value in network.HOSTED_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PATH", "/synthetic/node/bin:/usr/bin:/bin")
    monkeypatch.setenv("DSC_PGVECTOR_POC_SOCKET", "/tmp/core-pgvector-poc-synthetic/socket")
    monkeypatch.setenv("DSC_PGVECTOR_POC_PORT", "5432")
    monkeypatch.setenv("DSC_PGVECTOR_POC_DATABASE", "core_pgvector_synthetic")
    monkeypatch.setenv("DSC_PGVECTOR_POC_USER", "core_pgvector_synthetic")
    monkeypatch.setenv("DSC_SEMANTIC_PARENT_NETNS", "net:[101]")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-untrusted-value")
    monkeypatch.setenv("LD_PRELOAD", "synthetic-untrusted-value")
    monkeypatch.setenv("NODE_OPTIONS", "synthetic-untrusted-value")
    monkeypatch.setattr(os, "getuid", lambda: 1001)
    monkeypatch.setattr(os, "geteuid", lambda: 1001)
    monkeypatch.setattr(os, "getgid", lambda: 1002)
    monkeypatch.setattr(os, "getegid", lambda: 1002)
    monkeypatch.setattr(os, "getgroups", lambda: [])
    monkeypatch.setattr(os, "readlink", lambda _: "net:[101]")
    yield calls


def test_hosted_command_drops_identity_and_capabilities_before_checkout_code(
    captured: list[tuple[str, list[str], dict[str, str]]],
) -> None:
    command = ["/bin/bash", "/synthetic/checkout/tools/evaluate-semantic.sh", "--fixture-child"]
    with pytest.raises(Executed):
        network.launch(command, github_hosted=True)
    executable, args, environment = captured[0]
    assert executable == "/usr/bin/sudo"
    assert args[:17] == [
        "/usr/bin/sudo",
        "--non-interactive",
        "--",
        "/usr/bin/env",
        "-i",
        "/usr/bin/unshare",
        "--net",
        "--",
        "/usr/bin/setpriv",
        "--reuid=1001",
        "--regid=1002",
        "--clear-groups",
        "--no-new-privs",
        "--inh-caps=-all",
        "--ambient-caps=-all",
        "--bounding-set=-all",
        "--",
    ]
    assert args[17:19] == ["/usr/bin/env", "-i"]
    python = args.index("/usr/bin/python3")
    assert args[python : python + 3] == ["/usr/bin/python3", "-I", "-B"]
    assert args[python + 4 :] == ["--verify", "1001", "1002", "net:[101]", "--", *command]
    assert "DSC_PGVECTOR_POC_SOCKET=/tmp/core-pgvector-poc-synthetic/socket" in args
    assert not any("untrusted" in value for value in args)
    assert environment == {"PATH": "/usr/bin:/bin"}


@pytest.mark.parametrize("missing", tuple(network.HOSTED_ENV))
def test_explicit_hosted_mode_rejects_missing_hosted_metadata_without_exec(
    captured: list[tuple[str, list[str], dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    monkeypatch.delenv(missing)
    assert network.main(["--github-hosted", "--", "/usr/bin/true"]) == 2
    assert captured == []


@pytest.mark.parametrize("identity", ["getuid", "geteuid", "getgid", "getegid"])
def test_root_or_mixed_identity_never_reaches_sudo(
    captured: list[tuple[str, list[str], dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
    identity: str,
) -> None:
    monkeypatch.setattr(os, identity, lambda: 0)
    assert network.main(["--github-hosted", "--", "/usr/bin/true"]) == 2
    assert captured == []


def test_default_command_preserves_unprivileged_namespace_without_sudo(
    captured: list[tuple[str, list[str], dict[str, str]]],
) -> None:
    with pytest.raises(Executed):
        network.launch(["/usr/bin/true"], github_hosted=False)
    executable, args, environment = captured[0]
    assert executable == "/usr/bin/unshare"
    assert args[:7] == [
        "/usr/bin/unshare",
        "--user",
        "--map-current-user",
        "--net",
        "--",
        "/usr/bin/env",
        "-i",
    ]
    assert args[-1] == "/usr/bin/true" and "/usr/bin/sudo" not in args
    assert not any("untrusted" in value for value in args)
    assert environment == {"PATH": "/usr/bin:/bin"}


def status() -> dict[str, str]:
    return {"NoNewPrivs": "1", **dict.fromkeys(network.CAPABILITIES, "0000000000000000")}


@pytest.mark.parametrize(
    "problem", ["same-namespace", "groups", "uid", "gid", "NoNewPrivs", *network.CAPABILITIES]
)
def test_failed_post_drop_verification_never_executes_payload(
    captured: list[tuple[str, list[str], dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    fields = status()
    monkeypatch.setattr(os, "readlink", lambda _: "net:[202]")
    if problem == "same-namespace":
        monkeypatch.setattr(os, "readlink", lambda _: "net:[101]")
    elif problem == "groups":
        monkeypatch.setattr(os, "getgroups", lambda: [1002])
    elif problem == "uid":
        monkeypatch.setattr(os, "geteuid", lambda: 0)
    elif problem == "gid":
        monkeypatch.setattr(os, "getegid", lambda: 0)
    else:
        fields[problem] = "0" if problem == "NoNewPrivs" else "0000000000000001"
    monkeypatch.setattr(
        Path, "read_text", lambda _: "\n".join(f"{key}: {value}" for key, value in fields.items())
    )
    assert network.main(["--verify", "1001", "1002", "net:[101]", "--", "/usr/bin/true"]) == 2
    assert captured == []


def test_verified_nonroot_payload_receives_only_allowlisted_environment(
    captured: list[tuple[str, list[str], dict[str, str]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "readlink", lambda _: "net:[202]")
    monkeypatch.setattr(
        Path, "read_text", lambda _: "\n".join(f"{key}: {value}" for key, value in status().items())
    )
    with pytest.raises(Executed):
        network.main(["--verify", "1001", "1002", "net:[101]", "--", "/usr/bin/true"])
    assert captured[0][0] == "/usr/bin/true"
    environment = captured[0][2]
    assert environment["DSC_PGVECTOR_POC_DATABASE"] == "core_pgvector_synthetic"
    assert not (
        {"OPENAI_API_KEY", "LD_PRELOAD", "NODE_OPTIONS", "GITHUB_ACTIONS"} & environment.keys()
    )


def test_namespace_failure_is_not_retried_without_isolation(
    captured: list[tuple[str, list[str], dict[str, str]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[str] = []

    def fail(path: str, args: list[str], environment: dict[str, str]) -> NoReturn:
        attempts.append(path)
        raise PermissionError("synthetic namespace denial")

    monkeypatch.setattr(os, "execve", fail)
    assert network.main(["--", "/usr/bin/true"]) == 2
    assert attempts == ["/usr/bin/unshare"]
