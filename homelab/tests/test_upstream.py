from pathlib import Path

import pytest
from conftest import CATALOG

from imagectl import upstream
from imagectl.catalog import Upstream
from imagectl.upstream import (
    Release,
    UpstreamError,
    find_newest,
    natural_key,
    parse_checksums,
    rewrite_pins,
)

FIXTURES = Path(__file__).parent / "fixtures" / "upstream"
UPSTREAM_YML = (CATALOG / "upstream.yml").read_text()

DEBIAN = Upstream(
    key="debian-cloud",
    os="debian",
    index="https://cdimage.debian.org/images/cloud/trixie/",
    image_file="{version}/debian-13-genericcloud-amd64-{version}.qcow2",
    checksum_file="{version}/SHA512SUMS",
    version="20260831-2587",
    checksum="sha512:" + "0" * 128,
)
FEDORA = Upstream(
    key="fedora-cloud",
    os="fedora",
    index="https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Cloud/x86_64/images/",
    image_file="Fedora-Cloud-Base-Generic-44-{version}.x86_64.qcow2",
    checksum_file="Fedora-Cloud-44-{version}-x86_64-CHECKSUM",
    version="1.6",
    checksum="sha256:" + "0" * 64,
)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def fake_fetch(pages: dict[str, str]):
    def fetch(url: str) -> str:
        if url not in pages:
            raise OSError(f"unexpected fetch {url}")
        return pages[url]

    return fetch


DEBIAN_PAGES = {
    DEBIAN.index: fixture("debian-index.html"),
    DEBIAN.index + "20260914-2601/SHA512SUMS": fixture("debian-SHA512SUMS"),
}
FEDORA_PAGES = {
    FEDORA.index: fixture("fedora-index.html"),
    FEDORA.index + "Fedora-Cloud-44-1.7-x86_64-CHECKSUM": fixture("fedora-CHECKSUM"),
}


def test_debian_lookup_on_saved_pages():
    release = find_newest(DEBIAN, fake_fetch(DEBIAN_PAGES))
    assert release.version == "20260914-2601"
    assert release.url == (
        DEBIAN.index + "20260914-2601/debian-13-genericcloud-amd64-20260914-2601.qcow2"
    )
    assert release.checksum == (
        "sha512:95e110dfcdbd0ed8a82a75ed9579802f9950cabf51a810dcc6388e81bc778188"
        "713878b9f28d583a0ea602fbf48b35996ae9ad37f584166d8fbd6489df248f53"
    )


def test_fedora_lookup_on_saved_pages():
    release = find_newest(FEDORA, fake_fetch(FEDORA_PAGES))
    assert release.version == "1.7"
    assert release.url == FEDORA.index + "Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2"
    assert release.checksum == (
        "sha256:28680fe5b371a5a82ebf43a31926e086a168e59949d03969c5093e7071f90b7f"
    )


def test_natural_sort():
    assert sorted(["1.9", "1.10", "1.2"], key=natural_key) == ["1.2", "1.9", "1.10"]


def test_highest_version_by_natural_sort():
    pages = {
        FEDORA.index: "".join(
            f'<a href="Fedora-Cloud-Base-Generic-44-{v}.x86_64.qcow2">x</a>'
            for v in ("1.9", "1.10", "1.2")
        ),
        FEDORA.index + "Fedora-Cloud-44-1.10-x86_64-CHECKSUM": (
            "SHA256 (Fedora-Cloud-Base-Generic-44-1.10.x86_64.qcow2) = " + "c" * 64
        ),
    }
    assert find_newest(FEDORA, fake_fetch(pages)).version == "1.10"


def test_parse_gnu_and_bsd_checksums():
    gnu = parse_checksums(f"{'a' * 128}  foo.qcow2\n{'b' * 64} *bar.qcow2\n")
    assert gnu == {"foo.qcow2": "sha512:" + "a" * 128, "bar.qcow2": "sha256:" + "b" * 64}
    bsd = parse_checksums(f"# comment\nSHA256 (foo.qcow2) = {'c' * 64}\n")
    assert bsd == {"foo.qcow2": "sha256:" + "c" * 64}


def test_rejects_missing_checksum_entry():
    pages = dict(FEDORA_PAGES)
    pages[FEDORA.index + "Fedora-Cloud-44-1.7-x86_64-CHECKSUM"] = "SHA256 (other) = " + "c" * 64
    with pytest.raises(UpstreamError, match="no checksum for"):
        find_newest(FEDORA, fake_fetch(pages))


