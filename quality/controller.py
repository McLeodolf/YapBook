"""Trusted GitHub controller. Treat PR files/artifacts as bounded data, never code."""

from __future__ import annotations

import base64
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
import urllib.request
import zipfile

from quality.gate import Json, evaluate, finding, read_json

REPOSITORY = "McLeodolf/YapBook"
WORKFLOW = ".github/workflows/quality-evidence.yml"
MAXIMUM = 8_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token: str):
        if not token:
            raise ValueError("A scoped GitHub token is required")
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, path: str, method: str = "GET", body: object | None = None):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("GitHub API paths must be relative")
        request = urllib.request.Request(
            "https://api.github.com" + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "YapBook-quality-gate",
            },
        )
        with self.opener.open(request, timeout=45) as response:
            data = response.read(MAXIMUM + 1)
        if len(data) > MAXIMUM:
            raise ValueError("Oversized GitHub response")
        return json.loads(data) if data else None

    def pages(self, path: str, key: str | None = None) -> list[Json]:
        values = []
        for page in range(1, 101):
            data = self.request(path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
            batch = data[key] if key else data
            values.extend(batch)
            if len(batch) < 100:
                return values
        raise ValueError("Pagination limit reached; no truncated evidence may pass")

    def file(self, path: str, revision: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Files must be fetched at an immutable revision")
        data = self.request(f"/repos/{REPOSITORY}/contents/{quote(path, safe='/')}?ref={revision}")
        if data.get("encoding") != "base64" or data.get("size", MAXIMUM + 1) > MAXIMUM:
            raise ValueError("Missing or oversized repository evidence")
        return base64.b64decode(data["content"], validate=False)

    def artifact(self, artifact_id: int) -> Json:
        try:
            self.request(f"/repos/{REPOSITORY}/actions/artifacts/{int(artifact_id)}/zip")
        except HTTPError as error:
            if error.code != 302:
                raise
            location = error.headers["Location"]
        else:
            raise ValueError("Artifact endpoint did not return its download redirect")
        parsed = urlparse(location)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or not any(
                host.endswith(suffix) for suffix in (".blob.core.windows.net", ".githubusercontent.com")
            )
        ):
            raise ValueError("Unexpected artifact download host")
        # Do not send the GitHub token to the signed object-storage URL.
        with self.opener.open(urllib.request.Request(location), timeout=45) as response:
            data = response.read(MAXIMUM + 1)
        return artifact_bundle(data)


def artifact_bundle(data: bytes) -> Json:
    if len(data) > MAXIMUM:
        raise ValueError("Oversized artifact")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        matches = [item for item in archive.infolist() if item.filename == "bundle.json"]
        if len(matches) != 1 or matches[0].file_size > MAXIMUM:
            raise ValueError("Missing, duplicate or oversized bundle.json")
        # No archive extraction, symlink following or PR-controlled Python imports.
        raw = archive.read(matches[0])

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate artifact JSON key")
                result[key] = value
            return result

        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError("Artifact bundle must be an object")
        return value


def provenance(
    pr: Json,
    run: Json,
    commit: Json,
    identity: Json,
    policy: Json,
    workflow: bytes,
    expected: bytes,
    jobs: list[Json],
) -> list[Json]:
    errors = []
    head, base = pr["head"]["sha"], pr["base"]["sha"]
    if policy.get("evidence_maximum_hours"):
        try:
            started = datetime.fromisoformat(run["run_started_at"].replace("Z", "+00:00"))
            fresh = started.tzinfo and datetime.now(timezone.utc) - timedelta(
                hours=policy["evidence_maximum_hours"]
            ) <= started <= datetime.now(timezone.utc)
        except (KeyError, ValueError, TypeError):
            fresh = False
        if not fresh:
            errors.append(
                finding(
                    "EVIDENCE",
                    "Evidence is missing a valid timestamp or is too old; rerun the scans and tests.",
                )
            )
    if (
        run.get("event") != "pull_request"
        or run.get("path") != WORKFLOW
        or run.get("repository", {}).get("full_name") != REPOSITORY
    ):
        errors.append(
            finding("CI-INTEGRITY", "Evidence came from an unexpected workflow, event or repository.")
        )
    if run.get("status") != "completed" or run.get("conclusion") not in ("success", "failure"):
        errors.append(finding("EVIDENCE", "Evidence workflow is missing, skipped, cancelled or incomplete."))
    if (
        run.get("head_sha") != head
        or identity.get("head_sha") != head
        or identity.get("base_sha") != base
        or str(run.get("id")) != identity.get("run_id")
    ):
        errors.append(
            finding("REVISION", "Evidence does not cover the current PR head and target; rerun CI.")
        )
    parents = [row["sha"] for row in commit.get("parents", [])]
    if commit.get("sha") != identity.get("test_sha") or parents != [base, head]:
        errors.append(
            finding("REVISION", "Tests must run against the exact merge of the current target and PR head.")
        )
    digest = lambda data: hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
    if digest(workflow) != digest(expected) and digest(workflow) not in policy.get(
        "approved_workflow_hashes", []
    ):
        errors.append(
            finding(
                "CI-INTEGRITY",
                "The executed workflow differs from the trusted template; use a separately approved workflow transition.",
            )
        )
    evidence_jobs = [job for job in jobs if job.get("name") == "evidence"]
    if len(evidence_jobs) != 1 or evidence_jobs[0].get("status") != "completed":
        errors.append(finding("EVIDENCE", "The mandatory evidence job did not complete."))
    else:
        steps = {step["name"]: step for step in evidence_jobs[0].get("steps", [])}
        for step in ("Install locked dependencies", "Run quality checks", "Upload quality evidence"):
            allowed = ("success", "failure") if step == "Run quality checks" else ("success",)
            if steps.get(step, {}).get("conclusion") not in allowed:
                errors.append(finding("EVIDENCE", f"Required step '{step}' did not execute successfully."))
    return errors


def assess_pr(api: GitHub, number: int, triggered_run: Json | None = None) -> Json:
    pr = api.request(f"/repos/{REPOSITORY}/pulls/{number}")
    if pr["state"] != "open":
        raise ValueError("PR is no longer open")
    head, base = pr["head"]["sha"], pr["base"]["sha"]
    policy_bytes = api.file("quality/policy.json", base)
    policy = json.loads(policy_bytes)
    if pr["base"]["ref"] not in policy["protected_branches"]:
        raise ValueError("PR targets a branch without configured quality protection")
    runs = api.pages(
        f"/repos/{REPOSITORY}/actions/workflows/quality-evidence.yml/runs?event=pull_request&head_sha={head}",
        "workflow_runs",
    )
    if not runs:
        raise ValueError("No mandatory evidence run exists for this head")
    run = max(runs, key=lambda item: (item["id"], item.get("run_attempt", 1)))
    # A delayed webhook may not bless an earlier revision or a previous attempt.
    artifacts = api.pages(f"/repos/{REPOSITORY}/actions/runs/{run['id']}/artifacts", "artifacts")
    expected_name = f"quality-evidence-{run['id']}-{run.get('run_attempt', 1)}"
    matches = [item for item in artifacts if item["name"] == expected_name and not item["expired"]]
    if len(matches) != 1:
        raise ValueError("Fresh evidence artifact is missing or ambiguous")
    bundle = api.artifact(matches[0]["id"])
    identity = bundle["identity"]
    identity["author"] = pr["user"]["login"]
    policy_sha = hashlib.sha256(policy_bytes.replace(b"\r\n", b"\n")).hexdigest()
    if identity.get("policy_sha") != policy_sha or identity.get("local_dirty"):
        raise ValueError("Policy digest or CI identity is invalid")
    commit = api.request(f"/repos/{REPOSITORY}/git/commits/{identity['test_sha']}")
    jobs = api.pages(
        f"/repos/{REPOSITORY}/actions/runs/{run['id']}/attempts/{run.get('run_attempt', 1)}/jobs", "jobs"
    )
    errors = provenance(
        pr,
        run,
        commit,
        identity,
        policy,
        api.file(WORKFLOW, identity["test_sha"]),
        api.file(WORKFLOW, base),
        jobs,
    )
    paths = [item["filename"] for item in api.pages(f"/repos/{REPOSITORY}/pulls/{number}/files")]
    candidates = [p for p in paths if p.startswith("quality/changes/") and p.endswith(".json")]
    if len(candidates) != 1:
        raise ValueError("Exactly one structured change record is required")
    record = json.loads(api.file(candidates[0], head))
    waivers = json.loads(api.file("quality/exceptions.json", head))
    reviews = api.pages(f"/repos/{REPOSITORY}/pulls/{number}/reviews")
    result = evaluate(policy, identity, bundle["reports"], record, paths, reviews, waivers)
    result["outstanding_actions"].extend(errors)
    if errors:
        result["status"] = "FAIL"
    result.update(pull_request=number, evidence_run=run["html_url"])
    # Recheck after network reads to close a force-push/target-update race.
    fresh = api.request(f"/repos/{REPOSITORY}/pulls/{number}")
    if fresh["head"]["sha"] != head or fresh["base"]["sha"] != base:
        raise ValueError("PR changed during review; rerun the controller")
    return result


def publish(api: GitHub, number: int, result: Json) -> None:
    head = result["identity"]["head_sha"]
    lines = [
        f"Decision: **{result['status']}**",
        "",
        "Machine-readable evidence is attached to this controller run.",
    ]
    if result["status"] == "APPROVED EXCEPTION":
        lines.append(
            "Exception is recorded, but merge remains blocked: native GitHub checks cannot expire atomically at merge time. Remediate or adopt a trusted merge-time gate."
        )
    for issue in result["outstanding_actions"][:35]:
        text = re.sub(r"[\r\n<>`\[\]]", " ", issue["message"])[:400]
        lines.append(f"- {issue['rule']}: {text}")
    api.request(
        f"/repos/{REPOSITORY}/check-runs",
        "POST",
        {
            "name": "quality/gate",
            "head_sha": head,
            "status": "completed",
            "conclusion": "success" if result["status"] == "PASS" else "failure",
            "external_id": f"yapbook-pr-{number}",
            "output": {"title": "YapBook quality gate: " + result["status"], "summary": "\n".join(lines)},
        },
    )


def main() -> int:
    api = GitHub(os.environ.get("GH_TOKEN", ""))
    event = read_json(Path(os.environ["GITHUB_EVENT_PATH"]))
    numbers = set()
    if "pull_request" in event:
        numbers.add(event["pull_request"]["number"])
    elif "workflow_run" in event:
        run = event["workflow_run"]
        numbers.update(pr["number"] for pr in run.get("pull_requests", []))
        if not numbers:
            numbers.update(
                pr["number"]
                for pr in api.pages(f"/repos/{REPOSITORY}/commits/{run['head_sha']}/pulls")
                if pr["state"] == "open"
            )
    else:
        numbers.update(pr["number"] for pr in api.pages(f"/repos/{REPOSITORY}/pulls?state=open"))
    results = []
    for number in sorted(numbers):
        try:
            result = assess_pr(api, number)
        except Exception as exc:
            pr = api.request(f"/repos/{REPOSITORY}/pulls/{number}")
            if pr["state"] != "open":
                continue
            result = {
                "status": "FAIL",
                "identity": {"head_sha": pr["head"]["sha"]},
                "outstanding_actions": [
                    finding(
                        "EVIDENCE",
                        f"Trusted controller could not verify all required evidence ({type(exc).__name__}). Rerun evidence and check repository policy/availability.",
                    )
                ],
            }
        publish(api, number, result)
        results.append(result)
    Path("quality-decisions.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return int(any(result["status"] == "FAIL" for result in results))


if __name__ == "__main__":
    sys.exit(main())
