import pytest

from imagectl import cli


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
    ],
)
def test_wrong_arguments_fail_with_usage(in_root, capsys, argv):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_publish_needs_at_least_one_job(in_root, capsys):
    assert cli.main(["publish", "-j", "0"]) == 1
    assert "-j must be at least 1" in capsys.readouterr().err


def test_list_prints_tree_with_sources(in_root, capsys):
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == ["IMAGE", "PLAYBOOK", "DISK", "MEMORY", "CPUS", "SOURCE"]
    assert out[1].startswith("debian-base ")
    assert "debian-cloud https://cdimage.debian.org/" in out[1]
    assert out[4].startswith("    debian-edge ")
    assert out[4].rstrip().endswith("debian-container")


def test_unknown_image(in_root, capsys):
    assert cli.main(["test", "debian-nope"]) == 1
    assert "unknown image 'debian-nope'" in capsys.readouterr().err


def test_catalog_errors_are_reported(in_root, capsys):
    (in_root / "images.yml").write_text("config: {}\n")
    assert cli.main(["list"]) == 1
    assert "error:" in capsys.readouterr().err


def test_must_run_from_project_root(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["list"]) == 1
    assert "project root" in capsys.readouterr().err
