from pathlib import Path

import pytest
from conftest import INVALID, copy_catalog

from imagectl.catalog import CatalogError, load


def expected_error(path: Path) -> str:
    first = path.read_text().splitlines()[0]
    assert first.startswith("# error: "), f"{path} must start with '# error: <message>'"
    return first.removeprefix("# error: ")


def load_errors(root: Path) -> str:
    with pytest.raises(CatalogError) as e:
        load(root)
    return "\n".join(e.value.errors)


@pytest.mark.parametrize("case", sorted((INVALID / "images").glob("*.yml")), ids=lambda p: p.stem)
def test_invalid_images_yml(tmp_path, case):
    copy_catalog(tmp_path, images=case)
    assert expected_error(case) in load_errors(tmp_path)


@pytest.mark.parametrize("case", sorted((INVALID / "upstream").glob("*.yml")), ids=lambda p: p.stem)
def test_invalid_upstream_yml(tmp_path, case):
    copy_catalog(tmp_path, upstream=case)
    assert expected_error(case) in load_errors(tmp_path)


def test_every_image_is_resolved(catalog):
    assert [i.name for i in catalog.ordered()] == [
        "debian-base",
        "debian-kubernetes",
        "debian-container",
        "debian-edge",
        "debian-honeypot",
        "debian-media",
        "fedora-base",
        "fedora-kubernetes",
        "fedora-container",
        "fedora-edge",
    ]


def test_naming_fills_os_and_key(catalog):
    edge = catalog.get("debian-edge")
    assert (edge.name, edge.playbook, edge.s3_prefix) == (
        "debian-edge",
        "packer-debian-edge",
        "debian",
    )
    assert catalog.get("fedora-edge").playbook == "packer-fedora-edge"


def test_the_same_key_in_two_oses(catalog):
    assert catalog.get("debian-base").os == "debian"
    assert catalog.get("fedora-base").os == "fedora"


def test_os_comes_from_the_upstream(catalog):
    assert catalog.get("fedora-edge").os == "fedora"


def test_overrides_and_defaults(catalog):
    base = catalog.get("debian-base")
    assert (base.disk_size, base.memory, base.cpus) == ("3G", 1024, 2)
    media = catalog.get("debian-media")
    assert (media.disk_size, media.memory, media.cpus) == ("5G", 8192, 4)
    honeypot = catalog.get("debian-honeypot")
    assert (honeypot.max_age_days, honeypot.retain_images) == (1, 2)


def test_nothing_is_inherited_from_the_parent(catalog):
    assert catalog.get("debian-container").disk_size == "4G"
    edge = catalog.get("debian-edge")
    assert (edge.disk_size, edge.memory, edge.max_age_days, edge.retain_images) == (
        "5G",
        2048,
        7,
        5,
    )


def test_bare_name_and_empty_mapping_take_defaults(catalog):
    for name in ("debian-kubernetes", "fedora-kubernetes"):
        image = catalog.get(name)
        assert (image.disk_size, image.memory, image.cpus) == ("5G", 2048, 2)


def test_parents_and_tree_order(catalog):
    names = [i.name for i in catalog.ordered()]
    for image in catalog.ordered():
        if image.parent:
            assert names.index(image.parent) < names.index(image.name)
    assert catalog.get("debian-honeypot").parent == "debian-container"
    assert catalog.get("debian-base").upstream == "debian-cloud"
    assert catalog.get("debian-container").upstream is None
    assert [i.name for i in catalog.descendants("debian-container")] == [
        "debian-edge",
        "debian-honeypot",
        "debian-media",
    ]
    assert [i.name for i in catalog.ancestors("debian-media")] == [
        "debian-container",
        "debian-base",
    ]


def test_upstream_source_url_for_both_lookup_shapes(catalog):
    debian = catalog.upstream_source(catalog.get("debian-base"))
    assert debian.name == "debian-cloud"
    assert debian.url == (
        "https://cdimage.debian.org/images/cloud/trixie/20260914-2601/"
        "debian-13-genericcloud-amd64-20260914-2601.qcow2"
    )
    assert debian.checksum == "sha512:" + "a" * 128
    fedora = catalog.upstream_source(catalog.get("fedora-base"))
    assert fedora.url.endswith("/Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2")
    assert fedora.checksum == "sha256:" + "b" * 64


def test_unused_upstream_is_allowed(catalog):
    assert "ubuntu-cloud" in catalog.upstreams
    assert not any(i.upstream == "ubuntu-cloud" for i in catalog.ordered())
