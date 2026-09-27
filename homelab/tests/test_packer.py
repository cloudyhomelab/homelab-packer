from datetime import UTC, datetime
from pathlib import Path

from imagectl import packer
from imagectl.catalog import Source


def test_normalize_remote():
    expected = "https://github.com/cloudyhomelab/homelab-packer"
    assert packer.normalize_remote("git@github.com:cloudyhomelab/homelab-packer.git") == expected
    assert (
        packer.normalize_remote("https://token@github.com/cloudyhomelab/homelab-packer.git")
        == expected
    )
    assert packer.normalize_remote("ssh://git@github.com/cloudyhomelab/homelab-packer") == expected


def test_clock_is_one_reading():
    clock = packer.Clock.now(datetime(2026, 9, 27, 12, 5, 30, tzinfo=UTC))
    assert clock.build_version == "20260927-1205"
    assert clock.build_timestamp == "2026-09-27 12:05:30 +0000"


def test_missing_files_are_named(catalog):
    missing = packer.missing_files(catalog.root, catalog.get("fedora-edge"))
    assert missing == [
        "playbook ansible/packer-fedora-edge.yml",
        "template upstream/fedora/packer/",
        "cloud-init upstream/fedora/cloud-init/",
    ]


def test_variables(catalog, tmp_path):
    image = catalog.get("debian-edge")
    ssh = packer.SshMaterial(tmp_path / "ca.pub", tmp_path / "key", tmp_path / "key-cert.pub")
    inputs = packer.BuildInputs(
        image=image,
        source=Source("debian-container", "https://x/y.qcow2", "sha512:abc"),
        clock=packer.Clock("20260927-1200", "2026-09-27 12:00:00 +0000"),
        check_hash="sha256:h",
        git=packer.GitInfo("https://g/r", "abc"),
        output_directory=Path("/b/out"),
        accelerator="none",
        ssh=ssh,
    )
    values = packer.variables(inputs)
    assert values["playbook_file"] == "ansible/packer-debian-edge.yml"
    assert values["parent_name"] == "debian-container"
    assert values["disk_size"] == "5G"
    assert values["memory"] == "2048"
    assert packer.build_command(inputs)[-1] == "upstream/debian/packer"


def test_template_variables_match_the_driver(catalog, tmp_path):
    root = Path(__file__).resolve().parents[1]
    declared = set()
    for line in (root / "upstream/debian/packer/variables.pkr.hcl").read_text().splitlines():
        if line.startswith("variable "):
            declared.add(line.split('"')[1])
    ssh = packer.SshMaterial(tmp_path / "a", tmp_path / "b", tmp_path / "c")
    inputs = packer.BuildInputs(
        catalog.get("debian-base"),
        Source("u", "https://x", "sha512:a"),
        packer.Clock.now(),
        "h",
        packer.GitInfo("r", "c"),
        tmp_path,
        "none",
        ssh,
    )
    assert declared == set(packer.variables(inputs))
