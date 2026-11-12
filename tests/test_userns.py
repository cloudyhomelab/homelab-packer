import textwrap
from pathlib import Path

import pytest
from conftest import copy_catalog

from imagectl import userns
from imagectl.catalog import load

IDMAP = "start: 2000000\nsize: 65536\nslots:\n  youtarr: 1\n"
QUADLET = "[Container]\nImage=x.image\nSubUIDMap=youtarr\nSubGIDMap=youtarr\n"


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


def deploys(*apps: str, ranges: tuple[str, ...] = ()) -> str:
    items = "".join(f"    - role: app_idmap\n      app_idmap_app: {app}\n" for app in ranges)
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
    write(tmp_path, "ansible/roles/app_idmap/tasks/main.yml", "- ansible.builtin.debug: {}\n")
    write(
        tmp_path,
        "ansible/packer-debian-edge.yml",
        deploys("youtarr", "haproxy", ranges=("youtarr",)),
    )
    write(tmp_path, "ansible/apps/youtarr/quadlet/youtarr.container", QUADLET)
    write(tmp_path, "ansible/apps/haproxy/quadlet/haproxy.container", "[Container]\n")
    write(tmp_path, "ansible/apps/idmap.yml", IDMAP)
    return tmp_path


def test_no_problems(root):
    assert userns.problems(load(root)) == {}


def test_an_app_needs_no_storage_for_its_range(root):
    assert not (root / "ansible/apps/youtarr/storage.yml").exists()
    assert userns.problems(load(root)) == {}


def test_an_app_with_a_slot_needs_the_role(root):
    write(root, "ansible/packer-debian-edge.yml", deploys("youtarr", "haproxy"))
    assert userns.problems(load(root)) == {
        "debian-edge": ["youtarr has a slot, but the playbook does not run app_idmap for it"]
    }


def test_the_role_needs_a_slot(root):
    write(root, "ansible/packer-debian-edge.yml", deploys("haproxy", ranges=("haproxy",)))
    assert userns.problems(load(root)) == {
        "debian-edge": [
            "the playbook runs app_idmap for haproxy, but ansible/apps/idmap.yml has no slot for it"
        ]
    }


def test_the_role_needs_an_idmap(root):
    (root / "ansible/apps/idmap.yml").unlink()
    problems = userns.problems(load(root))
    assert any("app_idmap for youtarr" in p for p in problems["debian-edge"]), problems


def test_a_templated_app_is_left_to_check_hash(root):
    write(
        root,
        "ansible/packer-debian-edge.yml",
        '- hosts: all\n  roles:\n    - role: app_idmap\n      app_idmap_app: "{{ app }}"\n',
    )
    assert userns.problems(load(root)) == {}


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
def test_containers_of_an_app_with_a_slot_use_its_range(root, quadlet, error):
    write(root, "ansible/apps/youtarr/quadlet/youtarr.container", quadlet)
    problems = userns.problems(load(root))
    assert any(error in p for p in problems["debian-edge"]), problems


def test_an_app_without_a_slot_names_no_range(root):
    write(root, "ansible/apps/haproxy/quadlet/haproxy.container", "[Container]\nSubUIDMap=x\n")
    assert userns.problems(load(root)) == {
        "debian-edge": [
            "apps/haproxy/quadlet/haproxy.container: SubUIDMap=x needs a slot for haproxy in "
            "ansible/apps/idmap.yml"
        ]
    }


def test_an_app_without_a_slot_may_use_an_automatic_range(root):
    write(root, "ansible/apps/haproxy/quadlet/haproxy.container", "[Container]\nUserNS=auto\n")
    assert userns.problems(load(root)) == {}
