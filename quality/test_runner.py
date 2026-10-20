"""Run unittest with machine-readable counts; a skip is not a green suite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unittest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(args.start, pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "tests": result.testsRun,
                "failed": len(result.errors) + len(result.failures) + len(result.unexpectedSuccesses),
                "skipped": len(result.skipped) + len(result.expectedFailures),
                "failure_tests": [str(case) for case, _ in result.failures + result.errors],
            }
        ),
        encoding="utf-8",
    )
    return (
        0
        if result.wasSuccessful() and result.testsRun and not result.skipped and not result.expectedFailures
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
