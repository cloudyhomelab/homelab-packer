from pathlib import Path

import pytest
from conftest import UPSTREAM_YML, write_catalog

from imagectl.catalog import CatalogError, load


def errors_for(tmp_path: Path, images: str | None = None, upstream: str = UPSTREAM_YML) -> str:
    if images is None:
        write_catalog(tmp_path, upstream=upstream)
    else:
        write_catalog(tmp_path, images=images, upstream=upstream)
    with pytest.raises(CatalogError) as e:
        load(tmp_path)
    return "\n".join(e.value.errors)


def test_naming_fills_os_and_key(catalog):
    edge = catalog.get("debian-edge")
    assert edge.playbook == "packer-debian-edge"
    assert edge.s3_prefix == "debian"
    assert catalog.get("fedora-edge").playbook == "packer-fedora-edge"


def test_defaults_and_overrides_without_inheritance(catalog):
    assert catalog.get("debian-base").disk_size == "3G"
    assert catalog.get("debian-container").disk_size == "3G"
    # edge sits under a 3G parent but takes the default, never the parent's value
    assert catalog.get("debian-edge").disk_size == "5G"
    assert catalog.get("debian-kubernetes").memory == 2048
    assert catalog.get("debian-edge").retain_images == 5


def test_tree_order_and_parents(catalog):
    names = [i.name for i in catalog.ordered()]
    for image in catalog.ordered():
        if image.parent:
            assert names.index(image.parent) < names.index(image.name)
    assert catalog.get("debian-edge").parent == "debian-container"
    assert catalog.get("debian-base").upstream == "debian-cloud"
    assert [i.name for i in catalog.descendants("debian-base")] == [
        "debian-kubernetes",
        "debian-container",
        "debian-edge",
    ]
    assert [i.name for i in catalog.ancestors("debian-edge")] == [
        "debian-container",
        "debian-base",
    ]


def test_os_comes_from_the_upstream(catalog):
    assert catalog.get("fedora-edge").os == "fedora"


def test_upstream_source_url(catalog):
    source = catalog.upstream_source(catalog.get("debian-base"))
    assert source.name == "debian-cloud"
    assert source.url == (
        "https://cdimage.debian.org/images/cloud/trixie/20260914-2601/"
        "debian-13-genericcloud-amd64-20260914-2601.qcow2"
    )
    assert source.checksum == "sha512:" + "a" * 128


def test_duplicate_yaml_key(tmp_path):
    images = """\
    images:
      - base:
          from: debian-cloud
          disk_size: 3G
          disk_size: 4G
    """
    assert "duplicate" in errors_for(tmp_path, images).lower()


def test_key_repeated_within_an_os(tmp_path):
    images = """\
    images:
      - base:
          from: debian-cloud
          children:
            - base
    """
    assert "repeated within os 'debian'" in errors_for(tmp_path, images)


def test_key_allowed_across_oses(catalog):
    assert {"debian-base", "fedora-base"} <= set(catalog.images)


def test_bare_name_and_mapping_items(tmp_path):
    write_catalog(
        tmp_path,
        images="""\
        images:
          - base:
              from: debian-cloud
              children:
                - plain
                - tuned:
                    memory: 4096
                - empty:
        """,
    )
    catalog = load(tmp_path)
    assert catalog.get("debian-plain").memory == 2048
    assert catalog.get("debian-tuned").memory == 4096
    assert catalog.get("debian-empty").parent == "debian-base"


def test_two_key_item_from_an_indentation_slip(tmp_path):
    images = """\
    images:
      - base:
          from: debian-cloud
          children:
            - container:
              disk_size: 3G
    """
    assert "item has 2 keys (container, disk_size)" in errors_for(tmp_path, images)


def test_item_neither_name_nor_mapping(tmp_path):
    images = """\
    images:
      - base:
          from: debian-cloud
          children:
            - [a, b]
    """
    assert "neither a name nor a one-key mapping" in errors_for(tmp_path, images)


def test_missing_from(tmp_path):
    images = """\
    images:
      - base:
          disk_size: 3G
    """
    assert "a top-level image must set from" in errors_for(tmp_path, images)


def test_nested_from(tmp_path):
    images = """\
    images:
      - base:
          from: debian-cloud
          children:
            - kid:
                from: debian-cloud
    """
    assert "only a top-level image sets from" in errors_for(tmp_path, images)


def test_from_names_a_missing_upstream(tmp_path):
    images = """\
    images:
      - base:
          from: ubuntu-cloud
    """
    assert "'ubuntu-cloud' is not a key in upstream.yml" in errors_for(tmp_path, images)


def test_unknown_field(tmp_path):
    images = """\
    images:
      - base:
          from: debian-cloud
          playbook: custom
    """
    assert "unknown fields ['playbook']" in errors_for(tmp_path, images)


def test_name_collision_after_template(tmp_path):
    write_catalog(tmp_path)
    text = (tmp_path / "images.yml").read_text().replace('"{os}-{key}"', '"{key}"', 1)
    (tmp_path / "images.yml").write_text(text)
    with pytest.raises(CatalogError) as e:
        load(tmp_path)
    assert "image name 'base' collides" in str(e.value)


def test_unquoted_version(tmp_path):
    upstream = UPSTREAM_YML.replace('version: "1.7"', "version: 1.10")
    assert "version must be a quoted string, got 1.1" in errors_for(tmp_path, upstream=upstream)


def test_missing_version(tmp_path):
    upstream = UPSTREAM_YML.replace('  version: "1.7"\n', "")
    assert "fedora-cloud: missing fields ['version']" in errors_for(tmp_path, upstream=upstream)


def test_malformed_checksum(tmp_path):
    upstream = UPSTREAM_YML.replace("sha256:" + "b" * 64, "sha256:" + "b" * 60)
    assert "sha256 hash must be 64 hex characters" in errors_for(tmp_path, upstream=upstream)
    upstream = UPSTREAM_YML.replace("sha256:" + "b" * 64, "b" * 64)
    assert "must look like sha256:<hex>" in errors_for(tmp_path, upstream=upstream)


def test_unknown_upstream_field(tmp_path):
    upstream = UPSTREAM_YML.replace("  os: fedora\n", "  os: fedora\n  type: fedora\n")
    assert "fedora-cloud: unknown fields ['type']" in errors_for(tmp_path, upstream=upstream)


def test_unused_upstream_is_allowed(tmp_path):
    write_catalog(
        tmp_path,
        images="""\
        images:
          - base:
              from: debian-cloud
        """,
    )
    assert list(load(tmp_path).images) == ["debian-base"]


def test_retain_images_at_least_one(tmp_path):
    images = """\
    images:
      - base:
          from: debian-cloud
          retain_images: 0
    """
    assert "retain_images must be an integer >= 1" in errors_for(tmp_path, images)


def test_max_age_days_zero_is_allowed(tmp_path):
    write_catalog(
        tmp_path,
        images="""\
        images:
          - base:
              from: debian-cloud
              max_age_days: 0
        """,
    )
    assert load(tmp_path).get("debian-base").max_age_days == 0


def test_repo_catalog_loads():
    root = Path(__file__).resolve().parents[1]
    catalog = load(root)
    assert len(catalog.images) == 8
    assert catalog.get("debian-edge").parent == "debian-container"
