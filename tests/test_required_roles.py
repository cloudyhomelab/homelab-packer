import textwrap
from pathlib import Path

import pytest
from conftest import copy_catalog

from imagectl.catalog import CatalogError, load
from imagectl.required_roles import missing_roles, read_requirements

TASK = "- ansible.builtin.debug: {}\n"
REQUIRED_ROLES = """\
- folder: ansible/nftables/{playbook}
  role: nftables_dropins
"""


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


def playbook(*roles: str) -> str:
    items = "".join(f"    - role: {r}\n" for r in roles)
    return f"- hosts: all\n  roles:\n{items}"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    copy_catalog(tmp_path)
    write(tmp_path, "required_roles.yml", REQUIRED_ROLES)
    write(tmp_path, "ansible/roles/nftables_dropins/tasks/main.yml", TASK)
    write(tmp_path, "ansible/roles/kubernetes/tasks/main.yml", TASK)
    return tmp_path


def test_no_file_means_no_requirements(tmp_path: Path):
    copy_catalog(tmp_path)
    assert read_requirements(tmp_path) == []
    assert missing_roles(load(tmp_path)) == {}


def test_playbook_without_the_folder_needs_nothing(tree: Path):
    write(tree, "ansible/packer-debian-kubernetes.yml", playbook("kubernetes"))
    assert missing_roles(load(tree)) == {}


def test_playbook_with_the_folder_and_the_role_passes(tree: Path):
    write(tree, "ansible/packer-debian-kubernetes.yml", playbook("kubernetes", "nftables_dropins"))
    write(tree, "ansible/nftables/packer-debian-kubernetes/20-kubernetes.nft", "\n")
    assert missing_roles(load(tree)) == {}


def test_role_pulled_in_by_another_role_counts(tree: Path):
    write(tree, "ansible/roles/kubernetes/meta/main.yml", "dependencies:\n  - nftables_dropins\n")
    write(tree, "ansible/packer-debian-kubernetes.yml", playbook("kubernetes"))
    write(tree, "ansible/nftables/packer-debian-kubernetes/20-kubernetes.nft", "\n")
    assert missing_roles(load(tree)) == {}


def test_playbook_with_the_folder_but_without_the_role_fails(tree: Path):
    write(tree, "ansible/packer-debian-kubernetes.yml", playbook("kubernetes"))
    write(tree, "ansible/nftables/packer-debian-kubernetes/20-kubernetes.nft", "\n")
    assert missing_roles(load(tree)) == {
        "debian-kubernetes": [
            "ansible/nftables/packer-debian-kubernetes exists"
            " but the playbook does not run role nftables_dropins"
        ]
    }


@pytest.mark.parametrize(
    "text",
    [
        "folder: ansible/nftables/{playbook}\n",
        "- folder: ansible/nftables/{playbook}\n",
        "- folder: ansible/nftables/{playbook}\n  role: x\n  extra: y\n",
        "- folder: ansible/nftables/{playbook}\n  role: ''\n",
        "- folder: ansible/nftables/shared\n  role: x\n",
    ],
)
def test_invalid_file_is_rejected(tmp_path: Path, text: str):
    write(tmp_path, "required_roles.yml", text)
    with pytest.raises(CatalogError):
        read_requirements(tmp_path)
