import textwrap
from pathlib import Path

import pytest

from imagectl.catalog import load

UPSTREAM_YML = """\
debian-cloud:
  os: debian
  index: https://cdimage.debian.org/images/cloud/trixie/
  image_file: "{version}/debian-13-genericcloud-amd64-{version}.qcow2"
  checksum_file: "{version}/SHA512SUMS"
  version: "20260914-2601"
  checksum: "sha512:DEBIAN_SUM"
fedora-cloud:
  os: fedora
  index: https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Cloud/x86_64/images/
  image_file: "Fedora-Cloud-Base-Generic-44-{version}.x86_64.qcow2"
  checksum_file: "Fedora-Cloud-44-{version}-x86_64-CHECKSUM"
  version: "1.7"
  checksum: "sha256:FEDORA_SUM"
""".replace("DEBIAN_SUM", "a" * 128).replace("FEDORA_SUM", "b" * 64)

CONFIG = """\
config:
  s3:
    endpoint: https://s3.example.net
    region: home
    bucket: os-image-staging
  naming:
    image_name: "{os}-{key}"
    playbook: "packer-{os}-{key}"
    s3_prefix: "{os}"

defaults:
  disk_size: 5G
  memory: 2048
  cpus: 2
  max_age_days: 7
  retain_images: 5

"""

IMAGES = """\
images:
  - base:
      from: debian-cloud
      disk_size: 3G
      children:
        - kubernetes
        - container:
            disk_size: 3G
            children:
              - edge
  - base:
      from: fedora-cloud
      children:
        - kubernetes
        - container:
            children:
              - edge
"""


def write_catalog(root: Path, images: str = IMAGES, upstream: str = UPSTREAM_YML) -> None:
    (root / "images.yml").write_text(CONFIG + textwrap.dedent(images))
    (root / "upstream.yml").write_text(upstream)


@pytest.fixture
def catalog_root(tmp_path: Path) -> Path:
    write_catalog(tmp_path)
    return tmp_path


@pytest.fixture
def catalog(catalog_root: Path):
    return load(catalog_root)
