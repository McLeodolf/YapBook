"""Pure policy decisions. External reports never execute code here."""

from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import hashlib
import json
from pathlib import Path
import re
from typing import Any

Json = dict[str, Any]
RISK = {"low": 0, "medium": 1, "high": 2}
REVIEW_MARKER = "YAPBOOK-REVIEW"


def read_json(path: Path, maximum: int = 8_000_000) -> Any:
    data = path.read_bytes()
    if len(data) > maximum:
        raise ValueError(f"Report exceeds {maximum} bytes: {path.name}")

    def unique(pairs: list[tuple[str, Any]]) -> Json:
        result: Json = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(data, object_pairs_hook=unique)


def fingerprint(rule: str, path: str, detail: str) -> str:
    return hashlib.sha256(f"{rule}\0{path}\0{detail}".encode()).hexdigest()


def finding(
    rule: str,
    message: str,
    path: str = "",
    *,
    severity: str = "high",
    owner: str = "author",
    detail: str = "",
) -> Json:
    return {
        "rule": rule,
        "message": message,
        "path": path,
        "severity": severity,
        "owner": owner,
        "fingerprint": fingerprint(rule, path, detail or message),
    }


def classify(paths: list[str], policy: Json) -> str:
    rank = 0
    for path in paths:
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise ValueError("Invalid changed-file path")
        matches = [
            RISK[risk]
            for risk, patterns in policy["risk_paths"].items()
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
        ]
        rank = max(rank, max(matches, default=1))
    return next(name for name, value in RISK.items() if value == rank)


def traceability(record: Any, paths: list[str], policy: Json) -> tuple[str, list[Json]]:
    minimum = classify(paths, policy)
    errors: list[Json] = []
    if not isinstance(record, dict):
        return minimum, [finding("TRACE", "Add one structured change record for this PR.")]
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
    ):
        value = record.get(key)
        if (
            not isinstance(value, str)
            or not value.strip()
            or re.search(r"\b(TODO|TBD|fill me)\b", value, re.I)
        ):
            errors.append(finding("TRACE", f"Provide a concrete {key} in the change record."))
    declared = record.get("risk")
    if declared not in RISK or RISK[declared] < RISK[minimum]:
        errors.append(finding("RISK", f"Declared risk must be at least {minimum}."))
    else:
        minimum = declared
    if type(record.get("ai_assisted")) is not bool:
        errors.append(finding("TRACE", "Declare ai_assisted as true or false."))
    if not isinstance(record.get("components"), list) or not record["components"]:
        errors.append(finding("TRACE", "Identify affected components."))
    deps = record.get("dependencies")
    if not isinstance(deps, list):
        errors.append(finding("TRACE", "Record dependency changes as a list; use [] only when none changed."))
    elif (
        any(any(fnmatch.fnmatchcase(p, pattern) for pattern in policy["dependency_paths"]) for p in paths)
        and not deps
    ):
        errors.append(
            finding(
                "TRACE", "Dependency files changed; describe each addition, removal or upgrade and its risks."
            )
        )
    for item in deps if isinstance(deps, list) else []:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(k), str) and item[k].strip() for k in ("name", "reason", "risk")
        ):
            errors.append(finding("TRACE", "Every dependency change needs name, reason and risk."))
    if minimum == "high" and not record.get("threat_and_failure_analysis"):
        errors.append(finding("ARCH", "High-risk changes need threat/failure analysis and a rollback plan."))
    return minimum, errors


