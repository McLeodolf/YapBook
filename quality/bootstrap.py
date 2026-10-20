"""Download a pinned scanner and verify its release digest before execution."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import tarfile
import urllib.request
import zipfile

from quality.gate import read_json


def semgrep_core(root: Path) -> Path:
    """Extract only the official CE engine, without the unrelated Python MCP server."""
    platform = "windows" if os.name == "nt" else "linux"
    asset = read_json(root / "quality/policy.json")["tools"]["semgrep_assets"][platform]
    directory = root / "quality/bin/semgrep"
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "engine.whl"
    if not archive.exists():
        with urllib.request.urlopen(asset["url"], timeout=60) as response:
            data = response.read(150_000_001)
        if len(data) > 150_000_000 or hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise ValueError("Semgrep CE engine failed integrity verification")
        archive.write_bytes(data)
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise ValueError("Cached Semgrep engine failed integrity verification")
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        for member in package.namelist():
            relative = Path(member)
            if relative.parts[-3:-1] != ("semgrep", "bin"):
                continue
            if relative.suffix not in (".exe", ".dll") and relative.name != "semgrep-core":
                continue
            binary = package.read(member)
            destination = directory / relative.name
            if not destination.exists() or destination.read_bytes() != binary:
                destination.write_bytes(binary)
            destination.chmod(0o755)
    engine = directory / ("semgrep-core.exe" if platform == "windows" else "semgrep-core")
    if not engine.is_file():
        raise ValueError("Semgrep executable missing from verified wheel")
    return engine


def gitleaks(root: Path) -> Path:
    policy = read_json(root / "quality/policy.json")["tools"]["gitleaks"]
    platform = "windows" if os.name == "nt" else "linux"
    asset = policy[platform]
    directory = root / "quality/bin"
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / asset["asset"]
    if not archive.exists():
        url = f"https://github.com/gitleaks/gitleaks/releases/download/v{policy['version']}/{asset['asset']}"
        with urllib.request.urlopen(url, timeout=45) as response:
            data = response.read(100_000_001)
        if len(data) > 100_000_000 or hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise ValueError("Gitleaks release failed integrity verification")
        archive.write_bytes(data)
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise ValueError("Cached Gitleaks archive failed integrity verification")
    name = "gitleaks.exe" if platform == "windows" else "gitleaks"
    if platform == "windows":
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            binary = package.read(name)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as package:
            stream = package.extractfile(name)
            if stream is None:
                raise ValueError("Scanner executable missing")
            binary = stream.read()
    destination = directory / name
    if not destination.exists() or destination.read_bytes() != binary:
        destination.write_bytes(binary)
    destination.chmod(0o755)
    return destination


if __name__ == "__main__":
    print(gitleaks(Path(__file__).resolve().parents[1]))
