import json
from datetime import UTC, datetime

import boto3
import pytest
from botocore.stub import Stubber
from typer.testing import CliRunner

from imagectl import cli, publish

runner = CliRunner()


def imagectl(*argv: str):
    return runner.invoke(cli.app, list(argv))


@pytest.fixture
def in_root(catalog_root, monkeypatch):
    monkeypatch.chdir(catalog_root)
    return catalog_root


@pytest.mark.parametrize(
    "argv",
    [
        ["build"],
        ["build", "debian-base", "debian-edge"],
        ["build", "-j", "2", "debian-base"],
        ["publish", "debian-base"],
        ["publish", "--keep"],
        ["publish", "-j", "0"],
    ],
)
def test_wrong_arguments_fail_with_usage(in_root, argv):
    result = imagectl(*argv)
    assert result.exit_code == 2
    assert "Usage:" in result.output


def test_list_prints_tree_with_sources(in_root):
    result = imagectl("list")
    assert result.exit_code == 0
    out = result.stdout.splitlines()
    assert out[0].split() == ["IMAGE", "PLAYBOOK", "DISK", "MEMORY", "CPUS", "SOURCE"]
    assert out[1].split() == [
        "debian-cloud",
        "https://cdimage.debian.org/images/cloud/trixie/20260914-2601/"
        "debian-13-genericcloud-amd64-20260914-2601.qcow2",
    ]
    assert out[2].startswith("  debian-base ")
    assert out[2].rstrip().endswith("debian-cloud")
    assert out[5].startswith("      debian-edge ")
    assert out[5].rstrip().endswith("debian-container")


def test_unknown_image(in_root):
    result = imagectl("test", "debian-nope")
    assert result.exit_code == 1
    assert "unknown image 'debian-nope'" in result.stderr


def test_catalog_errors_are_reported(in_root):
    (in_root / "images.yml").write_text("config: {}\n")
    result = imagectl("list")
    assert result.exit_code == 1
    assert "error:" in result.stderr


def test_must_run_from_project_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = imagectl("list")
    assert result.exit_code == 1
    assert "project root" in result.stderr


def test_help_works_outside_project_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = imagectl("build", "-h")
    assert result.exit_code == 0
    assert "The image to build." in result.stdout


def test_clean_defaults_to_every_image(in_root):
    (in_root / "build" / "debian-base" / "20260927-1200").mkdir(parents=True)
    (in_root / "build" / "test" / "fedora-edge").mkdir(parents=True)
    result = imagectl("clean")
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "removed build/debian-base",
        "removed build/test/fedora-edge",
    ]
    assert not (in_root / "build" / "debian-base").exists()


def test_clean_rejects_unknown_images(in_root):
    result = imagectl("clean", "debian-nope")
    assert result.exit_code == 1
    assert "unknown image 'debian-nope'" in result.stderr


EMPTY_PLAYBOOK = "- hosts: all\n  roles: []\n"
EDGE_PLAYBOOK = """\
- hosts: all
  roles:
    - role: binarycodes.homelab.systemd_app
      systemd_app_kind: source
      systemd_app_name: web
"""


def test_storage_lists_the_datasets(in_root):
    ansible = in_root / "ansible"
    (ansible / "apps" / "web").mkdir(parents=True)
    (ansible / "apps" / "web" / "storage.yml").write_text(
        "datasets:\n  db:\n    owner: '999:999'\n    recordsize: 16K\n"
    )
    for image in ("base", "container"):
        (ansible / f"packer-debian-{image}.yml").write_text(EMPTY_PLAYBOOK)
    (ansible / "packer-debian-edge.yml").write_text(EDGE_PLAYBOOK)

    result = imagectl("storage", "debian-edge")
    assert result.exit_code == 0, result.output
    assert [line.split() for line in result.stdout.splitlines()] == [
        ["APP", "DATASET", "RECORDSIZE", "MOUNT"],
        ["web", "db", "16K", "/srv/web/db"],
    ]

    result = imagectl("storage", "--json", "debian-edge")
    assert json.loads(result.stdout) == [{"app": "web", "dataset": "db", "recordsize": "16K"}]

    result = imagectl("storage", "debian-base")
    assert result.stdout == "debian-base mounts no storage\n"


VERSIONS = [{"Key": "debian/debian-base/latest.json", "VersionId": "1"}]


