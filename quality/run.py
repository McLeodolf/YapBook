"""Run repository checks locally or in an unprivileged CI job. No publishing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

from quality import checks, coverage_check
from quality.gate import Json, evaluate, finding, read_json, traceability


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def git(root: Path, *args: str) -> str:
    result = checks.command(["git", *args], root)
    if result.returncode:
        raise ValueError("Git could not determine the revision or changed files")
    return result.stdout.strip()


def changed_paths(root: Path, base: str) -> list[str]:
    tracked = git(root, "diff", "--name-only", "-z", base, "--").split("\0")
    added = git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return sorted(set(filter(None, tracked + added)))


def change_record(root: Path, paths: list[str]) -> Json:
    candidates = [
        p for p in paths if p.startswith("quality/changes/") and p.endswith(".json") and (root / p).is_file()
    ]
    if len(candidates) != 1:
        raise ValueError("Add or update exactly one quality/changes/*.json record for this change")
    return read_json(root / candidates[0])


def run_checked(
    args: list[str], root: Path, label: str, timeout: int = 240, env: dict[str, str] | None = None
) -> list[Json]:
    result = checks.command(args, root, timeout=timeout, env=env)
    if result.returncode:
        # Do not publish raw child output: assertions and linters can quote credentials.
        return [
            finding(
                "CHECK",
                f"{label} failed (exit {result.returncode}). Run the documented {label} command locally to see diagnostics.",
            )
        ]
    return []


def code(root: Path, output: Path, policy: Json, controls: Path) -> tuple[list[Json], Json]:
    from quality.workflows import validate

    issues = validate(root)
    issues += run_checked(
        [sys.executable, "-m", "ruff", "check", "--config", str(controls / "quality/ruff.toml"), "."],
        root,
        "Python lint",
    )
    issues += run_checked(
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--check",
            "--config",
            str(controls / "quality/ruff.toml"),
            "quality",
        ],
        root,
        "gate formatting",
    )
    issues += run_checked(
        [sys.executable, "-m", "mypy", "--config-file", str(controls / "quality/mypy.ini")],
        root,
        "gate type checking",
    )
    issues += run_checked(
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            *policy["coverage"]["desktop_sources"],
            "web/speech_service.py",
            "web/streamlit_app.py",
            "quality",
        ],
        root,
        "Python compilation",
    )
    frontend = root / "web/frontend"
    issues += run_checked(["npm", "run", "lint"], frontend, "JavaScript lint")
    with tempfile.TemporaryDirectory(prefix="yapbook-build-check-") as folder:
        destination = Path(folder) / "dist"
        build = run_checked(
            ["npm", "run", "build", "--", "--outDir", str(destination)], frontend, "frontend build"
        )
        issues += build
        if not build:

            def digests(directory: Path) -> dict[str, str]:
                return {
                    p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in directory.rglob("*")
                    if p.is_file()
                }

            if digests(destination) != digests(frontend / "dist"):
                issues.append(
                    finding(
                        "BUILD",
                        "Committed frontend dist differs from a fresh build. Run npm run build and include the regenerated bundle.",
                        "web/frontend/dist",
                    )
                )
    return issues, {
        "type_check_scope": "quality/gate.py (strict); existing app is not fully annotated",
        "format_scope": "quality/*.py; production lint is incremental bug detection",
    }


def python_suite(root: Path, output: Path, name: str, policy: Json) -> tuple[list[Json], Json]:
    coverage_file = output / (name + ".coverage")
    counts = output / (name + "-tests.json")
    cwd = root / "web" if name == "web" else root
    start = "tests" if name == "web" else "quality/tests" if name == "governance" else "."
    sources = (
        "speech_service,streamlit_app"
        if name == "web"
        else ",".join(
            str(Path(p).with_suffix("")).replace("\\", ".").replace("/", ".")
            for p in policy["coverage"]["governance_sources"]
        )
        if name == "governance"
        else ",".join(Path(p).stem for p in policy["coverage"]["desktop_sources"])
    )
    if name == "desktop":
        extra = [
            Path(p).stem
            for p in checks.source_files(root)
            if p.endswith(".py") and "/" not in p and not p.startswith(("test_", "verify_"))
        ]
        sources = ",".join(sorted(set(sources.split(",") + extra)))
    env = {"COVERAGE_FILE": str(coverage_file), "PYTHONPATH": str(root)}
    args = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--branch",
        "--source=" + sources,
        "-m",
        "quality.test_runner",
        "--start",
        start,
        "--output",
        str(counts),
    ]
    issues = run_checked(args, cwd, name + " tests", env=env)
    if name == "desktop":
        issues += run_checked(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--append",
                "--branch",
                "--source=" + sources,
                "gui_entry.py",
                "--self-test",
                str(output / "gui-self-test.txt"),
            ],
            root,
            "GUI self-test",
            env=env,
        )
    issues += run_checked(
        [sys.executable, "-m", "coverage", "json", "-o", str(output / (name + "-coverage.json"))],
        cwd,
        name + " coverage",
        env=env,
    )
    data = read_json(counts)
    return issues, data


def frontend_tests(root: Path, output: Path) -> tuple[list[Json], Json]:
    frontend = root / "web/frontend"
    report = frontend / "test-output/node-tests.xml"
    report.unlink(missing_ok=True)
    issues = run_checked(["npm", "run", "test:coverage"], frontend, "Node tests")
    # The parser is used only in the unprivileged test process, with a bounded local output.
    if report.stat().st_size > 4_000_000:
        raise ValueError("Oversized Node test report")
    document = ET.fromstring(report.read_bytes())
    cases = document.findall(".//testcase")
    return issues, {
        "tests": len(cases),
        "failed": sum(bool(c.findall("failure") or c.findall("error")) for c in cases),
        "skipped": sum(bool(c.findall("skipped")) for c in cases),
    }


def browser_tests(root: Path, output: Path) -> tuple[list[Json], Json]:
    frontend = root / "web/frontend"
    directory = frontend / "test-output/browser-coverage"
    directory.mkdir(parents=True, exist_ok=True)
    # Only delete generated JSON in this exact directory; stale coverage must never pass.
    for path in directory.glob("*.json"):
        if path.resolve().parent != directory.resolve():
            raise ValueError("Unexpected browser coverage path")
        path.unlink()
    report = frontend / "test-output/quality-browser.json"
    report.unlink(missing_ok=True)
    issues = run_checked(["npm", "run", "test:browser"], frontend, "browser tests")
    data = read_json(report)
    stats = data["stats"]
    issues += run_checked(["npm", "run", "coverage:merge"], frontend, "frontend coverage merge")
    return issues, {
        "tests": stats["expected"] + stats["unexpected"] + stats["skipped"] + stats["flaky"],
        "failed": stats["unexpected"] + stats["flaky"],
        "skipped": stats["skipped"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--controls", type=Path)
    parser.add_argument("--output", type=Path, default=Path("test-output/quality-current"))
    parser.add_argument(
        "--stage",
        choices=[
            "all",
            "security",
            "dependencies",
            "code",
            "desktop-tests",
            "web-tests",
            "frontend-tests",
            "browser-tests",
            "governance-tests",
            "coverage",
            "traceability",
        ],
        default="all",
    )
    args = parser.parse_args()
    root = Path.cwd().resolve()
    controls = args.controls.resolve() if args.controls else root
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    policy = read_json(controls / "quality/policy.json")
    policy_sha = hashlib.sha256(
        (controls / "quality/policy.json").read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    head, base = git(root, "rev-parse", "HEAD"), git(root, "rev-parse", args.base)
    identity = (
        read_json(args.identity)
        if args.identity
        else {
            "head_sha": head,
            "test_sha": head,
            "base_sha": base,
            "policy_sha": policy_sha,
            "run_id": "local-" + datetime.now(timezone.utc).isoformat(),
            "author": "local author",
            "local_dirty": bool(git(root, "status", "--porcelain")),
        }
    )
    if identity["policy_sha"] != policy_sha:
        raise ValueError("Executing policy differs from the declared trusted policy digest")
    paths = changed_paths(root, base)
    try:
        record = change_record(root, paths)
    except ValueError:
        record = {}
    reports: dict[str, Json] = {}
    actions = {
        "security": lambda: (lambda issues, data: (issues + checks.scanner_fixtures(root, controls), data))(
            *checks.security(root, output, policy, controls)
        ),
        "dependencies": lambda: checks.dependencies(root, output, policy),
        "code": lambda: code(root, output, policy, controls),
        "desktop-tests": lambda: python_suite(root, output, "desktop", policy),
        "web-tests": lambda: python_suite(root, output, "web", policy),
        "frontend-tests": lambda: frontend_tests(root, output),
        "browser-tests": lambda: browser_tests(root, output),
        "governance-tests": lambda: python_suite(root, output, "governance", policy),
        "coverage": lambda: coverage_check.assess(root, output, base, policy),
        "traceability": lambda: (traceability(record, paths, policy)[1], {"change_record": record}),
    }
    for stage, action in actions.items():
        if args.stage not in ("all", stage):
            continue
        print(f"Running {stage}...", flush=True)
        try:
            issues, data = action()
        except Exception as exc:
            # Exception strings from tools may include source/credentials; expose class only.
            issues, data = (
                [
                    finding(
                        "EVIDENCE",
                        f"{stage} could not produce evidence ({type(exc).__name__}). Run that stage locally using the operations guide.",
                    )
                ],
                {},
            )
        report = {
            "schema_version": 1,
            "stage": stage,
            "identity": identity,
            "status": "FAIL" if issues else "PASS",
            "findings": issues,
            "evidence": [f"{stage}.json"],
            **data,
        }
        if stage in policy["test_stages"] and (
            report.get("tests", 0) <= 0 or report.get("skipped", 1) or report.get("failed", 1)
        ):
            report["findings"].append(
                finding("TEST", "Suite must execute a nonzero number of tests with zero skips and failures.")
            )
            report["status"] = "FAIL"
        reports[stage] = report
        write(output / (stage + ".json"), report)
        print(f"{stage}: {report['status']} ({len(report['findings'])} finding(s))", flush=True)
    if args.stage != "all":
        return int(any(r["status"] != "PASS" for r in reports.values()))
    decision = evaluate(
        policy, identity, reports, record, paths, [], read_json(root / "quality/exceptions.json")
    )
    decision["scope"] = "Local preview; actual GitHub approvals are checked only by the trusted controller."
    write(output / "decision.json", decision)
    write(output / "bundle.json", {"identity": identity, "reports": reports})
    print(f"Overall: {decision['status']}; report: {output / 'decision.json'}")
    return (
        int(any(r["status"] != "PASS" for r in reports.values()))
        if args.identity
        else int(decision["status"] == "FAIL")
    )


if __name__ == "__main__":
    sys.exit(main())
