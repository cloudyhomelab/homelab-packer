"""Is a build required: compare an image's latest.json with what a build would use now."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .catalog import Catalog, Image, Source

BUILD_DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"

Latest = dict[str, str]
LatestReader = Callable[[Image], "Latest | None"]


class PreflightError(Exception):
    pass


def parse_build_date(value: str) -> datetime:
    return datetime.strptime(value, BUILD_DATE_FORMAT)


def build_required(
    latest: Latest | None,
    source: Source | None,
    check_hash: str | None,
    now: datetime,
    max_age: timedelta,
) -> str | None:
    """Return why a build is required, or None when the published build is current.

    source is None when the parent has never been published; check_hash is None when it could
    not be computed (for example a missing playbook).
    """
    if latest is None:
        return "never built"
    if source is None or latest.get("PARENT_CHECKSUM") != source.checksum:
        return "source changed"
    if latest.get("CHECK_HASH") != check_hash:
        return "check hash changed"
    if now - parse_build_date(latest["BUILD_DATE"]) >= max_age:
        return "aged out"
    return None


def latest_url(catalog: Catalog, image: Image) -> str:
    return catalog.public_url(f"{catalog.image_prefix(image)}/latest.json")


def fetch_latest(catalog: Catalog, image: Image) -> Latest | None:
    """Read an image's latest.json anonymously. 404 means never built; other errors raise."""
    url = latest_url(catalog, image)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        # a missing bucket is also a 404, but it must not read as "never built"
        if e.code == 404 and b"NoSuchBucket" not in e.read():
            return None
        raise PreflightError(f"{url}: HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise PreflightError(f"{url}: {e.reason}") from None


def source_from_latest(latest: Latest) -> Source:
    return Source(name=latest["IMAGE"], url=latest["IMAGE_URL"], checksum=latest["IMAGE_CHECKSUM"])


def current_source(
    catalog: Catalog, image: Image, latest: dict[str, Latest | None]
) -> Source | None:
    """The source a build of image would use now: its upstream pin or its parent's latest."""
    if image.parent is None:
        return catalog.upstream_source(image)
    parent_latest = latest.get(image.parent)
    return source_from_latest(parent_latest) if parent_latest else None


@dataclass(frozen=True)
class Due:
    image: str
    reason: str


def plan(
    catalog: Catalog,
    hashes: dict[str, str | None],
    read_latest: LatestReader,
    now: datetime,
) -> tuple[list[Due], dict[str, Latest | None]]:
    """Images that are due, in tree order, each with its reason.

    An image is due for its own reason, or because an ancestor is due ("parent due").
    """
    latest: dict[str, Latest | None] = {}
    due: dict[str, str] = {}
    for image in catalog.ordered():
        latest[image.name] = read_latest(image)
        source = current_source(catalog, image, latest)
        reason = build_required(
            latest[image.name],
            source,
            hashes.get(image.name),
            now,
            timedelta(days=image.max_age_days),
        )
        if reason is None and image.parent in due:
            reason = f"parent due ({image.parent})"
        if reason is not None:
            due[image.name] = reason
    return [Due(name, reason) for name, reason in due.items()], latest
