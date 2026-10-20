from pathlib import Path
import tempfile
import unittest

from quality.workflows import validate


class WorkflowTests(unittest.TestCase):
    def test_real_templates_satisfy_local_invariants(self):
        self.assertEqual(validate(Path(__file__).resolve().parents[2]), [])

    def test_unpinned_actions_and_untrusted_write_permissions_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workflows = root / ".github/workflows"
            workflows.mkdir(parents=True)
            (workflows / "quality-controller.yml").write_text(
                "name: fixture\non: workflow_dispatch\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo fixture\n"
            )
            candidate = workflows / "quality-evidence.yml"
            candidate.write_text(
                "name: fixture\non:\n  pull_request:\n    paths: ['docs/**']\npermissions:\n  contents: write\njobs:\n  check:\n    permissions:\n      actions: write\n    steps:\n      - uses: actions/checkout@main\n"
            )
            errors = validate(root)
            self.assertEqual(len(errors), 4)
            self.assertTrue(all(item["rule"] == "CI-INTEGRITY" for item in errors))


if __name__ == "__main__":
    unittest.main()
