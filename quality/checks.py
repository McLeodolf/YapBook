"""Local automated checks; reports contain findings, never secret values."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
from typing import Any

from quality.bootstrap import gitleaks, semgrep_core
from quality.gate import Json, finding, read_json


def command(
    args: list[str], cwd: Path, timeout: int = 180, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(args[0]) or args[0]
    return subprocess.run(
        [executable, *args[1:]],
        cwd=cwd,
        env={**os.environ, "PYTHONUTF8": "1", **(env or {})},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def source_files(root: Path) -> list[str]:
    result = command(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], root)
    if result.returncode:
        raise ValueError("Cannot enumerate version-controlled source")
    return sorted({p for p in result.stdout.split("\0") if p and (root / p).is_file()})


def security(root: Path, output: Path, policy: Json, controls: Path | None = None) -> tuple[list[Json], Json]:
    controls = controls or root
    issues: list[Json] = []
    scanner = gitleaks(controls)
    for mode, target in (("dir", str(root)), ("git", str(root))):
        report = output / f"gitleaks-{mode}.json"
        args = [
            str(scanner),
            mode,
            target,
            "--redact=100",
            "--ignore-gitleaks-allow",
            "--no-banner",
            "--config",
            str(controls / "quality/gitleaks.toml"),
            "--report-format",
            "json",
            "--report-path",
            str(report),
        ]
        if mode == "git":
            args += ["--log-opts=--all"]
        result = command(args, root)
        if result.returncode not in (0, 1) or not report.exists():
            issues.append(
                finding(
                    "EVIDENCE",
                    f"Gitleaks {mode} failed to produce a valid report; check scanner availability.",
                )
            )
            continue
        entries = read_json(report)
        sanitized = []
        for item in entries:
            issue = finding(
                "SEC-SECRET",
                "Remove the exposed credential, revoke/rotate it, document remediation and rescan.",
                item["File"],
                severity="critical",
                detail=item["Fingerprint"],
            )
            issue.update(
                scanner_rule=item["RuleID"], line=item["StartLine"], classification="requires_triage"
            )
            issues.append(issue)
            sanitized.append(issue)
        report.write_text(json.dumps(sanitized), encoding="utf-8")
        if result.returncode == 1 and not sanitized:
            issues.append(finding("EVIDENCE", f"Gitleaks {mode} failed without findings."))
    files = [p for p in source_files(root) if p.endswith((".py", ".mjs", ".jsx")) and "/dist/" not in p]
    semgrep = scan_core(root, files, controls)
    try:
        data = json.loads(semgrep.stdout)
        if semgrep.returncode != 0 or data.get("errors"):
            issues.append(
                finding("EVIDENCE", "Semgrep encountered an execution/parsing error; fix it and rescan.")
            )
        for item in data.get("results", []):
            issue = finding(
                "SEC-SAST",
                item["extra"]["message"],
                item["path"],
                detail=item["check_id"] + ":" + str(item["start"]["line"]),
            )
            issue.update(
                scanner="semgrep",
                scanner_rule=item["check_id"],
                line=item["start"]["line"],
                classification="requires_triage",
            )
            issues.append(issue)
        if not data.get("paths", {}).get("scanned"):
            issues.append(finding("EVIDENCE", "Semgrep scanned no source files."))
    except (ValueError, KeyError, TypeError):
        issues.append(finding("EVIDENCE", "Semgrep did not return valid JSON."))
    production = policy["coverage"]["desktop_sources"] + ["web/speech_service.py", "web/streamlit_app.py"]
    bandit = command([sys.executable, "-m", "bandit", "-f", "json", "-q", *production], root)
    try:
        data = json.loads(bandit.stdout)
        if bandit.returncode not in (0, 1) or data.get("errors"):
            issues.append(finding("EVIDENCE", "Bandit could not scan all Python production files."))
        for item in data.get("results", []):
            # Bandit messages/code can include a discovered password; preserve only safe metadata.
            issue = finding(
                "SEC-SAST",
                f"Review Bandit {item['test_id']} ({item['test_name']}); remediate or obtain a scoped exception.",
                item["filename"].replace("\\", "/"),
                severity=item["issue_severity"].lower(),
                detail=item["test_id"] + ":" + str(item["line_number"]),
            )
            issue.update(
                scanner="bandit",
                scanner_rule=item["test_id"],
                line=item["line_number"],
                confidence=item["issue_confidence"],
                classification="requires_triage",
            )
            issues.append(issue)
        if data.get("metrics", {}).get("_totals", {}).get("loc", 0) <= 0:
            issues.append(finding("EVIDENCE", "Bandit scanned no Python source."))
    except (ValueError, KeyError, TypeError):
        issues.append(finding("EVIDENCE", "Bandit did not return valid JSON."))
    for name in files:
        text = (root / name).read_text(encoding="utf-8")
        comments = (
            "\n".join(
                token.string
                for token in tokenize.generate_tokens(io.StringIO(text).readline)
                if token.type == tokenize.COMMENT
            )
            if name.endswith(".py")
            else "\n".join(re.findall(r"//[^\n]*|/\*.*?\*/", text, re.S))
        )
        if re.search(
            r"nosec|nosemgrep|pragma:\s*no cover|eslint-disable|\b(?:istanbul|c8|v8) ignore\b",
            comments,
        ) or re.search(r"\btest\.(?:skip|only)\s*\(", text):
            issues.append(
                finding(
                    "SUPPRESSION",
                    "Inline scanner/coverage suppressions and disabled/focused tests need explicit policy review.",
                    name,
                )
            )
    return issues, {
        "tools": {name: policy["tools"][name] for name in ("semgrep", "bandit", "gitleaks")},
        "scanned_source_files": len(files),
    }


def parse_lock(path: Path) -> dict[str, str]:
    logical = path.read_text(encoding="utf-8").replace("\\\n", " ")
    packages: dict[str, str] = {}
    for line in logical.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)==([^\s;]+)(?:\s*;[^-]+)?\s+--hash=sha256:[a-f0-9]{64}", line)
        if not match or re.search(
            r"(?:https?://|git\+|file:|--index|--extra-index|--trusted-host|^-e\b)", line
        ):
            raise ValueError(f"Unpinned, unhashed or prohibited dependency source in {path.name}")
        packages[match[1].lower().replace("_", "-")] = match[2]
    if not packages:
        raise ValueError(f"Empty dependency lock: {path.name}")
    return packages


def dependencies(root: Path, output: Path, policy: Json) -> tuple[list[Json], Json]:
    from quality.inventory import standard_license

    issues: list[Json] = []
    inventory = read_json(root / "quality/dependencies.json")
    for name, expected in inventory["files"].items():
        path = root / name
        actual = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != expected:
            issues.append(
                finding(
                    "DEP-INTEGRITY",
                    "Dependency input/lock changed without regenerated inventory; regenerate, explain the delta and request review.",
                    name,
                )
            )
        if name.endswith(".lock") or name in ("requirements.txt", "web/requirements.txt"):
            try:
                parse_lock(path)
            except ValueError:
                issues.append(
                    finding(
                        "DEP-SOURCE",
                        "Use exact versions and SHA-256 hashes from the approved PyPI registry.",
                        name,
                    )
                )
    package = read_json(root / "web/frontend/package.json")
    lock = read_json(root / "web/frontend/package-lock.json")
    for category in ("dependencies", "devDependencies"):
        if package.get(category) != lock["packages"][""].get(category):
            issues.append(
                finding(
                    "DEP-INTEGRITY",
                    "package.json and package-lock.json disagree.",
                    "web/frontend/package-lock.json",
                )
            )
        for name, version in package.get(category, {}).items():
            if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", version):
                issues.append(
                    finding("DEP-INTEGRITY", "Pin direct npm dependencies to exact reviewed versions.", name)
                )
    for name, item in lock["packages"].items():
        if not name:
            continue
        if not any(
            item.get("resolved", "").startswith(registry) for registry in policy["registries"]["npm"]
        ) or not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", item.get("integrity", "")):
            issues.append(
                finding(
                    "DEP-SOURCE",
                    "npm package must resolve to an approved registry with SHA-512 integrity.",
                    name,
                )
            )
    for ecosystem, packages in inventory["packages"].items():
        for item in packages:
            reviewed = any(
                review.get("ecosystem") == ecosystem
                and review.get("name") == item["name"]
                and review.get("version") == item["version"]
                and review.get("license") == item.get("license")
                and review.get("decision") == "allowed"
                and review.get("reviewer") in policy["reviewers"]["security"]
                and all(review.get(key) for key in ("review_url", "rationale"))
                for review in policy.get("license_reviews", [])
            )
            if not standard_license(item.get("license", "UNKNOWN"), policy["license_policy"]["permitted"]):
                if reviewed:
                    continue
                issues.append(
                    finding(
                        "DEP-LICENSE",
                        f"Review the license metadata and redistribution obligations for {item['name']} ({item['license']}); record an accountable package-specific decision.",
                        item["name"],
                        severity="medium",
                    )
                )
    if not policy.get("native_tool_review", {}).get("review_url"):
        issues.append(
            finding(
                "DEP-LICENSE",
                "Review the pinned Semgrep CE native engine and bundled libraries, including their LGPL notices and native supply-chain limitations.",
                "quality/bootstrap.py",
                severity="medium",
                owner="repository owner",
            )
        )
    audit = command(
        [
            sys.executable,
            "-m",
            "pip_audit",
            "-r",
            "quality/ci.lock",
            "--require-hashes",
            "--disable-pip",
            "--no-deps",
            "--format",
            "json",
            "--progress-spinner",
            "off",
        ],
        root,
        timeout=240,
    )
    try:
        data = json.loads(audit.stdout)
        if audit.returncode not in (0, 1) or not data.get("dependencies"):
            issues.append(
                finding(
                    "EVIDENCE",
                    "Python dependency audit unavailable or empty; rerun when the advisory service is reachable.",
                )
            )
        for item in data.get("dependencies", []):
            if "skip_reason" in item:
                issues.append(finding("EVIDENCE", "Python package could not be audited.", item["name"]))
            for vuln in item.get("vulns", []):
                malicious = "malicious" in vuln.get("description", "").lower()
                issue = finding(
                    "DEP-MALICIOUS" if malicious else "DEP-VULN",
                    f"{item['name']} {item['version']}: {vuln['id']}; fixed versions: {', '.join(vuln.get('fix_versions', [])) or 'none reported'}. Triage advisory severity before requesting any exception.",
                    item["name"],
                    severity="critical" if malicious else "high",
                    detail=vuln["id"],
                )
                issue.update(
                    advisory=vuln["id"],
                    severity_basis="malicious advisory"
                    if malicious
                    else "conservative block; source audit does not supply severity",
                )
                issues.append(issue)
        (output / "python-audit.json").write_text(json.dumps(data), encoding="utf-8")
    except (ValueError, KeyError, TypeError):
        issues.append(finding("EVIDENCE", "Python audit did not produce valid JSON."))
    audit = command(
        ["npm", "audit", "--json", "--registry=https://registry.npmjs.org"], root / "web/frontend"
    )
    try:
        data = json.loads(audit.stdout)
        if audit.returncode not in (0, 1) or data.get("error") or "metadata" not in data:
            issues.append(
                finding(
                    "EVIDENCE", "npm audit unavailable; rerun when the registry advisory API is reachable."
                )
            )
        for name, item in data.get("vulnerabilities", {}).items():
            issue = finding(
                "DEP-VULN",
                f"Upgrade {name}; affected range {item['range']}. Consult the linked advisory and verify the lockfile after remediation.",
                name,
                severity=item["severity"],
                detail=json.dumps(item["via"], sort_keys=True),
            )
            issue["advisories"] = [v["url"] for v in item["via"] if isinstance(v, dict)]
            issues.append(issue)
        (output / "npm-audit.json").write_text(json.dumps(data), encoding="utf-8")
    except (ValueError, KeyError, TypeError):
        issues.append(finding("EVIDENCE", "npm audit did not produce valid JSON."))
    return issues, {"inventory": "quality/dependencies.json", "dependency_inputs": list(inventory["files"])}


def scanner_fixtures(root: Path, controls: Path | None = None) -> list[Json]:
    """Exercise real scanners against generated inert violations, never real secrets."""
    controls = controls or root
    errors: list[Json] = []
    with tempfile.TemporaryDirectory(prefix="yapbook-scanner-fixtures-") as folder:
        target = Path(folder)
        leak = target / "test_fixture.py"
        fake = "ghp_" + hashlib.sha256(b"nonfunctional scanner fixture").hexdigest()[:36]
        leak.write_text('token = "' + fake + '"\n', encoding="utf-8")
        source_leak = target / "source.py"
        source_leak.write_text('token = "' + fake + '"\n', encoding="utf-8")
        report = target / "secrets.json"
        result = command(
            [
                str(gitleaks(controls)),
                "dir",
                str(target),
                "--redact=100",
                "--ignore-gitleaks-allow",
                "--no-banner",
                "--report-format=json",
                "--report-path",
                str(report),
                "--config",
                str(controls / "quality/gitleaks.toml"),
            ],
            root,
        )
        if (
            result.returncode != 1
            or not report.exists()
            or len(read_json(report)) != 2
            or fake in result.stdout + result.stderr + report.read_text()
        ):
            errors.append(
                finding(
                    "EVIDENCE",
                    "Secrets scanner fixture did not block/redact a synthetic source/test credential.",
                )
            )
        leak.unlink()
        source_leak.unlink()
        unsafe = target / "unsafe.py"
        unsafe.write_text("import subprocess\ndef unsafe(value):\n    return eval(value)\n", encoding="utf-8")
        result = scan_core(root, [str(unsafe)], controls)
        try:
            blocked = any(
                item["check_id"].endswith("python-dynamic-execution")
                for item in json.loads(result.stdout)["results"]
            )
        except (ValueError, KeyError):
            blocked = False
        if result.returncode != 0 or not blocked:
            errors.append(finding("EVIDENCE", "SAST fixture did not block dynamic execution."))
    return errors


def scan_core(root: Path, files: list[str], controls: Path | None = None) -> subprocess.CompletedProcess[str]:
    controls = controls or root
    combined: Json = {"results": [], "errors": [], "paths": {"scanned": []}}
    code = 0
    engine = semgrep_core(controls)
    for language, suffixes in (("python", (".py",)), ("javascript", (".mjs", ".jsx", ".js"))):
        targets = [p for p in files if p.endswith(suffixes)]
        if not targets:
            continue
        for target in targets:
            result = command(
                [
                    str(engine),
                    "-rules",
                    str(controls / "quality/semgrep.yml"),
                    "-lang",
                    language,
                    "-json",
                    "-json_nodots",
                    "-j",
                    "1",
                    "-timeout",
                    "10",
                    target,
                ],
                root,
                timeout=60,
            )
            code = code or result.returncode
            data = json.loads(result.stdout)
            for key in ("results", "errors"):
                combined[key].extend(data[key])
            combined["paths"]["scanned"].extend(data["paths"]["scanned"])
    return subprocess.CompletedProcess([str(engine)], code, json.dumps(combined), "")