def review_record(body: str) -> Json | None:
    match = re.search(r"YAPBOOK-REVIEW\s*```json\s*(\{.*?\})\s*```", body, re.S)
    if not match:
        return None
    try:
        value = json.loads(match.group(1))
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def approvals(
    reviews: list[Json], author: str, head: str, risk: str, policy: Json
) -> tuple[list[Json], list[Json]]:
    latest: dict[str, Json] = {}
    for review in sorted(reviews, key=lambda row: row.get("id", 0)):
        if review.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[review.get("user", {}).get("login", "")] = review
    accepted: list[Json] = []
    errors: list[Json] = []
    for login, review in latest.items():
        if review["state"] == "CHANGES_REQUESTED":
            errors.append(
                finding("ARCH", f"Resolve {login}'s requested changes and obtain a new review.", owner=login)
            )
        if review["state"] != "APPROVED" or login.casefold() == author.casefold():
            continue
        if review.get("user", {}).get("type") != "User" or review.get("commit_id") != head:
            continue
        roles = [
            role
            for role, users in policy["reviewers"].items()
            if login.casefold() in [u.casefold() for u in users]
        ]
        if not roles:
            continue
        record = review_record(review.get("body", ""))
        if not record or record.get("head_sha") != head or record.get("decision") != "approve":
            continue
        if not all(record.get(key) for key in ("components", "risks", "actions")):
            continue
        accepted.append(
            {
                "reviewer": login,
                "roles": roles,
                "record": record,
                "url": review.get("html_url", ""),
                "review_id": review["id"],
            }
        )
    required = policy["reviews"][risk]
    if len(accepted) < required["count"]:
        errors.append(
            finding(
                "ARCH",
                f"Need {required['count']} independent designated human approval(s) for {risk} risk, on {head}.",
                owner="repository owner",
            )
        )
    for role in required["roles"]:
        if not any(role in review["roles"] for review in accepted):
            errors.append(
                finding(
                    "ARCH",
                    f"A designated {role} reviewer must approve this exact commit.",
                    owner="repository owner",
                )
            )
    return accepted, errors


