"""Scan a build's SBOM for known vulnerabilities with grype. Findings are reported, never fatal."""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

GRYPE = "grype"
# the publish workflow copies what is between these lines into the job summary
BEGIN = "--- vulnerabilities"
END = "--- end vulnerabilities"

# parallel builds would otherwise race on updating grype's shared database
_lock = threading.Lock()


def scan(sbom_path: Path) -> str:
    """grype's findings table, or why there is none."""
    env = {**os.environ, "GRYPE_CHECK_FOR_APP_UPDATE": "false"}
    cmd = [GRYPE, f"sbom:{sbom_path}", "--quiet", "--output", "table"]
    with _lock:
        try:
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        except FileNotFoundError:
            return f"{GRYPE} not found on PATH, not scanned"
    if result.returncode != 0:
        return f"{GRYPE} failed with exit code {result.returncode}: {result.stderr.strip()}"
    return result.stdout.strip() or "no vulnerabilities found"


def report(image: str, findings: str) -> str:
    return f"{BEGIN} {image}\n{findings}\n{END}"
