import stat
from pathlib import Path

import pytest

from imagectl import scan


@pytest.fixture
def fake_grype(tmp_path, monkeypatch):
    """Point scan at a script that prints `out`, `err` and exits with `code`."""

    def make(out: str = "", err: str = "", code: int = 0) -> Path:
        path = tmp_path / "grype"
        path.write_text(f"#!/bin/sh\nprintf '%s' '{out}'\nprintf '%s' '{err}' >&2\nexit {code}\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setattr(scan, "GRYPE", str(path))
        return path

    return make


def test_findings_are_grypes_table(fake_grype, tmp_path):
    fake_grype(out="NAME  VULNERABILITY\nopenssh-server  CVE-1\n")
    assert scan.scan(tmp_path / "sbom.cdx.json") == "NAME  VULNERABILITY\nopenssh-server  CVE-1"


def test_empty_output_says_nothing_was_found(fake_grype, tmp_path):
    fake_grype()
    assert scan.scan(tmp_path / "sbom.cdx.json") == "no vulnerabilities found"


def test_grype_failure_is_reported_not_raised(fake_grype, tmp_path):
    fake_grype(err="db download failed", code=1)
    findings = scan.scan(tmp_path / "sbom.cdx.json")
    assert findings == f"{scan.GRYPE} failed with exit code 1: db download failed"


def test_missing_grype_is_reported_not_raised(monkeypatch, tmp_path):
    monkeypatch.setattr(scan, "GRYPE", str(tmp_path / "no-grype"))
    assert scan.scan(tmp_path / "sbom.cdx.json").endswith("not found on PATH, not scanned")


def test_report_is_framed_by_the_summary_markers():
    assert scan.report("debian-base", "x").splitlines() == [
        f"{scan.BEGIN} debian-base",
        "x",
        scan.END,
    ]