def exceptions(
    findings: list[Json], records: Any, reviews: list[Json], head: str, now: datetime, policy: Json
) -> tuple[list[Json], list[Json]]:
    if not isinstance(records, list):
        return findings + [finding("EXCEPTION", "Exception records must be a list.")], []
    outstanding = list(findings)
    accepted: list[Json] = []
    seen: set[str] = set()
    for record in records:
        required = (
            "id",
            "rule",
            "fingerprint",
            "rationale",
            "owner",
            "approver",
            "compensating_controls",
            "expires_at",
            "created_at",
        )
        if not isinstance(record, dict) or not all(
            isinstance(record.get(k), str) and record[k].strip() for k in required
        ):
            outstanding.append(
                finding("EXCEPTION", "An exception is missing required accountable, scoped fields.")
            )
            continue
        identifier = record["id"]
        if identifier in seen:
            outstanding.append(finding("EXCEPTION", f"Duplicate exception ID {identifier}."))
            continue
        seen.add(identifier)
        try:
            expiry = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
            created = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
            valid = bool(
                expiry.tzinfo
                and created.tzinfo
                and created <= now < expiry
                and (expiry - created).total_seconds() <= policy["exceptions"]["maximum_days"] * 86400
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            outstanding.append(
                finding(
                    "EXCEPTION",
                    f"Exception {identifier} is expired, future-dated or exceeds the permitted duration.",
                    owner=record["owner"],
                )
            )
            continue
        if record.get("head_sha", head) != head:
            outstanding.append(finding("EXCEPTION", f"Exception {identifier} does not cover this commit."))
            continue
        approver = next(
            (
                r
                for r in reviews
                if r["reviewer"].casefold() == record["approver"].casefold()
                and "security" in r["roles"]
                and identifier in r["record"].get("exception_ids", [])
            ),
            None,
        )
        if not approver or record["owner"].casefold() == record["approver"].casefold():
            outstanding.append(
                finding("EXCEPTION", f"Exception {identifier} needs explicit independent security approval.")
            )
            continue
        matched = [
            f
            for f in outstanding
            if f["rule"] == record["rule"] and f["fingerprint"] == record["fingerprint"]
        ]
        if not matched:
            outstanding.append(
                finding("EXCEPTION", f"Exception {identifier} does not match a current finding.")
            )
        elif any(
            f["severity"] == "critical" or f["rule"] in policy["exceptions"]["non_waivable"] for f in matched
        ):
            outstanding.append(
                finding("EXCEPTION", f"Exception {identifier} attempts to waive a prohibited rule.")
            )
        else:
            outstanding = [f for f in outstanding if f not in matched]
            accepted.append({**record, "head_sha": head, "review_url": approver["url"], "findings": matched})
    return outstanding, accepted


def evaluate(
    policy: Json,
    identity: Json,
    reports: dict[str, Any],
    record: Any,
    paths: list[str],
    reviews: list[Json],
    waiver_records: Any,
    now: datetime | None = None,
) -> Json:
    now = now or datetime.now(timezone.utc)
    errors: list[Json] = []
    stages: Json = {}
    risk, trace_errors = traceability(record, paths, policy)
    errors.extend(trace_errors)
    for stage in policy["required_stages"]:
        report = reports.get(stage)
        if not isinstance(report, dict):
            errors.append(finding("EVIDENCE", f"Missing {stage} report; rerun that stage."))
            stages[stage] = "MISSING"
            continue
        if report.get("schema_version") != 1 or report.get("stage") != stage:
            errors.append(finding("EVIDENCE", f"Invalid {stage} report schema."))
        for key in ("head_sha", "base_sha", "test_sha", "policy_sha", "run_id"):
            if not identity.get(key) or report.get("identity", {}).get(key) != identity[key]:
                errors.append(
                    finding(
                        "REVISION",
                        f"{stage} evidence does not match {key}; rerun against the current revision.",
                    )
                )
        status = report.get("status")
        stages[stage] = status
        stage_findings = report.get("findings")
        if not isinstance(stage_findings, list) or any(
            not isinstance(f, dict)
            or not all(f.get(k) for k in ("rule", "message", "fingerprint", "severity", "owner"))
            for f in stage_findings
        ):
            errors.append(finding("EVIDENCE", f"Malformed findings in {stage}."))
            stage_findings = []
        errors.extend(stage_findings)
        if status not in ("PASS", "FAIL"):
            errors.append(finding("EVIDENCE", f"{stage} was skipped, cancelled or never completed."))
        elif status == "FAIL" and not stage_findings:
            errors.append(finding("EVIDENCE", f"{stage} failed without actionable evidence."))
        elif status == "PASS" and stage_findings:
            errors.append(finding("EVIDENCE", f"{stage} claims PASS despite outstanding findings."))
        if stage in policy["test_stages"]:
            count, skipped, failed = (report.get(key) for key in ("tests", "skipped", "failed"))
            if (
                type(count) is not int
                or count <= 0
                or type(skipped) is not int
                or skipped != 0
                or type(failed) is not int
                or failed != 0
            ):
                errors.append(
                    finding("TEST", f"{stage} needs a nonempty suite with no failures or skipped tests.")
                )
    baseline = policy.get("coverage", {}).get("approval", {})
    if not all(baseline.get(key) for key in ("reviewer", "review_url", "revision")):
        errors.append(
            finding(
                "BASELINE",
                "A qualified human must approve the measured coverage baseline and record the review.",
                owner="repository owner",
            )
        )
    accepted, review_errors = approvals(reviews, identity["author"], identity["head_sha"], risk, policy)
    errors.extend(review_errors)
    outstanding, waivers = exceptions(errors, waiver_records, accepted, identity["head_sha"], now, policy)
    return {
        "schema_version": 1,
        "status": "FAIL" if outstanding else "APPROVED EXCEPTION" if waivers else "PASS",
        "generated_at": now.isoformat(),
        "identity": identity,
        "risk": risk,
        "stages": stages,
        "architecture_reviews": accepted,
        "exceptions": waivers,
        "outstanding_actions": outstanding,
        "evidence": {
            name: report.get("evidence", []) for name, report in reports.items() if isinstance(report, dict)
        },
    }
