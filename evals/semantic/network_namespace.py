"""通信不能な評価用namespace。昇格経路は明示したGitHub hosted CIだけに限定。"""

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

HOSTED_ENV = {
    "CI": "true",
    "GITHUB_ACTIONS": "true",
    "RUNNER_ENVIRONMENT": "github-hosted",
    "RUNNER_OS": "Linux",
    "ImageOS": "ubuntu24",
}
ALLOWED_ENV = (
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "DSC_SEMANTIC_PARENT_NETNS",
    "DSC_PGVECTOR_POC_SOCKET",
    "DSC_PGVECTOR_POC_PORT",
    "DSC_PGVECTOR_POC_DATABASE",
    "DSC_PGVECTOR_POC_USER",
)
CAPABILITIES = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")


def clean_environment(environment: Mapping[str, str]) -> dict[str, str]:
    return {name: environment[name] for name in ALLOWED_ENV if name in environment}


def hosted_identity(environment: Mapping[str, str]) -> tuple[int, int]:
    uid, gid = os.getuid(), os.getgid()
    if (
        sys.platform != "linux"
        or uid <= 0
        or gid <= 0
        or os.geteuid() != uid
        or os.getegid() != gid
        or any(environment.get(name) != value for name, value in HOSTED_ENV.items())
    ):
        raise ValueError("Explicit hosted Ubuntu CI with a non-root identity is required")
    return uid, gid


def verify_reduced_identity(uid: int, gid: int, parent_namespace: str) -> None:
    if (
        uid <= 0
        or gid <= 0
        or (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (uid, uid, gid, gid)
        or os.getgroups()
        or not parent_namespace.startswith("net:[")
        or os.readlink("/proc/self/ns/net") == parent_namespace
    ):
        raise ValueError("Namespace identity verification failed")
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if status.get("NoNewPrivs", "").strip() != "1" or any(
        int(status.get(name, "-1"), 16) != 0 for name in CAPABILITIES
    ):
        raise ValueError("Namespace privilege verification failed")


def launch(command: Sequence[str], *, github_hosted: bool) -> None:
    if not command or not os.path.isabs(command[0]):
        raise ValueError("An explicit absolute command is required")
    environment = clean_environment(os.environ)
    assignments = [f"{name}={value}" for name, value in environment.items()]
    if github_hosted:
        uid, gid = hosted_identity(os.environ)
        namespace = os.readlink("/proc/self/ns/net")
        args = [
            "/usr/bin/sudo",
            "--non-interactive",
            "--",
            "/usr/bin/env",
            "-i",
            "/usr/bin/unshare",
            "--net",
            "--",
            "/usr/bin/setpriv",
            f"--reuid={uid}",
            f"--regid={gid}",
            "--clear-groups",
            "--no-new-privs",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--bounding-set=-all",
            "--",
            "/usr/bin/env",
            "-i",
            *assignments,
            "/usr/bin/python3",
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            "--verify",
            str(uid),
            str(gid),
            namespace,
            "--",
            *command,
        ]
        # root実行区間は固定OSコマンドだけ。checkoutのPythonはsetpriv後に初めて実行する。
        os.execve(args[0], args, {"PATH": "/usr/bin:/bin"})
    else:
        args = [
            "/usr/bin/unshare",
            "--user",
            "--map-current-user",
            "--net",
            "--",
            "/usr/bin/env",
            "-i",
            *assignments,
            *command,
        ]
        os.execve(args[0], args, {"PATH": "/usr/bin:/bin"})


def main(arguments: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    try:
        if args == ["--check-github-hosted"]:
            hosted_identity(os.environ)
            return 0
        if args and args[0] == "--verify":
            if len(args) < 6 or args[4] != "--" or not os.path.isabs(args[5]):
                raise ValueError("Invalid verification arguments")
            verify_reduced_identity(int(args[1]), int(args[2]), args[3])
            os.execve(args[5], args[5:], clean_environment(os.environ))
        else:
            hosted = bool(args and args[0] == "--github-hosted")
            if hosted:
                args.pop(0)
            if not args or args.pop(0) != "--":
                raise ValueError("An explicit command separator is required")
            launch(args, github_hosted=hosted)
    except (ValueError, OSError):
        print(
            "FAIL: isolated namespace or reduced identity could not be established.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
