from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from quality.gate import approvals, classify, evaluate, finding, read_json, traceability

HEAD = "a" * 40
BASE = "b" * 40
NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def fixture():
    policy = json.loads((Path(__file__).parents[1] / "policy.json").read_text())
    policy["reviewers"] = {
        "peer": ["architect"],
        "architecture": ["architect"],
        "security": ["security-reviewer"],
    }
    policy["coverage"]["approval"] = {
        "reviewer": "architect",
        "review_url": "fixture://baseline",
        "revision": BASE,
    }
    identity = {
        "head_sha": HEAD,
        "base_sha": BASE,
        "test_sha": "d" * 40,
        "run_id": "fixture-123",
        "policy_sha": "c" * 64,
        "author": "author",
    }
    record = {
        key: "An explicit fixture-only rationale."
        for key in (
            "summary",
            "requirement",
            "rationale",
            "assumptions",
            "compatibility",
            "verification",
            "operations",
            "rollback",
            "limitations",
            "threat_and_failure_analysis",
        )
    }
    record.update(risk="high", ai_assisted=True, components=["reader"], dependencies=[])
    reports = {
        stage: {
            "schema_version": 1,
            "stage": stage,
            "identity": identity.copy(),
            "status": "PASS",
            "findings": [],
            "tests": 3,
            "skipped": 0,
            "failed": 0,
            "evidence": [],
        }
        for stage in policy["required_stages"]
    }
    reviews = []
    for i, name in enumerate(("architect", "security-reviewer")):
        review = {
            "head_sha": HEAD,
            "decision": "approve",
            "components": ["reader"],
            "risks": "Fixture only",
            "actions": "None",
            "exception_ids": ["EX-1"],
        }
        reviews.append(
            {
                "id": i + 1,
                "user": {"login": name, "type": "User"},
                "state": "APPROVED",
                "commit_id": HEAD,
                "html_url": f"fixture://review/{i}",
                "body": "YAPBOOK-REVIEW\n```json\n" + json.dumps(review) + "\n```",
            }
        )
    return policy, identity, reports, record, reviews


