"""Invoke only the target branch's runner, independent of PR Python imports."""

import hashlib
import json
import os
from pathlib import Path
import re
import sys

CONTROLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONTROLS))
from quality.run import main


if __name__ == "__main__":
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    pr = event["pull_request"]
    values = {
        "head_sha": pr["head"]["sha"],
        "base_sha": pr["base"]["sha"],
        "test_sha": os.environ["GITHUB_SHA"],
    }
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in values.values()):
        raise ValueError("Unexpected revision identity")
    values.update(
        policy_sha=hashlib.sha256(
            (CONTROLS / "quality/policy.json").read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        run_id=os.environ["GITHUB_RUN_ID"],
        author=pr["user"]["login"],
        local_dirty=False,
    )
    destination = Path("test-output/ci-identity.json")
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(values), encoding="utf-8")
    sys.argv = [
        sys.argv[0],
        "--base",
        values["base_sha"],
        "--identity",
        str(destination),
        "--controls",
        str(CONTROLS),
    ]
    sys.exit(main())
