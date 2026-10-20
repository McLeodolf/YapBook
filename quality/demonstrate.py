"""Write clearly labelled positive/negative policy simulations for reviewers."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from quality.gate import evaluate, finding
from quality.tests.test_gate import fixture


def main() -> int:
    policy, identity, reports, record, reviews = fixture()
    cases = []
    for name in ("compliant", "missing_scan", "secret", "stale_approval", "skipped_suite"):
        evidence, approvals = deepcopy(reports), deepcopy(reviews)
        if name == "missing_scan":
            del evidence["security"]
        if name == "secret":
            evidence["security"].update(
                status="FAIL",
                findings=[
                    finding(
                        "SEC-SECRET",
                        "Synthetic credential fixture: remove and rotate",
                        "test_fixture.py",
                        severity="critical",
                    )
                ],
            )
        if name == "stale_approval":
            approvals[0]["commit_id"] = "e" * 40
        if name == "skipped_suite":
            evidence["desktop-tests"]["skipped"] = 1
        result = evaluate(policy, identity, evidence, record, ["epub_document.py"], approvals, [])
        expected = "PASS" if name == "compliant" else "FAIL"
        cases.append(
            {
                "scenario": name,
                "expected": expected,
                "actual": result["status"],
                "rules": sorted({f["rule"] for f in result["outstanding_actions"]}),
            }
        )
    destination = Path("test-output/quality-demonstrations.json")
    destination.parent.mkdir(exist_ok=True)
    data = {
        "scope": "SIMULATION ONLY: synthetic reviewers, approvals and reports; this does not authorize a real PR.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    destination.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data, indent=2))
    return int(any(case["expected"] != case["actual"] for case in cases))


if __name__ == "__main__":
    raise SystemExit(main())