class GateTests(unittest.TestCase):
    def setUp(self):
        self.policy, self.identity, self.reports, self.record, self.reviews = fixture()
        self.paths = ["epub_document.py", "test_html_reader.py"]

    def decision(self, waivers=None):
        return evaluate(
            self.policy,
            self.identity,
            self.reports,
            self.record,
            self.paths,
            self.reviews,
            waivers or [],
            NOW,
        )

    def test_compliant_fixture_passes(self):
        self.assertEqual(self.decision()["status"], "PASS")

    def test_missing_skipped_cancelled_or_empty_report_fails(self):
        for replacement in (
            None,
            {},
            {**self.reports["security"], "status": "SKIPPED"},
            {**self.reports["security"], "status": "cancelled"},
        ):
            with self.subTest(replacement=replacement):
                self.reports["security"] = replacement
                self.assertEqual(self.decision()["status"], "FAIL")

    def test_each_revision_mismatch_fails(self):
        for key in ("head_sha", "base_sha", "test_sha", "policy_sha", "run_id"):
            original = self.reports["security"]["identity"][key]
            self.reports["security"]["identity"][key] = "wrong"
            self.assertEqual(self.decision()["status"], "FAIL")
            self.reports["security"]["identity"][key] = original

    def test_suite_failure_skips_zero_tests_and_boolean_counts_fail(self):
        for field, value in (("tests", 0), ("tests", True), ("failed", 1), ("skipped", 1), ("skipped", None)):
            original = self.reports["desktop-tests"][field]
            self.reports["desktop-tests"][field] = value
            self.assertEqual(self.decision()["status"], "FAIL")
            self.reports["desktop-tests"][field] = original

    def test_pass_cannot_hide_findings(self):
        self.reports["security"]["findings"] = [finding("SEC-SAST", "Fix injection")]
        self.assertEqual(self.decision()["status"], "FAIL")

    def test_fail_without_remediation_is_still_failure(self):
        self.reports["security"]["status"] = "FAIL"
        self.assertTrue(any(f["rule"] == "EVIDENCE" for f in self.decision()["outstanding_actions"]))

    def test_coverage_baseline_needs_approval(self):
        self.policy["coverage"]["approval"] = {}
        self.assertEqual(self.decision()["status"], "FAIL")

    def test_author_bot_unknown_and_stale_review_cannot_approve(self):
        for mutation in (
            {"user": {"login": "author", "type": "User"}},
            {"user": {"login": "architect", "type": "Bot"}},
            {"user": {"login": "outsider", "type": "User"}},
            {"commit_id": BASE},
        ):
            original = deepcopy(self.reviews[0])
            self.reviews[0].update(mutation)
            self.assertEqual(self.decision()["status"], "FAIL")
            self.reviews[0] = original

    def test_later_changes_requested_overrides_old_approval(self):
        self.reviews.append({**self.reviews[0], "id": 999, "state": "CHANGES_REQUESTED"})
        self.assertEqual(self.decision()["status"], "FAIL")

    def test_dismissed_review_is_not_approval(self):
        self.reviews[0]["state"] = "DISMISSED"
        self.assertEqual(self.decision()["status"], "FAIL")

    def test_empty_or_fabricated_architecture_record_fails(self):
        for body in ("LGTM", "YAPBOOK-REVIEW\n```json\n{}\n```", "YAPBOOK-REVIEW\n```json\n{invalid}\n```"):
            self.reviews[0]["body"] = body
            self.assertEqual(self.decision()["status"], "FAIL")

    def test_risk_cannot_be_downgraded(self):
        self.record["risk"] = "low"
        self.assertEqual(self.decision()["status"], "FAIL")
        self.assertEqual(classify(["README.md"], self.policy), "low")
        self.assertEqual(classify(["new_business.py"], self.policy), "medium")
        self.assertEqual(classify([".github/workflows/test.yml"], self.policy), "high")

    def test_dependency_changes_require_rationale(self):
        self.paths.append("web/frontend/package-lock.json")
        self.assertEqual(self.decision()["status"], "FAIL")
        self.record["dependencies"] = [
            {"name": "vite", "reason": "Patch an advisory", "risk": "Rebuild validated"}
        ]
        self.assertEqual(self.decision()["status"], "PASS")

    def waiver(self, rule="SEC-SAST", severity="medium"):
        issue = finding(rule, "Remediation pending", severity=severity)
        self.reports["security"].update(status="FAIL", findings=[issue])
        return {
            "id": "EX-1",
            "rule": rule,
            "fingerprint": issue["fingerprint"],
            "head_sha": HEAD,
            "rationale": "Fixture only",
            "owner": "author",
            "approver": "security-reviewer",
            "compensating_controls": "Feature disabled",
            "created_at": "2026-10-19T00:00:00Z",
            "expires_at": "2026-10-21T00:00:00Z",
        }

    def test_valid_exception_remains_visible_and_preserves_failed_stage(self):
        decision = self.decision([self.waiver()])
        self.assertEqual(decision["status"], "APPROVED EXCEPTION")
        self.assertEqual(decision["stages"]["security"], "FAIL")
        self.assertEqual(decision["exceptions"][0]["id"], "EX-1")

    def test_expired_naive_future_or_excessively_long_exception_fails(self):
        for expiry in ("2026-10-20T00:00:00Z", "2026-10-21", "2030-01-01T00:00:00Z", "invalid"):
            waiver = self.waiver()
            waiver["expires_at"] = expiry
            self.assertEqual(self.decision([waiver])["status"], "FAIL")
        waiver = self.waiver()
        waiver["created_at"] = "2026-10-21T00:00:00Z"
        self.assertEqual(self.decision([waiver])["status"], "FAIL")

    def test_exception_needs_exact_scope_and_independent_explicit_approval(self):
        for field, value in (
            ("fingerprint", "wrong"),
            ("head_sha", BASE),
            ("approver", "author"),
            ("compensating_controls", ""),
        ):
            waiver = self.waiver()
            waiver[field] = value
            self.assertEqual(self.decision([waiver])["status"], "FAIL")

    def test_secrets_malicious_packages_and_critical_issues_cannot_be_waived(self):
        for rule, severity in (("SEC-SECRET", "high"), ("DEP-MALICIOUS", "high"), ("SEC-SAST", "critical")):
            self.assertEqual(self.decision([self.waiver(rule, severity)])["status"], "FAIL")

    def test_exception_commit_is_bound_by_real_review_without_self_referential_file_hash(self):
        waiver = self.waiver()
        del waiver["head_sha"]
        result = self.decision([waiver])
        self.assertEqual(result["status"], "APPROVED EXCEPTION")
        self.assertEqual(result["exceptions"][0]["head_sha"], HEAD)

    def test_duplicate_exception_and_malformed_findings_fail(self):
        waiver = self.waiver()
        self.assertEqual(self.decision([waiver, waiver])["status"], "FAIL")
        self.reports["security"]["findings"] = ["not a finding"]
        self.assertEqual(self.decision()["status"], "FAIL")

    def test_duplicate_keys_and_oversized_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            path.write_text('{"status":"FAIL","status":"PASS"}')
            with self.assertRaises(ValueError):
                read_json(path)
            with self.assertRaises(ValueError):
                read_json(path, maximum=2)

    def test_missing_traceability_and_invalid_paths_fail(self):
        risk, errors = traceability(None, self.paths, self.policy)
        self.assertEqual(risk, "high")
        self.assertTrue(errors)
        with self.assertRaises(ValueError):
            classify(["../escape.py"], self.policy)


if __name__ == "__main__":
    unittest.main()
