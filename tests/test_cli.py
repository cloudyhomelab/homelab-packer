import pytest
from typer.testing import CliRunner

from imagectl import cli

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
    assert out[1].startswith("debian-base ")
    assert "debian-cloud https://cdimage.debian.org/" in out[1]
    assert out[4].startswith("    debian-edge ")
    assert out[4].rstrip().endswith("debian-container")


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
