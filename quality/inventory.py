"""Regenerate proposed dependency evidence. This never grants human approval."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import urllib.request

from quality.checks import parse_lock
from quality.gate import read_json
import re


def standard_license(expression: str, permitted: list[str]) -> bool:
    # Compound SPDX expressions are allowed only when every named license is allowed.
    names = re.findall(r"[A-Za-z0-9][A-Za-z0-9.+-]*", expression)
    return bool(names) and all(name in permitted or name in ("AND", "OR") for name in names)


def license_name(metadata: dict) -> str:
    expression = metadata.get("license_expression") or metadata.get("License-Expression")
    if expression:
        return expression
    raw = str(metadata.get("license") or metadata.get("License") or "")
    classifiers = metadata.get("classifiers", [])
    if not raw:
        raw = " ".join(value for value in classifiers if value.startswith("License ::"))
    for text, identifier in (
        ("Affero", "AGPL (review required)"),
        ("Lesser", "LGPL (review required)"),
        ("General Public", "GPL (review required)"),
        ("MIT-CMU", "MIT-CMU"),
        ("MIT", "MIT"),
        ("Apache", "Apache-2.0"),
        ("ISC", "ISC"),
        ("PSF", "PSF-2.0"),
        ("Python Software Foundation", "PSF-2.0"),
        ("BSD-3", "BSD-3-Clause"),
        ("3-Clause BSD", "BSD-3-Clause"),
        ("BSD-2", "BSD-2-Clause"),
        ("MPL-2", "MPL-2.0"),
        ("MPL 2.0", "MPL-2.0"),
    ):
        if text.lower() in raw.lower():
            return identifier
    return raw.strip()[:120] or "UNKNOWN"


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    policy = read_json(root / "quality/policy.json")
    files = [
        "requirements.in",
        "requirements.txt",
        "web/requirements.in",
        "web/requirements.txt",
        "quality/requirements.in",
        "quality/requirements.lock",
        "quality/ci.in",
        "quality/ci.lock",
        "quality/build.in",
        "quality/build.lock",
        "web/frontend/package.json",
        "web/frontend/package-lock.json",
    ]
    data = {
        "schema_version": 1,
        "approval": "proposed; independent dependency and license review required",
        "files": {
            name: hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for name in files
        },
        "packages": {"python": [], "npm": []},
    }
    allowed = policy["license_policy"]["permitted"]
    for name, version in sorted(parse_lock(root / "quality/ci.lock").items()):
        try:
            installed = importlib.metadata.distribution(name)
            if installed.version != version:
                raise importlib.metadata.PackageNotFoundError(name)
            metadata = dict(installed.metadata)
            metadata["classifiers"] = installed.metadata.get_all("Classifier") or []
        except importlib.metadata.PackageNotFoundError:
            with urllib.request.urlopen(
                f"https://pypi.org/pypi/{name}/{version}/json", timeout=20
            ) as response:
                metadata = json.load(response)["info"]
        license = license_name(metadata)
        data["packages"]["python"].append(
            {
                "name": name,
                "version": version,
                "source": "https://pypi.org/simple",
                "license": license,
                "license_review": "standard-policy" if standard_license(license, allowed) else "required",
            }
        )
    lock = read_json(root / "web/frontend/package-lock.json")
    for path, package in sorted(lock["packages"].items()):
        if not path:
            continue
        license = package.get("license", "UNKNOWN")
        data["packages"]["npm"].append(
            {
                "name": path,
                "version": package["version"],
                "source": package.get("resolved", ""),
                "license": license,
                "license_review": "standard-policy" if standard_license(license, allowed) else "required",
            }
        )
    (root / "quality/dependencies.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    required = [
        (ecosystem, item["name"], item["license"])
        for ecosystem, items in data["packages"].items()
        for item in items
        if item["license_review"] == "required"
    ]
    print(
        json.dumps(
            {
                "packages": {k: len(v) for k, v in data["packages"].items()},
                "manual_license_reviews": required,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
