import textwrap
from pathlib import Path

import pytest
from conftest import copy_catalog

from imagectl import storage
from imagectl.catalog import CatalogError, StorageConfig, load
from imagectl.idmap import IdMap

IDMAP = """\
start: 2000000
size: 65536
slots:
  youtarr: 1
"""
QUADLET = "[Container]\nImage=x.image\nSubUIDMap=youtarr\nSubGIDMap=youtarr\n"
RANGES = IdMap(start=2000000, size=65536, slots={"youtarr": 1})

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


def deploys(*apps: str, roles: tuple[str, ...] = ()) -> str:
    items = "".join(f"    - role: {r}\n" for r in roles)
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
        deploys("youtarr", "haproxy", roles=("app_storage",)),
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


def test_ansible_vars(root):
    datasets = storage.read_app(root, "youtarr")
    config = StorageConfig("nfs.example.net", "/mnt/tank/apps")
    assert storage.ansible_vars(config, RANGES, datasets) == {
        "app_storage_mounts": [
            {
                "unit": "srv-youtarr-db.mount",
                "what": "nfs.example.net:/mnt/tank/apps/youtarr/db",
                "where": "/srv/youtarr/db",
            },
            {
                "unit": "srv-youtarr-data.mount",
                "what": "nfs.example.net:/mnt/tank/apps/youtarr/data",
                "where": "/srv/youtarr/data",
            },
        ],
        "app_storage_apps": [
            {
                "app": "youtarr",
                "id_base": 2065536,
                "id_count": 65536,
                "datasets": [
                    {"where": "/srv/youtarr/db", "owner": "2066535:2066535", "dirs": []},
                    {
                        "where": "/srv/youtarr/data",
                        "owner": "2066536:2066536",
                        "dirs": ["/srv/youtarr/data/config", "/srv/youtarr/data/jobs"],
                    },
                ],
            }
        ],
    }


def test_ansible_vars_pass_a_dataset_mode(root):
    write(
        root,
        "ansible/apps/youtarr/storage.yml",
        "datasets:\n  media:\n    owner: '1:1'\n    mode: '0755'\n",
    )
    config = StorageConfig("nfs.example.net", "/mnt/tank/apps")
    found = storage.ansible_vars(config, RANGES, storage.read_app(root, "youtarr"))
    assert found["app_storage_apps"][0]["datasets"] == [
        {"where": "/srv/youtarr/media", "owner": "2065537:2065537", "dirs": [], "mode": "0755"}
    ]


def test_ansible_vars_without_storage_need_no_config():
    assert storage.ansible_vars(None, None, []) == {
        "app_storage_mounts": [],
        "app_storage_apps": [],
    }


def test_ansible_vars_need_config_when_apps_declare_storage(root):
    with pytest.raises(CatalogError, match="no config.storage"):
        storage.ansible_vars(None, RANGES, storage.read_app(root, "youtarr"))


def test_mount_unit_escapes_dashes():
    assert storage.mount_unit("/srv/caddy-lab/data") == "srv-caddy\\x2dlab-data.mount"


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
        "debian-edge": ["its apps declare storage but the playbook does not run role app_storage"]
    }


def test_a_dataset_declared_by_a_parent_layer_too_is_a_problem(root):
    write(root, "ansible/packer-debian-container.yml", deploys("youtarr", roles=("app_storage",)))
    problems = storage.problems(load(root))
    assert problems == {"debian-edge": ["debian-edge: youtarr/db declared twice"]}


def test_ansible_vars_need_a_slot_for_every_app_with_storage(root):
    config = StorageConfig("nfs.example.net", "/mnt/tank/apps")
    no_slot = IdMap(start=2000000, size=65536, slots={})
    with pytest.raises(CatalogError, match="no slot for youtarr"):
        storage.ansible_vars(config, no_slot, storage.read_app(root, "youtarr"))


def test_owner_must_fit_the_app_range(root):
    config = StorageConfig("nfs.example.net", "/mnt/tank/apps")
    small = IdMap(start=2000000, size=1000, slots={"youtarr": 1})
    with pytest.raises(CatalogError, match="owner 1000:1000 is outside the app's 1000 IDs"):
        storage.ansible_vars(config, small, storage.read_app(root, "youtarr"))


@pytest.mark.parametrize(
    ("quadlet", "error"),
    [
        ("[Container]\nSubUIDMap=youtarr\n", "needs SubGIDMap=youtarr"),
        ("[Container]\n", "needs SubGIDMap=youtarr and SubUIDMap=youtarr"),
        (QUADLET + "UserNS=auto\n", "UserNS=auto conflicts with the app's ID range"),
        (
            "[Container]\nSubUIDMap=other\nSubGIDMap=youtarr\n",
            "SubUIDMap=other conflicts with the app's ID range",
        ),
    ],
)
def test_containers_of_an_app_with_storage_use_its_range(root, quadlet, error):
    write(root, "ansible/apps/youtarr/quadlet/youtarr.container", quadlet)
    problems = storage.problems(load(root))
    assert any(error in p for p in problems["debian-edge"]), problems


def test_missing_idmap_is_a_problem(root):
    (root / "ansible/apps/idmap.yml").unlink()
    assert storage.problems(load(root)) == {
        "debian-edge": ["apps declare storage but ansible/apps/idmap.yml does not exist"]
    }
