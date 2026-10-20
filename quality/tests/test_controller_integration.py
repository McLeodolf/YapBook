from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import unittest

from quality.controller import assess_pr, publish, REPOSITORY, WORKFLOW
from quality.tests.test_gate import fixture


class RecordedGitHub:
    """A network-boundary fixture with actual GitHub REST response shapes."""

    def __init__(self):
        self.policy, self.identity, self.reports, self.record, self.reviews = fixture()
        self.identity["run_id"] = "123"
        self.policy_bytes = json.dumps(self.policy).encode()
        self.identity["policy_sha"] = hashlib.sha256(self.policy_bytes).hexdigest()
        for report in self.reports.values():
            report["identity"] = self.identity.copy()
        self.pr = {
            "number": 4,
            "state": "open",
            "user": {"login": "author"},
            "head": {"sha": self.identity["head_sha"]},
            "base": {"sha": self.identity["base_sha"], "ref": "main"},
        }
        self.run = {
            "id": 123,
            "run_started_at": datetime.now(timezone.utc).isoformat(),
            "run_attempt": 1,
            "head_sha": self.identity["head_sha"],
            "event": "pull_request",
            "path": WORKFLOW,
            "status": "completed",
            "conclusion": "success",
            "repository": {"full_name": REPOSITORY},
            "html_url": "https://github.com/McLeodolf/YapBook/actions/runs/123",
        }
        self.artifacts = [{"name": "quality-evidence-123-1", "id": 456, "expired": False}]
        self.workflow = b"approved workflow fixture"
        self.paths = ["epub_document.py", "quality/changes/fixture.json"]
        self.jobs = [
            {
                "name": "evidence",
                "status": "completed",
                "steps": [
                    {"name": name, "conclusion": "success"}
                    for name in (
                        "Install locked dependencies",
                        "Run quality checks",
                        "Upload quality evidence",
                    )
                ],
            }
        ]
        self.requests = []
        self.change_during_review = False
        self.pr_reads = 0

    def request(self, path, method="GET", body=None):
        self.requests.append((path, method, body))
        if method == "POST":
            return {"id": 1}
        if path.endswith("/pulls/4"):
            self.pr_reads += 1
            pr = deepcopy(self.pr)
            if self.change_during_review and self.pr_reads > 1:
                pr["head"]["sha"] = "e" * 40
            return pr
        if "/git/commits/" in path:
            return {
                "sha": self.identity["test_sha"],
                "parents": [{"sha": self.identity["base_sha"]}, {"sha": self.identity["head_sha"]}],
            }
        raise AssertionError("Unexpected API contract " + path)

    def pages(self, path, key=None):
        if "/workflows/quality-evidence.yml/runs?" in path:
            return [self.run]
        if path.endswith("/artifacts"):
            return self.artifacts
        if path.endswith("/jobs"):
            return self.jobs
        if path.endswith("/files"):
            return [{"filename": path} for path in self.paths]
        if path.endswith("/reviews"):
            return self.reviews
        raise AssertionError("Unexpected API pagination contract " + path)

    def file(self, path, revision):
        if path == "quality/policy.json":
            return self.policy_bytes
        if path == WORKFLOW:
            return self.workflow if revision == self.identity["test_sha"] else b"approved workflow fixture"
        if path == "quality/exceptions.json":
            return b"[]"
        if path == "quality/changes/fixture.json":
            return json.dumps(self.record).encode()
        raise AssertionError("Unexpected file contract " + path)

    def artifact(self, artifact_id):
        if artifact_id != 456:
            raise AssertionError("Unexpected artifact identity")
        return {"identity": self.identity.copy(), "reports": deepcopy(self.reports)}


class ControllerIntegrationTests(unittest.TestCase):
    def test_compliant_records_pass_and_publish_expected_check(self):
        api = RecordedGitHub()
        result = assess_pr(api, 4)
        self.assertEqual(result["status"], "PASS")
        publish(api, 4, result)
        body = api.requests[-1][2]
        self.assertEqual(body["name"], "quality/gate")
        self.assertEqual(body["head_sha"], api.identity["head_sha"])
        self.assertEqual(body["conclusion"], "success")

    def test_artifact_cannot_invent_independent_approvals(self):
        api = RecordedGitHub()
        api.reviews = []
        self.assertEqual(assess_pr(api, 4)["status"], "FAIL")

    def test_candidate_cannot_change_workflow_to_skip_scanning(self):
        api = RecordedGitHub()
        api.workflow = b"skipped security checks"
        result = assess_pr(api, 4)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(f["rule"] == "CI-INTEGRITY" for f in result["outstanding_actions"]))

    def test_missing_artifact_or_duplicate_change_record_blocks(self):
        api = RecordedGitHub()
        api.artifacts = []
        with self.assertRaises(ValueError):
            assess_pr(api, 4)
        api = RecordedGitHub()
        api.paths.append("quality/changes/another.json")
        with self.assertRaises(ValueError):
            assess_pr(api, 4)

    def test_force_push_during_controller_reads_cannot_get_stale_approval(self):
        api = RecordedGitHub()
        api.change_during_review = True
        with self.assertRaises(ValueError):
            assess_pr(api, 4)

    def test_approved_exception_does_not_leave_a_timeless_success_check(self):
        api = RecordedGitHub()
        publish(api, 4, {"status": "APPROVED EXCEPTION", "identity": api.identity, "outstanding_actions": []})
        self.assertEqual(api.requests[-1][2]["conclusion"], "failure")
        self.assertIn("merge remains blocked", api.requests[-1][2]["output"]["summary"])


if __name__ == "__main__":
    unittest.main()
