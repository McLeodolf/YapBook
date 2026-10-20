"""Small local invariants; hosted execution is still required for acceptance."""

from pathlib import Path
import re
import yaml

from quality.gate import finding


def validate(root: Path):
    issues = []
    for path in (root / ".github/workflows").glob("*.yml"):
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        if not isinstance(document, dict) or not document.get("on") or not document.get("jobs"):
            issues.append(finding("CI-INTEGRITY", "Workflow must declare events and jobs.", path.name))
            continue
        for permission, value in document.get("permissions", {}).items():
            if value == "write" and (path.name != "quality-controller.yml" or permission != "checks"):
                issues.append(
                    finding(
                        "CI-INTEGRITY", "Only the protected controller may request checks:write.", path.name
                    )
                )
        for job in document["jobs"].values():
            if job.get("permissions"):
                issues.append(
                    finding(
                        "CI-INTEGRITY",
                        "Job permissions must not override the reviewed workflow boundary.",
                        path.name,
                    )
                )
            for step in job.get("steps", []):
                if "uses" in step and not re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", step["uses"]):
                    issues.append(
                        finding(
                            "CI-INTEGRITY", "Pin reviewed actions to immutable full commit SHAs.", path.name
                        )
                    )
        if path.name == "quality-evidence.yml" and (
            "pull_request" not in document["on"]
            or "paths" in document["on"]["pull_request"]
            or "paths-ignore" in document["on"]["pull_request"]
        ):
            issues.append(
                finding(
                    "CI-INTEGRITY",
                    "Mandatory PR evidence must not be filtered out by changed paths.",
                    path.name,
                )
            )
    if not (root / ".github/workflows/quality-controller.yml").exists():
        issues.append(finding("CI-INTEGRITY", "Missing authoritative controller workflow."))
    return issues
