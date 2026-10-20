from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import unittest
import zipfile

from quality.controller import artifact_bundle, provenance, REPOSITORY, WORKFLOW


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.pr = {"head": {"sha": "h" * 40}, "base": {"sha": "b" * 40}}
        self.run = {
            "id": 123,
            "event": "pull_request",
            "path": WORKFLOW,
            "repository": {"full_name": REPOSITORY},
            "status": "completed",
            "conclusion": "success",
            "head_sha": "h" * 40,
        }
        self.commit = {"sha": "m" * 40, "parents": [{"sha": "b" * 40}, {"sha": "h" * 40}]}
        self.identity = {"head_sha": "h" * 40, "base_sha": "b" * 40, "test_sha": "m" * 40, "run_id": "123"}
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

    def errors(self, workflow=b"approved"):
        return provenance(self.pr, self.run, self.commit, self.identity, {}, workflow, b"approved", self.jobs)

    def test_exact_merge_and_executed_steps_pass_provenance(self):
        self.assertEqual(self.errors(), [])

    def test_wrong_revision_run_repository_or_event_cannot_pass(self):
        for field, value in (
            ("event", "push"),
            ("head_sha", "older"),
            ("id", 122),
            ("repository", {"full_name": "attacker/repo"}),
            ("path", ".github/workflows/fake.yml"),
            ("status", "queued"),
            ("conclusion", "skipped"),
        ):
            with self.subTest(field=field):
                original = deepcopy(self.run)
                self.run[field] = value
                self.assertTrue(self.errors())
                self.run = original

    def test_target_update_and_wrong_test_merge_fail(self):
        self.pr["base"]["sha"] = "c" * 40
        self.assertTrue(self.errors())
        self.pr["base"]["sha"] = "b" * 40
        self.commit["parents"].reverse()
        self.assertTrue(self.errors())

    def test_modified_workflow_cannot_approve_itself(self):
        self.assertTrue(self.errors(b"checks: skipped"))

    def test_missing_expired_or_future_scan_timestamp_fails(self):
        for stamp in (None, "2000-01-01T00:00:00Z", "2999-01-01T00:00:00Z", "invalid"):
            self.run["run_started_at"] = stamp
            # None must also be treated as malformed evidence, not a successful scan.
            if stamp is None:
                del self.run["run_started_at"]
            self.assertTrue(
                provenance(
                    self.pr,
                    self.run,
                    self.commit,
                    self.identity,
                    {"evidence_maximum_hours": 24},
                    b"same",
                    b"same",
                    self.jobs,
                )
            )
        self.run["run_started_at"] = datetime.now(timezone.utc).isoformat()
        self.assertEqual(
            provenance(
                self.pr,
                self.run,
                self.commit,
                self.identity,
                {"evidence_maximum_hours": 24},
                b"same",
                b"same",
                self.jobs,
            ),
            [],
        )

    def test_missing_cancelled_skipped_jobs_and_steps_fail(self):
        original = deepcopy(self.jobs)
        for replacement in (
            [],
            [{"name": "evidence", "status": "in_progress"}],
            [{"name": "evidence", "status": "completed", "steps": []}],
        ):
            self.jobs = replacement
            self.assertTrue(self.errors())
        self.jobs = original
        self.jobs[0]["steps"][1]["conclusion"] = "skipped"
        self.assertTrue(self.errors())

    def test_explicit_failure_has_evidence_not_automatic_success(self):
        self.run["conclusion"] = "failure"
        self.jobs[0]["steps"][1]["conclusion"] = "failure"
        self.assertEqual(self.errors(), [])  # Findings are evaluated separately by gate.evaluate.

    def archive(self, name="bundle.json", text='{"reports": {}}'):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(name, text)
        return stream.getvalue()

    def test_artifact_is_data_and_never_extracted(self):
        self.assertEqual(artifact_bundle(self.archive()), {"reports": {}})
        for name in ("../bundle.json", "/bundle.json", "folder/bundle.json"):
            with self.assertRaises(ValueError):
                artifact_bundle(self.archive(name))

    def test_duplicate_json_keys_invalid_types_and_oversize_fail(self):
        for data in (
            self.archive(text='{"status":"FAIL","status":"PASS"}'),
            self.archive(text="[]"),
            b"x" * 8_000_001,
        ):
            with self.assertRaises(ValueError):
                artifact_bundle(data)


if __name__ == "__main__":
    unittest.main()
