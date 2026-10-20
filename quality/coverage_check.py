"""Coverage floors and changed-line/branch coverage from actual execution reports."""

from __future__ import annotations

from pathlib import Path
import re

from quality.checks import command
from quality.gate import Json, finding, read_json


def changed_lines(root: Path, base: str) -> dict[str, set[int]]:
    result = command(["git", "diff", "--no-ext-diff", "--unified=0", base, "--"], root)
    if result.returncode:
        raise ValueError("Cannot calculate changed-code coverage against the base revision")
    changes: dict[str, set[int]] = {}
    current = ""
    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            changes.setdefault(current, set())
        elif line.startswith("+++ "):
            current = ""
        elif current and (match := re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)):
            start, count = int(match[1]), int(match[2] or 1)
            changes[current].update(range(start, start + count))
    untracked = command(["git", "ls-files", "--others", "--exclude-standard", "-z"], root)
    if untracked.returncode:
        raise ValueError("Cannot enumerate added files")
    for name in filter(None, untracked.stdout.split("\0")):
        if name.endswith((".py", ".mjs", ".js", ".jsx")):
            changes[name] = set(range(1, len((root / name).read_text(encoding="utf-8").splitlines()) + 1))
    return changes


def percent(covered: int, total: int) -> float:
    return 100.0 * covered / total if total else 100.0


def python_files(path: Path, prefix: str = "") -> dict[str, Json]:
    result = {}
    for name, data in read_json(path)["files"].items():
        name = prefix + name.replace("\\", "/")
        hit = set(data["executed_lines"])
        all_lines = hit | set(data["missing_lines"])
        hit_branches = {tuple(v) for v in data["executed_branches"]}
        all_branches = hit_branches | {tuple(v) for v in data["missing_branches"]}
        result[name] = {
            "lines": all_lines,
            "hit_lines": hit,
            "branches": all_branches,
            "hit_branches": hit_branches,
        }
    return result


def javascript_files(path: Path, root: Path) -> dict[str, Json]:
    result = {}
    for name, data in read_json(path, maximum=30_000_000).items():
        relative = Path(name).resolve().relative_to(root.resolve()).as_posix()
        counts: dict[int, int] = {}
        for key, location in data["statementMap"].items():
            line = location["start"]["line"]
            counts[line] = max(counts.get(line, 0), data["s"][key])
        branches = set()
        hit_branches = set()
        for key, location in data["branchMap"].items():
            for index, count in enumerate(data["b"][key]):
                branch = (location["line"], key, index)
                branches.add(branch)
                if count:
                    hit_branches.add(branch)
        result[relative] = {
            "lines": set(counts),
            "hit_lines": {line for line, count in counts.items() if count},
            "branches": branches,
            "hit_branches": hit_branches,
        }
    return result


def measure(files: dict[str, Json], changes: dict[str, set[int]]) -> Json:
    counts = dict.fromkeys(
        (
            "lines",
            "hit_lines",
            "branches",
            "hit_branches",
            "changed_lines",
            "hit_changed_lines",
            "changed_branches",
            "hit_changed_branches",
        ),
        0,
    )
    for name, file in files.items():
        selected = changes.get(name, set())
        for key in ("lines", "hit_lines", "branches", "hit_branches"):
            counts[key] += len(file[key])
        for key in ("lines", "branches"):
            changed = {value for value in file[key] if (value if key == "lines" else value[0]) in selected}
            counts["changed_" + key] += len(changed)
            counts["hit_changed_" + key] += len(changed & file["hit_" + key])
    return {
        **counts,
        "line": percent(counts["hit_lines"], counts["lines"]),
        "branch": percent(counts["hit_branches"], counts["branches"]),
        "changed_line": percent(counts["hit_changed_lines"], counts["changed_lines"]),
        "changed_branch": percent(counts["hit_changed_branches"], counts["changed_branches"]),
    }


def assess(root: Path, output: Path, base: str, policy: Json) -> tuple[list[Json], Json]:
    changes = changed_lines(root, base)
    components = {
        "desktop": python_files(output / "desktop-coverage.json"),
        "web": python_files(output / "web-coverage.json", "web/"),
        "frontend": javascript_files(root / "web/frontend/test-output/quality-coverage/combined.json", root),
        "governance": python_files(output / "governance-coverage.json"),
    }
    issues = []
    measured = {}
    for component, files in components.items():
        measured[component] = measure(files, changes)
        thresholds = policy["coverage"]["components"].get(component)
        if thresholds is None:
            issues.append(finding("BASELINE", f"Measure and approve the {component} coverage baseline."))
            continue
        if not files or not measured[component]["lines"]:
            issues.append(finding("EVIDENCE", f"{component} coverage contains no executable source."))
        for metric, minimum in thresholds.items():
            actual = measured[component][metric]
            if actual + 1e-9 < minimum:
                issues.append(
                    finding(
                        "COVERAGE",
                        f"{component} {metric}: {actual:.2f}% < {minimum:.2f}%. Add behavioral/negative tests; policy reductions require independent approval.",
                        component,
                        detail=metric,
                    )
                )
    measured_files = {path for files in components.values() for path in files}
    for name in changes:
        production = (
            (name.endswith(".py") and "/" not in name and not name.startswith(("test_", "verify_")))
            or (
                name.startswith("web/")
                and name.endswith(".py")
                and not name.startswith(("web/tests/", "web/frontend/"))
            )
            or name in policy["coverage"]["desktop_sources"]
            or name.startswith("web/frontend/src/")
            or name in ("web/speech_service.py", "web/streamlit_app.py")
        )
        if (
            production
            and name.endswith((".py", ".js", ".jsx", ".mjs"))
            and (root / name).exists()
            and name not in measured_files
        ):
            issues.append(
                finding(
                    "COVERAGE",
                    "Changed production source is absent from coverage; register it and add meaningful tests.",
                    name,
                )
            )
    return issues, {"components": measured, "changed_files": sorted(changes)}
