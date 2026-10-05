"""明示された実モデル設定を接続前に検証する。推論やDB接続は行わない。"""

import hashlib
import json
import os
import sys
from pathlib import Path

from evals.semantic.models import LocalProfile


def main() -> int:
    try:
        if len(sys.argv) not in (2, 4) or (len(sys.argv) == 4 and sys.argv[2] != "--snapshot"):
            raise ValueError("An explicit profile is required")
        path = Path(sys.argv[1])
        if not path.is_absolute() or path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError("Invalid profile file")
        with path.open("rb") as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise ValueError("Invalid profile size")
        profile = LocalProfile.model_validate_json(data)
        if profile.chat is None:
            raise ValueError("Both mandatory suites require an explicit chat profile")
        result: dict[str, object] = {
            "status": "READY",
            "scope": "profile_validation_only",
            "inference_calls": 0,
        }
        if len(sys.argv) == 4:
            target = Path(sys.argv[3])
            if not target.is_absolute():
                raise ValueError("An absolute snapshot destination is required")
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
            result["profile_sha256"] = hashlib.sha256(data).hexdigest()
    except (ValueError, OSError):
        print(json.dumps({"status": "NOT_RUN", "reason": "invalid_local_profile"}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