def test_rejects_empty_lookup():
    pages = {FEDORA.index: '<a href="unrelated.txt">x</a>'}
    with pytest.raises(UpstreamError, match="no version matching"):
        find_newest(FEDORA, fake_fetch(pages))


def test_rejects_hash_of_wrong_length():
    pages = dict(FEDORA_PAGES)
    pages[FEDORA.index + "Fedora-Cloud-44-1.7-x86_64-CHECKSUM"] = (
        "SHA256 (Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2) = " + "c" * 60
    )
    with pytest.raises(UpstreamError, match="64 hex characters"):
        find_newest(FEDORA, fake_fetch(pages))


HAND_FORMATTED = """\
# upstream images; `imagectl upstream --update` moves version and checksum
debian-cloud:
  os: debian   # trixie
  index: https://cdimage.debian.org/images/cloud/trixie/
  image_file: "{version}/debian-13-genericcloud-amd64-{version}.qcow2"
  checksum_file: '{version}/SHA512SUMS'
  version:   "20260831-2587"    # pinned by hand once
  checksum: "sha512:DEBIAN_SUM"

fedora-cloud:
  os: fedora
  index: https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Cloud/x86_64/images/
  image_file: "Fedora-Cloud-Base-Generic-44-{version}.x86_64.qcow2"
  checksum_file: "Fedora-Cloud-44-{version}-x86_64-CHECKSUM"
  version: '1.6'
  checksum: 'sha256:FEDORA_SUM'
""".replace("DEBIAN_SUM", "0" * 128).replace("FEDORA_SUM", "0" * 64)


def test_rewrite_changes_only_version_and_checksum_lines():
    new = rewrite_pins(
        HAND_FORMATTED,
        {
            "debian-cloud": Release("20260914-2601", "u", "sha512:" + "1" * 128),
            "fedora-cloud": Release("1.7", "u", "sha256:" + "2" * 64),
        },
    )
    old_lines, new_lines = HAND_FORMATTED.splitlines(True), new.splitlines(True)
    assert len(old_lines) == len(new_lines)
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines, strict=True)) if a != b]
    assert [old_lines[i].split(":")[0].strip() for i in changed] == [
        "version",
        "checksum",
        "version",
        "checksum",
    ]
    assert new_lines[6] == '  version:   "20260914-2601"    # pinned by hand once\n'
    assert new_lines[14] == "  version: '1.7'\n"
    assert new_lines[15] == "  checksum: 'sha256:" + "2" * 64 + "'\n"


def test_update_writes_upstream_yml_only_when_newer(tmp_path):
    text = UPSTREAM_YML.replace('"20260914-2601"', '"20260831-2587"')
    (tmp_path / "upstream.yml").write_text(text)
    pages = {**DEBIAN_PAGES, **FEDORA_PAGES}
    pages[FEDORA.index + "Fedora-Cloud-44-1.7-x86_64-CHECKSUM"] = (
        "SHA256 (Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2) = " + "b" * 64
    )

    assert upstream.check(tmp_path, ["debian-cloud"], update=True, fetch=fake_fetch(pages)) == 0
    after = (tmp_path / "upstream.yml").read_text()
    assert '"20260914-2601"' in after
    assert after.count("\n") == text.count("\n")

    mtime = (tmp_path / "upstream.yml").stat().st_mtime_ns
    assert upstream.check(tmp_path, ["debian-cloud"], update=True, fetch=fake_fetch(pages)) == 0
    assert (tmp_path / "upstream.yml").stat().st_mtime_ns == mtime


def test_check_without_update_writes_nothing(tmp_path):
    text = UPSTREAM_YML.replace('"20260914-2601"', '"20260831-2587"')
    (tmp_path / "upstream.yml").write_text(text)
    assert (
        upstream.check(tmp_path, ["debian-cloud"], update=False, fetch=fake_fetch(DEBIAN_PAGES))
        == 0
    )
    assert (tmp_path / "upstream.yml").read_text() == text


def test_failed_lookup_leaves_file_untouched(tmp_path):
    text = UPSTREAM_YML.replace('"20260914-2601"', '"20260831-2587"')
    (tmp_path / "upstream.yml").write_text(text)
    pages = {DEBIAN.index: fixture("debian-index.html")}
    assert upstream.check(tmp_path, ["debian-cloud"], update=True, fetch=fake_fetch(pages)) == 1
    assert (tmp_path / "upstream.yml").read_text() == text
