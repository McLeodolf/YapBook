"""Authorize an artifact build only for a current, independently approved PR."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from quality.controller import GitHub, assess_pr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", type=int, required=True)
    args = parser.parse_args()
    result = assess_pr(GitHub(os.environ.get("GH_TOKEN", "")), args.pr)
    Path("release-quality-decision.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if result["status"] != "PASS":
        print("Build blocked: all quality checks and current human approvals are required.")
        return 1
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("test_sha=" + result["identity"]["test_sha"] + "\n")
    print("Current approved revision verified for artifact build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
