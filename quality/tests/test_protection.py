from copy import deepcopy
import unittest

from quality.protect import policy_ready, protection_payload, verify_protection
from quality.tests.test_gate import fixture


class ProtectionTests(unittest.TestCase):
    def test_unconfigured_reviewers_and_baseline_block_activation(self):
        policy = fixture()[0]
        self.assertEqual(policy_ready(policy), [])
        policy["reviewers"] = {"peer": [], "architecture": [], "security": []}
        policy["coverage"]["approval"] = {}
        self.assertEqual(len(policy_ready(policy)), 3)

    def test_preserves_stricter_reviews_and_existing_required_checks(self):
        result = protection_payload(
            123,
            {
                "required_status_checks": {"checks": [{"context": "existing", "app_id": 42}]},
                "required_pull_request_reviews": {"required_approving_review_count": 3},
            },
        )
        self.assertEqual(result["required_pull_request_reviews"]["required_approving_review_count"], 3)
        self.assertIn({"context": "existing", "app_id": 42}, result["required_status_checks"]["checks"])
        self.assertTrue(result["enforce_admins"])

    def test_verification_catches_missing_review_and_bypass(self):
        result = protection_payload(123)
        for key in (
            "enforce_admins",
            "allow_force_pushes",
            "allow_deletions",
            "required_conversation_resolution",
        ):
            result[key] = {"enabled": result[key]}
        self.assertEqual(verify_protection(result, 123), [])
        changed = deepcopy(result)
        changed["enforce_admins"]["enabled"] = False
        self.assertTrue(verify_protection(changed, 123))
        changed = deepcopy(result)
        changed["required_pull_request_reviews"]["bypass_pull_request_allowances"] = {"users": ["author"]}
        self.assertTrue(verify_protection(changed, 123))


if __name__ == "__main__":
    unittest.main()
