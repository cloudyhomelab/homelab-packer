import subprocess
import textwrap
from pathlib import Path

import pytest
from conftest import copy_catalog

from imagectl import check_hash
from imagectl.catalog import load
from imagectl.check_hash import CheckHashError, resolve_roles

CHECK_HASH = """\
# every image
src/imagectl/packer.py
ansible/ansible.cfg
ansible/group_vars/**

# the image's OS
upstream/{os}/packer/**
!upstream/{os}/packer/README.md

# the image itself
ansible/{playbook}.yml
ansible/roles/{roles}/**
ansible/apps/{apps}/**
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
    write(tmp_path, ".check_hash", CHECK_HASH)
    write(tmp_path, ".gitignore", "/build/\n")
    write(tmp_path, "src/imagectl/packer.py", "# driver\n")
    write(tmp_path, "ansible/ansible.cfg", "[defaults]\n")
    write(tmp_path, "ansible/group_vars/all/vars.yml", "a: 1\n")
    write(tmp_path, "upstream/debian/packer/build.pkr.hcl", "build {}\n")
    write(tmp_path, "upstream/debian/packer/README.md", "notes\n")
    write(tmp_path, "build/debian-base/output.qcow2", "ignored\n")

    write(tmp_path, "ansible/packer-debian-base.yml", playbook("system"))
    write(
        tmp_path,
        "ansible/packer-debian-kubernetes.yml",
        """\
        - hosts: all
          tasks:
            - name: pull in kubernetes
              ansible.builtin.include_role:
                name: kubernetes
        """,
    )
    write(tmp_path, "ansible/packer-debian-container.yml", playbook("podman"))
    for name in ("debian-honeypot", "fedora-base", "fedora-kubernetes", "fedora-container"):
        write(tmp_path, f"ansible/packer-{name}.yml", playbook("system"))
    write(tmp_path, "ansible/packer-fedora-edge.yml", playbook("system"))
    write(tmp_path, "ansible/roles/system/tasks/main.yml", "- ansible.builtin.debug: {}\n")
    write(tmp_path, "ansible/roles/kubernetes/tasks/main.yml", "- ansible.builtin.debug: {}\n")
    write(tmp_path, "ansible/roles/kubernetes/meta/main.yml", "dependencies:\n  - role: kubelet\n")
    write(tmp_path, "ansible/roles/kubelet/tasks/main.yml", "- ansible.builtin.debug: {}\n")
    write(
        tmp_path,
        "ansible/roles/podman/tasks/main.yml",
        """\
        - block:
            - ansible.builtin.import_role:
                name: registry
        """,
    )
    write(tmp_path, "ansible/roles/registry/tasks/main.yml", "- ansible.builtin.debug: {}\n")
    write(tmp_path, "ansible/roles/unused/tasks/main.yml", "- ansible.builtin.debug: {}\n")
    write(
        tmp_path,
        "ansible/packer-debian-edge.yml",
        """\
        - hosts: all
          roles:
            - role: binarycodes.homelab.systemd_app
              systemd_app_kind: source
              systemd_app_name: haproxy
        """,
    )
    write(
        tmp_path,
        "ansible/packer-debian-media.yml",
        """\
        - hosts: all
          roles:
            - role: binarycodes.homelab.systemd_app
              systemd_app_kind: source
              systemd_app_name: immich
          tasks:
            - name: deploy caddy
              ansible.builtin.include_role:
                name: binarycodes.homelab.systemd_app
              vars:
                systemd_app_kind: source
                systemd_app_name: caddy
        """,
    )
    write(tmp_path, "ansible/apps/haproxy/config/haproxy.cfg", "global\n")
    write(tmp_path, "ansible/apps/immich/config/immich.env", "TZ=UTC\n")
    write(tmp_path, "ansible/apps/caddy/config/Caddyfile", "x {}\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def hashes(root: Path) -> dict[str, str]:
    result = check_hash.compute_all(load(root))
    assert not result.errors
    return result.hashes


def test_placeholders_expand_per_image(tree):
    result = check_hash.compute_all(load(tree))
    assert result.files["debian-kubernetes"] == [
        "ansible/ansible.cfg",
        "ansible/group_vars/all/vars.yml",
        "ansible/packer-debian-kubernetes.yml",
        "ansible/roles/kubelet/tasks/main.yml",
        "ansible/roles/kubernetes/meta/main.yml",
        "ansible/roles/kubernetes/tasks/main.yml",
        "src/imagectl/packer.py",
        "upstream/debian/packer/build.pkr.hcl",
    ]
    assert result.unmatched == []


def test_role_resolution_follows_meta_dependencies_and_static_includes(tree):
    assert resolve_roles(tree, "packer-debian-kubernetes") == ["kubelet", "kubernetes"]
    assert resolve_roles(tree, "packer-debian-container") == ["podman", "registry"]


def test_negation_excludes_files(tree):
    files = check_hash.compute_all(load(tree)).files["debian-base"]
    assert "upstream/debian/packer/README.md" not in files


def test_gitignored_files_are_not_hashed(tree):
    before = hashes(tree)
    write(tree, "build/debian-base/output.qcow2", "changed\n")
    assert hashes(tree) == before


def test_role_change_rebuilds_only_its_users(tree):
    before = hashes(tree)
    write(tree, "ansible/roles/kubelet/tasks/main.yml", "- ansible.builtin.debug: {msg: x}\n")
    after = hashes(tree)
    assert [n for n in before if before[n] != after[n]] == ["debian-kubernetes"]


def test_shared_file_rebuilds_every_image(tree):
    before = hashes(tree)
    write(tree, "src/imagectl/packer.py", "# changed\n")
    after = hashes(tree)
    assert all(before[n] != after[n] for n in before)


def test_settings_are_part_of_the_hash(tree):
    before = hashes(tree)
    images = (
        (tree / "images.yml")
        .read_text()
        .replace("- kubernetes\n", "- kubernetes:\n" + " " * 12 + "memory: 4096\n", 1)
    )
    (tree / "images.yml").write_text(images)
    after = hashes(tree)
    assert [n for n in before if before[n] != after[n]] == ["debian-kubernetes"]


def test_max_age_and_retain_are_not_part_of_the_hash(tree):
    before = hashes(tree)
    images = (
        (tree / "images.yml")
        .read_text()
        .replace(
            "- kubernetes\n",
            "- kubernetes:\n" + " " * 12 + "max_age_days: 1\n" + " " * 12 + "retain_images: 2\n",
            1,
        )
    )
    (tree / "images.yml").write_text(images)
    assert hashes(tree) == before


def test_pattern_matching_nothing_is_reported(tree):
    write(tree, ".check_hash", CHECK_HASH + "ansible/requirements.yml\n")
    result = check_hash.compute_all(load(tree))
    assert [r.template for r in result.unmatched] == ["ansible/requirements.yml"]


def test_templated_role_name_is_an_error(tree):
    write(tree, "ansible/packer-debian-container.yml", playbook("{{ runtime }}"))
    result = check_hash.compute_all(load(tree))
    assert "templated" in result.errors["debian-container"]
    assert "debian-base" in result.hashes


def test_templated_include_role_is_an_error(tree):
    write(
        tree,
        "ansible/roles/podman/tasks/main.yml",
        '- ansible.builtin.include_role:\n    name: "{{ item }}"\n',
    )
    with pytest.raises(CheckHashError, match="templated"):
        resolve_roles(tree, "packer-debian-container")


def test_missing_playbook_is_a_per_image_error(tree):
    (tree / "ansible/packer-debian-container.yml").unlink()
    result = check_hash.compute_all(load(tree))
    assert "does not exist" in result.errors["debian-container"]
    assert set(result.hashes) == set(load(tree).images) - {"debian-container"}


def test_apps_resolved_from_role_entries_and_include_role(tree):
    assert check_hash.resolve_apps(tree, "packer-debian-media", []) == ["caddy", "immich"]
    files = check_hash.compute_all(load(tree)).files
    assert "ansible/apps/haproxy/config/haproxy.cfg" in files["debian-edge"]
    assert not any(f.startswith("ansible/apps/") for f in files["debian-base"])


def test_app_change_rebuilds_only_its_images(tree):
    before = hashes(tree)
    write(tree, "ansible/apps/caddy/config/Caddyfile", "y {}\n")
    after = hashes(tree)
    assert [n for n in before if before[n] != after[n]] == ["debian-media"]


def test_templated_app_name_is_an_error(tree):
    write(
        tree,
        "ansible/packer-debian-edge.yml",
        "- hosts: all\n  roles:\n    - role: binarycodes.homelab.systemd_app\n"
        '      systemd_app_name: "{{ app }}"\n',
    )
    result = check_hash.compute_all(load(tree))
    assert "templated" in result.errors["debian-edge"]


def test_app_call_without_a_name_is_an_error(tree):
    write(
        tree,
        "ansible/packer-debian-edge.yml",
        "- hosts: all\n  roles:\n    - role: binarycodes.homelab.systemd_app\n"
        "      systemd_app_kind: source\n",
    )
    result = check_hash.compute_all(load(tree))
    assert "without a systemd_app_name" in result.errors["debian-edge"]