@pytest.fixture
def s3_stub(in_root, monkeypatch):
    client = boto3.client(
        "s3",
        endpoint_url="https://s3.example.net",
        region_name="home",
        aws_access_key_id="k",
        aws_secret_access_key="s",
        config=publish.CLIENT_CONFIG,
    )
    monkeypatch.setattr(publish, "s3_client", lambda catalog: client)
    with Stubber(client) as stub:
        stub.add_response(
            "list_object_versions", {"Versions": VERSIONS}, {"Bucket": "os-image-staging"}
        )
        yield stub


def expect_delete(stub):
    stub.add_response(
        "delete_objects",
        {},
        {"Bucket": "os-image-staging", "Delete": {"Objects": VERSIONS, "Quiet": True}},
    )


def test_purge_deletes_after_the_bucket_name_is_typed(s3_stub):
    expect_delete(s3_stub)
    result = runner.invoke(cli.app, ["purge"], input="os-image-staging\n")
    assert result.exit_code == 0
    assert "1 objects, 1 versions and delete markers" in result.stdout
    s3_stub.assert_no_pending_responses()


def test_purge_deletes_nothing_without_confirmation(s3_stub):
    result = runner.invoke(cli.app, ["purge"], input="yes\n")
    assert result.exit_code == 1
    assert "nothing deleted" in result.stderr
    s3_stub.assert_no_pending_responses()


def test_purge_yes_skips_the_prompt(s3_stub):
    expect_delete(s3_stub)
    assert imagectl("purge", "--yes").exit_code == 0
    s3_stub.assert_no_pending_responses()


def test_purge_warns_that_protected_images_go_too(s3_stub):
    expect_delete(s3_stub)
    result = imagectl("purge", "--yes")
    assert "protected images" in result.stderr
    s3_stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    ("build_date", "expected"),
    [
        ("2026-11-23 10:00:00 +0000", "2h"),
        ("2026-11-21 09:30:00 +0000", "2d 2h"),
        ("2026-11-23 13:00:00 +0000", "0h"),
    ],
)
def test_age_in_days_and_hours(build_date, expected):
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    assert cli.age(build_date, now) == expected


class ProtectedStore:
    def __init__(self, catalog, client):
        pass

    base = "https://s3.example.net/os-image-staging/debian"
    files = {
        "protected/infra/vm1.json": f"{base}/debian-base/20260901-0000/x.qcow2",
        "protected/infra/vm2.json": f"{base}/debian-edge/20260902-0000/x.qcow2",
        "protected/infra/vm3.json": f"{base}/debian-gone/20260903-0000/x.qcow2",
    }

    def list_keys(self, prefix):
        return list(self.files)

    def get_json(self, key):
        return {"image_url": self.files[key]}

    def get_json_optional(self, key):
        if key == "debian/debian-base/20260901-0000/metadata.json":
            return {"BUILD_DATE": "2026-09-01 00:00:00 +0000"}
        return None

    def latest(self, image):
        return {"BUILD_VERSION": "20261120-0000"} if image.name == "debian-base" else None


def test_protected_lists_version_current_and_age(in_root, monkeypatch):
    monkeypatch.setattr(publish, "anonymous_client", lambda catalog: None)
    monkeypatch.setattr(publish, "Store", ProtectedStore)
    result = imagectl("protected")
    assert result.exit_code == 0, result.output
    rows = [line.split() for line in result.stdout.splitlines()]
    assert rows[0] == ["IMAGE", "PROTECTED", "CURRENT", "AGE", "CONSUMERS"]
    assert rows[1][:3] == ["debian-base", "20260901-0000", "20261120-0000"]
    assert rows[1][-1] == "infra/vm1"
    assert rows[1][3].endswith("d")
    assert rows[2] == ["debian-edge", "20260902-0000", "none", "missing", "infra/vm2"]
    assert "debian-gone" in result.stderr


def test_protected_without_files(in_root, monkeypatch):
    monkeypatch.setattr(publish, "anonymous_client", lambda catalog: None)
    monkeypatch.setattr(publish, "Store", ProtectedStore)
    monkeypatch.setattr(ProtectedStore, "list_keys", lambda self, prefix: [])
    result = imagectl("protected")
    assert result.stdout == "no protected builds\n"
