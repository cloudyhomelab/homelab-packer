"""Is a security update out for a package a published build ships.

Compares the Debian packages in the build's SBOM with the Packages indexes listed under its
upstream's `security`. A build installs every pending update, so a rebuild clears the reason.
"""

from __future__ import annotations

import gzip
import lzma
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from debian.deb822 import Packages
from debian.debian_support import Version

from .catalog import Catalog, Image
from .packer import SBOM_FILE

DEB_PURL_PREFIX = "pkg:deb/"
# only the host's dpkg database counts: a rebuild cannot update packages syft finds elsewhere
HOST_DPKG_STATUS = "var/lib/dpkg/status"
LOCATION_PROPERTY = "syft:location:0:path"
# names shown in a plan reason; the rest are counted
REASON_NAMES = 3

Latest = dict[str, str]
SbomReader = Callable[[Image, Latest], "dict | None"]
Fetch = Callable[[str], bytes]


class SecurityError(Exception):
    pass


@dataclass(frozen=True)
class Update:
    package: str
    installed: str
    available: str


def fetch_bytes(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except urllib.error.URLError as e:
        raise SecurityError(f"{url}: {e}") from None


def decompress(url: str, body: bytes) -> str:
    if url.endswith(".xz"):
        body = lzma.decompress(body)
    elif url.endswith(".gz"):
        body = gzip.decompress(body)
    return body.decode("utf-8", errors="replace")


def parse_packages(text: str) -> dict[str, Version]:
    """The newest version of each binary package in a Packages index."""
    newest: dict[str, Version] = {}
    for stanza in Packages.iter_paragraphs(text.splitlines(), use_apt_pkg=False):
        name = stanza.get("Package")
        if not name or "Version" not in stanza:
            continue
        version = Version(stanza["Version"])
        if name not in newest or version > newest[name]:
            newest[name] = version
    return newest


def _location(component: dict) -> str | None:
    for prop in component.get("properties", []):
        if prop.get("name") == LOCATION_PROPERTY:
            return prop.get("value", "").lstrip("/")
    return None


def installed_debs(sbom: dict) -> dict[str, str]:
    """The host's Debian binary packages in a CycloneDX SBOM, name to version (with epoch)."""
    return {
        c["name"]: c["version"]
        for c in sbom.get("components", [])
        if c.get("purl", "").startswith(DEB_PURL_PREFIX)
        and "version" in c
        and _location(c) == HOST_DPKG_STATUS
    }


def pending(installed: dict[str, str], available: dict[str, Version]) -> list[Update]:
    return [
        Update(name, version, str(available[name]))
        for name, version in sorted(installed.items())
        if name in available and available[name] > Version(version)
    ]


def reason(updates: list[Update]) -> str:
    shown = ", ".join(f"{u.package} {u.installed} -> {u.available}" for u in updates[:REASON_NAMES])
    more = len(updates) - REASON_NAMES
    return f"security update ({shown}{f', +{more} more' if more > 0 else ''})"


def sbom_key(catalog: Catalog, image: Image, latest: Latest) -> str:
    return f"{catalog.image_prefix(image)}/{latest['BUILD_VERSION']}/{SBOM_FILE}"


class Checker:
    """Why a published build is due for a security update, or None.

    Each Packages index is fetched once per Checker, however many images use it.
    """

    def __init__(self, catalog: Catalog, read_sbom: SbomReader, fetch: Fetch = fetch_bytes):
        self.catalog = catalog
        self.read_sbom = read_sbom
        self.fetch = fetch
        self._indexes: dict[str, dict[str, Version]] = {}

    def available(self, urls: tuple[str, ...]) -> dict[str, Version]:
        merged: dict[str, Version] = {}
        for url in urls:
            if url not in self._indexes:
                body = self.fetch(url)
                self._indexes[url] = parse_packages(decompress(url, body))
            for name, version in self._indexes[url].items():
                if name not in merged or version > merged[name]:
                    merged[name] = version
        return merged

    def __call__(self, image: Image, latest: Latest) -> str | None:
        urls = self.catalog.root_upstream(image).security
        if not urls:
            return None
        sbom = self.read_sbom(image, latest)
        if sbom is None:
            # a rebuild publishes one, so this clears itself
            return "no SBOM to check for security updates"
        updates = pending(installed_debs(sbom), self.available(urls))
        return reason(updates) if updates else None
