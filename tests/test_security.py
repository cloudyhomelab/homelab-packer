import lzma

import pytest

from imagectl.security import (
    Checker,
    Update,
    installed_debs,
    parse_packages,
    pending,
    reason,
    sbom_key,
)

INDEX_URL = (
    "https://deb.debian.org/debian-security/dists/trixie-security/main/binary-amd64/Packages.xz"
)

PACKAGES = """\
Package: openssl
Version: 3.5.1-1+deb13u1
Architecture: amd64

Package: libssl3t64
Source: openssl
Version: 3.5.1-1+deb13u1
Architecture: amd64

Package: auditd
Source: audit
Version: 1:4.0.2-2+deb13u2
Architecture: amd64

Package: tzdata
Version: 2025b-4+deb13u1
Architecture: all

Package: tzdata
Version: 2025b-4+deb13u2
Architecture: all
"""


def component(name, version, purl_type="deb", location="var/lib/dpkg/status"):
    return {
        "name": name,
        "version": version,
        "purl": f"pkg:{purl_type}/debian/{name}@x",
        "properties": [{"name": "syft:location:0:path", "value": location}],
    }


def sbom(*components):
    return {"components": list(components)}


CURRENT_SBOM = sbom(
    component("openssl", "3.5.1-1+deb13u1"),
    component("auditd", "1:4.0.2-2+deb13u2"),
)


def test_parse_packages_keeps_the_newest_version():
    available = parse_packages(PACKAGES)
    assert str(available["tzdata"]) == "2025b-4+deb13u2"
    assert str(available["auditd"]) == "1:4.0.2-2+deb13u2"


def test_installed_debs_counts_only_the_dpkg_database():
    found = installed_debs(
        sbom(
            component("age", "1.2.1-1+b5"),
            component("alloy", "1.21.3-1", location="var/cache/apt/archives/alloy_1.21.3-1.deb"),
        )
    )
    assert found == {"age": "1.2.1-1+b5"}


def test_installed_debs_ignores_other_ecosystems():
    found = installed_debs(
        sbom(component("openssl", "3.5.1-1"), component("requests", "2.32.3", "pypi"))
    )
    assert found == {"openssl": "3.5.1-1"}


def test_pending_compares_debian_versions():
    available = parse_packages(PACKAGES)
    installed = {
        "openssl": "3.5.1-1",
        # newer than security: from a point release
        "libssl3t64": "3.5.1-1+deb13u2",
        # the epoch decides, not the string
        "auditd": "1:4.0.2-2+deb13u1",
        "curl": "8.14.1-2",
    }
    assert pending(installed, available) == [
        Update("auditd", "1:4.0.2-2+deb13u1", "1:4.0.2-2+deb13u2"),
        Update("openssl", "3.5.1-1", "3.5.1-1+deb13u1"),
    ]


def test_reason_counts_what_it_does_not_name():
    updates = [Update(f"p{i}", "1", "2") for i in range(5)]
    assert reason(updates[:1]) == "security update (p0 1 -> 2)"
    assert reason(updates) == "security update (p0 1 -> 2, p1 1 -> 2, p2 1 -> 2, +2 more)"


def test_sbom_key(catalog):
    image = catalog.get("debian-container")
    assert sbom_key(catalog, image, {"BUILD_VERSION": "20261106-0726"}) == (
        "debian/debian-container/20261106-0726/sbom.cdx.json"
    )


@pytest.fixture
def fetches():
    return []


@pytest.fixture
def checker(catalog, fetches):
    def fetch(url):
        fetches.append(url)
        return lzma.compress(PACKAGES.encode())

    sboms = {"debian-base": sbom(component("openssl", "3.5.1-1")), "debian-edge": None}
    return Checker(catalog, lambda image, latest: sboms.get(image.name, CURRENT_SBOM), fetch)


def test_checker_reports_a_pending_update(catalog, checker):
    assert checker(catalog.get("debian-base"), {}) == (
        "security update (openssl 3.5.1-1 -> 3.5.1-1+deb13u1)"
    )


def test_checker_passes_a_current_build(catalog, checker):
    assert checker(catalog.get("debian-container"), {}) is None


def test_checker_makes_a_build_without_sbom_due(catalog, checker):
    assert checker(catalog.get("debian-edge"), {}) == "no SBOM to check for security updates"


def test_checker_fetches_each_index_once(catalog, checker, fetches):
    for name in ("debian-base", "debian-container", "debian-media"):
        checker(catalog.get(name), {})
    assert fetches == [INDEX_URL]


def test_checker_skips_an_upstream_without_security(catalog, checker, fetches):
    # fedora-cloud lists no security index
    fedora = next(i for i in catalog.ordered() if i.os == "fedora" and i.parent)
    assert checker(fedora, {}) is None
    assert fetches == []
