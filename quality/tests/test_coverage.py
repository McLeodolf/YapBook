import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from quality.coverage_check import changed_lines, javascript_files, measure, python_files
from quality.checks import parse_lock


class CoverageTests(unittest.TestCase):
    def test_changed_branch_coverage_catches_untested_error_path(self):
        files = {
            "logic.py": {
                "lines": {1, 2, 3, 4},
                "hit_lines": {1, 2, 4},
                "branches": {(2, 3), (2, 4)},
                "hit_branches": {(2, 4)},
            }
        }
        result = measure(files, {"logic.py": {2, 3}})
        self.assertEqual(result["line"], 75)
        self.assertEqual(result["branch"], 50)
        self.assertEqual(result["changed_line"], 50)
        self.assertEqual(result["changed_branch"], 50)
        self.assertEqual(result["changed_branches"], 2)

    def test_unchanged_files_do_not_inflate_changed_coverage(self):
        files = {
            "changed.py": {"lines": {1}, "hit_lines": set(), "branches": set(), "hit_branches": set()},
            "unchanged.py": {
                "lines": set(range(100)),
                "hit_lines": set(range(100)),
                "branches": set(),
                "hit_branches": set(),
            },
        }
        self.assertEqual(measure(files, {"changed.py": {1}})["changed_line"], 0)

    def test_real_git_diff_includes_new_untracked_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def git(*args):
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

            git("init", "-q")
            (root / "logic.py").write_text("a = 1\nb = 2\n")
            git("add", "logic.py")
            git(
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            )
            (root / "logic.py").write_text("a = 1\nb = 3\nraise ValueError()\n")
            (root / "new.py").write_text("first = 1\nsecond = 2\n")
            changes = changed_lines(root, "HEAD")
            self.assertEqual(changes["logic.py"], {2, 3})
            self.assertEqual(changes["new.py"], {1, 2})

    def test_python_report_adapter_retains_missing_branches(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "coverage.json"
            path.write_text(
                json.dumps(
                    {
                        "files": {
                            "logic.py": {
                                "executed_lines": [1, 2],
                                "missing_lines": [3],
                                "executed_branches": [[2, 1]],
                                "missing_branches": [[2, 3]],
                            }
                        }
                    }
                )
            )
            data = python_files(path, "web/")
            self.assertEqual(data["web/logic.py"]["branches"], {(2, 1), (2, 3)})

    def test_javascript_report_adapter_counts_each_branch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "coverage.json"
            path.write_text(
                json.dumps(
                    {
                        str(root / "logic.mjs"): {
                            "statementMap": {"0": {"start": {"line": 1}}, "1": {"start": {"line": 2}}},
                            "s": {"0": 1, "1": 0},
                            "branchMap": {"0": {"line": 1}},
                            "b": {"0": [1, 0]},
                        }
                    }
                )
            )
            result = measure(javascript_files(path, root), {"logic.mjs": {1, 2}})
            self.assertEqual(result["changed_line"], 50)
            self.assertEqual(result["changed_branch"], 50)

    def test_dependency_lock_rejects_missing_hashes_ranges_and_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "requirements.txt"
            good = "example-package==1.2.3 --hash=sha256:" + "a" * 64
            path.write_text(good)
            self.assertEqual(parse_lock(path), {"example-package": "1.2.3"})
            for text in (
                "example-package>=1.2",
                "example-package==1.2.3",
                "--extra-index-url https://unapproved.invalid\n" + good,
                "git+https://unapproved.invalid/project",
                "",
            ):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    parse_lock(path)


if __name__ == "__main__":
    unittest.main()
