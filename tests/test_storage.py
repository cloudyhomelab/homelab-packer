import textwrap
from pathlib import Path

import pytest
from conftest import copy_catalog

from imagectl import storage
from imagectl.catalog import CatalogError, load
from imagectl.idmap import IdMap

IDMAP = """\
start: 2000000
size: 65536
slots:
  youtarr: 1
"""
QUADLET = "[Container]\nImage=x.image\nSubUIDMap=youtarr\nSubGIDMap=youtarr\n"

YOUTARR = """\
datasets:
  db:
    owner: "999:999"
    recordsize: 16K
  data:
    owner: "1000:1000"
    dirs: [config, jobs]
"""


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


def deploys(*apps: str, stored: tuple[str, ...] = ()) -> str:
    items = "".join(f"    - role: app_storage\n      app_storage_app: {app}\n" for app in stored)
    items += "".join(
        "    - role: binarycodes.homelab.systemd_app\n"
        "      systemd_app_kind: source\n"
        f"      systemd_app_name: {app}\n"
        for app in apps
    )
    return f"- hosts: all\n  roles:\n{items or '    []'}\n"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    copy_catalog(tmp_path)
    for image in load(tmp_path).ordered():
        write(tmp_path, f"ansible/{image.playbook}.yml", deploys())
    write(tmp_path, "ansible/roles/app_storage/tasks/main.yml", "- ansible.builtin.debug: {}\n")
    write(
        tmp_path,
        "ansible/packer-debian-edge.yml",
        deploys("youtarr", "haproxy", stored=("youtarr",)),
    )
    write(tmp_path, "ansible/apps/youtarr/storage.yml", YOUTARR)
    write(tmp_path, "ansible/apps/youtarr/quadlet/youtarr.container", QUADLET)
    write(tmp_path, "ansible/apps/idmap.yml", IDMAP)
    return tmp_path


def test_image_datasets_are_published_without_dirs(root):
    catalog = load(root)
    datasets = storage.image_datasets(catalog, catalog.get("debian-edge"))
    assert [d.published() for d in datasets] == [
        {"app": "youtarr", "dataset": "db", "recordsize": "16K"},
        {"app": "youtarr", "dataset": "data"},
    ]
    assert storage.image_datasets(catalog, catalog.get("debian-media")) == []


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("datasets: {}\n", "non-empty mapping"),
        ("volumes: {}\n", "only datasets"),
        ("datasets:\n  db:\n    owner: 999\n", "owner must be a quoted uid:gid"),
        ("datasets:\n  db:\n    owner: '1:1'\n    size: 1G\n", "unknown fields ['size']"),
        ("datasets:\n  db:\n    owner: '1:1'\n    recordsize: 16k\n", "recordsize must be"),
        ("datasets:\n  Db:\n    owner: '1:1'\n", "name must be lowercase"),
        ("datasets:\n  db:\n    owner: '1:1'\n    dirs: [a, a]\n", "dirs has duplicates"),
        ("datasets:\n  db:\n    owner: '1:1'\n    dirs: [a/b]\n", "dirs must be a list"),
        ("datasets:\n  db:\n    owner: '1:1'\n    mode: 755\n", "mode must be a quoted octal"),
        ("datasets:\n  db:\n    owner: '1:1'\n    mode: '0778'\n", "mode must be a quoted octal"),
    ],
)
def test_invalid_storage_yml(root, text, error):
    write(root, "ansible/apps/youtarr/storage.yml", text)
    with pytest.raises(CatalogError) as e:
        storage.read_app(root, "youtarr")
    assert error in "\n".join(e.value.errors)


def test_no_problems(root):
    assert storage.problems(load(root)) == {}


def test_playbook_must_run_the_storage_role(root):
    write(root, "ansible/packer-debian-edge.yml", deploys("youtarr"))
    assert storage.problems(load(root)) == {
        "debian-edge": [
            "youtarr declares storage, but the playbook does not run app_storage for it"
        ]
    }


def test_the_storage_role_needs_a_storage_yml(root):
    write(
        root,
        "ansible/packer-debian-edge.yml",
        deploys("youtarr", "haproxy", stored=("youtarr", "haproxy")),
    )
    assert storage.problems(load(root)) == {
        "debian-edge": ["the playbook runs app_storage for haproxy, which has no storage.yml"]
    }


def test_the_storage_role_is_for_a_deployed_app(root):
    write(root, "ansible/packer-debian-edge.yml", deploys("haproxy", stored=("youtarr",)))
    assert storage.problems(load(root)) == {
        "debian-edge": ["the playbook runs app_storage for youtarr, but does not deploy it"]
    }


def test_a_dataset_declared_by_a_parent_layer_too_is_a_problem(root):
    write(root, "ansible/packer-debian-container.yml", deploys("youtarr", stored=("youtarr",)))
    problems = storage.problems(load(root))
    assert problems == {"debian-edge": ["debian-edge: youtarr/db declared twice"]}


def test_every_app_with_storage_needs_a_slot():
    no_slot = IdMap(start=2000000, size=65536, slots={})
    datasets = [storage.Dataset("youtarr", "db", "999:999", None, ())]
    assert storage.range_problems(no_slot, datasets) == [
        "ansible/apps/idmap.yml: no slot for youtarr"
    ]


def test_owner_must_fit_the_app_range(root):
    small = IdMap(start=2000000, size=1000, slots={"youtarr": 1})
    found = storage.range_problems(small, storage.read_app(root, "youtarr"))
    assert found == [
        "apps/youtarr/storage.yml: data: owner 1000:1000 is outside the app's 1000 IDs"
    ]


def test_missing_idmap_is_a_problem(root):
    (root / "ansible/apps/idmap.yml").unlink()
    assert storage.problems(load(root)) == {
        "debian-edge": ["apps declare storage but ansible/apps/idmap.yml does not exist"]
    }
