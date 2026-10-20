"""Plan, apply and verify branch protection only after reviewed CI bootstrap."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import quote

from quality.controller import GitHub, REPOSITORY
from quality.gate import read_json


def credential() -> str:
    token = os.environ.get("GH_TOKEN")
    if token:
        return token
    # Windows Credential Manager is the existing connection. Never print its output.
    result = subprocess.run(
        ["git", "credential-manager", "get"],
        input="protocol=https\nhost=github.com\nusername=McLeodolf\n\n",
        capture_output=True,
        text=True,
        env={**os.environ, "GCM_INTERACTIVE": "Never", "GIT_TERMINAL_PROMPT": "0"},
        timeout=30,
    )
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if result.returncode or not values.get("password"):
        raise ValueError("Sign in using Windows Git Credential Manager; no token is logged")
    return values["password"]


def policy_ready(policy: dict) -> list[str]:
    errors = []
    if any(not policy["reviewers"].get(role) for role in ("peer", "architecture", "security")):
        errors.append("Designate qualified independent peer, architecture and security reviewers.")
    if len(set(sum(policy["reviewers"].values(), []))) < 2:
        errors.append("High-risk changes require two distinct independent human reviewers.")
    if not all(policy["coverage"]["approval"].get(key) for key in ("reviewer", "review_url", "revision")):
        errors.append("Obtain and record approval for the measured coverage baseline.")
    return errors


def protection_payload(app_id: int, existing: dict | None = None) -> dict:
    existing = existing or {}
    checks = {
        item["context"]: {"context": item["context"], "app_id": item.get("app_id", -1)}
        for item in (existing.get("required_status_checks") or {}).get("checks", [])
    }
    checks["quality/gate"] = {"context": "quality/gate", "app_id": app_id}
    reviews = existing.get("required_pull_request_reviews", {})
    restrictions = existing.get("restrictions")
    if restrictions:
        restrictions = {
            key: [item["login" if key == "users" else "slug"] for item in restrictions.get(key, [])]
            for key in ("users", "teams", "apps")
        }
    return {
        "required_status_checks": {"strict": True, "checks": list(checks.values())},
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": True,
            "required_approving_review_count": max(1, reviews.get("required_approving_review_count", 0)),
            "require_last_push_approval": True,
        },
        "restrictions": restrictions,
        "required_conversation_resolution": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "block_creations": False,
    }


def verify_protection(value: dict, app_id: int) -> list[str]:
    errors = []
    status = value.get("required_status_checks") or {}
    if not status.get("strict") or not any(
        item.get("context") == "quality/gate" and item.get("app_id") == app_id
        for item in status.get("checks", [])
    ):
        errors.append("Required quality/gate check or strict up-to-date validation is missing.")
    for name, expected in (
        ("enforce_admins", True),
        ("allow_force_pushes", False),
        ("allow_deletions", False),
        ("required_conversation_resolution", True),
    ):
        if value.get(name, {}).get("enabled") is not expected:
            errors.append(f"Unexpected {name} setting.")
    reviews = value.get("required_pull_request_reviews") or {}
    for name in ("dismiss_stale_reviews", "require_code_owner_reviews", "require_last_push_approval"):
        if reviews.get(name) is not True:
            errors.append(f"Missing {name} review protection.")
    if reviews.get("required_approving_review_count", 0) < 1 or any(
        (reviews.get("bypass_pull_request_allowances") or {}).values()
    ):
        errors.append("Independent review is missing or a bypass allowance exists.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Activate only after all preflight checks pass")
    parser.add_argument(
        "--evidence-sha", help="Exact head SHA of a recently passing, independently reviewed bootstrap PR"
    )
    args = parser.parse_args()
    policy = read_json(Path("quality/policy.json"))
    errors = policy_ready(policy)
    api = GitHub(credential())
    repository = api.request(f"/repos/{REPOSITORY}")
    if not repository.get("permissions", {}).get("admin"):
        errors.append("Repository administration permission is required.")
    workflows = api.pages(f"/repos/{REPOSITORY}/actions/workflows", "workflows")
    for name in ("quality-evidence.yml", "quality-controller.yml", "quality-review-event.yml"):
        if not any(
            row["path"] == ".github/workflows/" + name and row["state"] == "active" for row in workflows
        ):
            errors.append(f"Publish and execute {name} before requiring its checks.")
    app_id = None
    if args.evidence_sha:
        checks = api.pages(f"/repos/{REPOSITORY}/commits/{args.evidence_sha}/check-runs", "check_runs")
        for check in checks:
            if (
                check["name"] == "quality/gate"
                and check["conclusion"] == "success"
                and check["app"]["slug"] == "github-actions"
            ):
                completed = datetime.fromisoformat(check["completed_at"].replace("Z", "+00:00"))
                if completed > datetime.now(timezone.utc) - timedelta(days=7):
                    app_id = check["app"]["id"]
    if app_id is None:
        errors.append(
            "Supply a passing quality/gate revision from the last seven days; no missing check may be activated as a presumed pass."
        )
    report = {
        "status": "BLOCKED" if errors else "READY",
        "mode": "apply" if args.apply else "read-only preflight",
        "actions": errors,
        "branches": {},
    }
    for branch in policy["protected_branches"]:
        path = f"/repos/{REPOSITORY}/branches/{quote(branch, safe='')}/protection"
        try:
            current = api.request(path)
        except HTTPError as exc:
            if exc.code != 404:
                raise
            current = None
        report["branches"][branch] = {
            "currently_protected": current is not None,
            "proposed": protection_payload(app_id or -1, current),
        }
        if args.apply and not errors:
            api.request(path, "PUT", protection_payload(app_id, current))
            observed = api.request(path)
            failures = verify_protection(observed, app_id)
            report["branches"][branch]["verification"] = failures or "PASS"
            errors.extend(failures)
    if args.apply and not errors:
        api.request(f"/repos/{REPOSITORY}/vulnerability-alerts", "PUT")
        api.request(f"/repos/{REPOSITORY}/automated-security-fixes", "PUT")
        api.request(f"/repos/{REPOSITORY}/vulnerability-alerts")
        security_updates = api.request(f"/repos/{REPOSITORY}/automated-security-fixes")
        if not security_updates.get("enabled"):
            errors.append("Dependabot security updates did not remain enabled.")
        report["status"] = "FAIL" if errors else "VERIFIED"
    destination = Path("test-output/quality-protection.json")
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "actions": errors, "report": str(destination)}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
