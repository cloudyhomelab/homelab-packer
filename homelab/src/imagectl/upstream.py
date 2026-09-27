"""Find the newest release of each upstream and move its pin in upstream.yml."""

from __future__ import annotations

import os
import re
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

from .catalog import (
    HASH_LENGTHS,
    UPSTREAM_FILE,
    CatalogError,
    Upstream,
    check_checksum,
    parse_upstreams,
    yaml_loader,
)

Fetch = Callable[[str], str]

VERSION_PATTERN = r"(?P<version>[0-9][0-9A-Za-z._-]*)"
HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
GNU_RE = re.compile(r"^(?P<hash>[0-9a-fA-F]+) [ *](?P<file>.+)$")
BSD_RE = re.compile(r"^(?P<algo>[A-Za-z0-9]+) \((?P<file>.+)\) = (?P<hash>[0-9a-fA-F]+)$")
ALGO_BY_LENGTH = {length: algo for algo, length in HASH_LENGTHS.items()}


class UpstreamError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    checksum: str


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def natural_key(value: str) -> list[tuple[int, int | str]]:
    """Sort key where digit runs compare as numbers, so 1.10 sorts after 1.9."""
    return [(0, int(part)) if part.isdigit() else (1, part) for part in re.split(r"(\d+)", value)]


def _split_template(image_file: str) -> tuple[str, re.Pattern[str]]:
    """Split image_file at the first path segment holding {version}.

    Returns the directory to list (relative to index) and a regex for that segment.
    """
    segments = image_file.split("/")
    for i, segment in enumerate(segments):
        if "{version}" in segment:
            directory = "".join(s + "/" for s in segments[:i])
            parts = [re.escape(p) for p in segment.split("{version}")]
            # the first {version} captures, any later one must repeat it
            pattern = parts[0] + VERSION_PATTERN + parts[1]
            pattern += "".join("(?P=version)" + p for p in parts[2:])
            return directory, re.compile(pattern)
    raise UpstreamError(f"image_file {image_file!r} has no {{version}}")


def list_versions(listing_html: str, segment: re.Pattern[str]) -> list[str]:
    versions = set()
    for href in HREF_RE.findall(listing_html):
        path = urllib.parse.urlsplit(href).path
        name = urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1])
        m = segment.fullmatch(name)
        if m:
            versions.add(m.group("version"))
    return sorted(versions, key=natural_key)


def parse_checksums(text: str) -> dict[str, str]:
    """Parse GNU (`<hash>  <file>`) or BSD (`ALGO (<file>) = <hash>`) checksum lines.

    Returns file name -> `<algo>:<hex>`. Lines in neither format (comments, PGP armour) are
    skipped.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if m := BSD_RE.match(line):
            algo = m.group("algo").lower()
        elif m := GNU_RE.match(line):
            algo = ALGO_BY_LENGTH.get(len(m.group("hash")), "unknown")
        else:
            continue
        name = m.group("file").strip().lstrip("*").rsplit("/", 1)[-1]
        out[name] = f"{algo}:{m.group('hash').lower()}"
    return out


def find_newest(upstream: Upstream, fetch: Fetch = fetch_text) -> Release:
    directory, segment = _split_template(upstream.image_file)
    listing_url = upstream.index + directory
    versions = list_versions(fetch(listing_url), segment)
    if not versions:
        raise UpstreamError(
            f"{upstream.key}: no version matching {segment.pattern} at {listing_url}"
        )
    version = versions[-1]

    image_path = upstream.image_file.format(version=version)
    image_name = image_path.rsplit("/", 1)[-1]
    checksum_url = upstream.index + upstream.checksum_file.format(version=version)
    checksums = parse_checksums(fetch(checksum_url))
    if image_name not in checksums:
        raise UpstreamError(f"{upstream.key}: no checksum for {image_name} in {checksum_url}")
    checksum = checksums[image_name]
    error = check_checksum(checksum)
    if error:
        raise UpstreamError(f"{upstream.key}: checksum for {image_name} {error}")
    return Release(version=version, url=upstream.index + image_path, checksum=checksum)


def _value_span(line: str, col: int) -> tuple[int, int]:
    quote = line[col] if col < len(line) else ""
    if quote not in ("'", '"'):
        raise UpstreamError(f"expected a quoted value at column {col + 1}: {line!r}")
    end = line.index(quote, col + 1)
    return col, end + 1


def rewrite_pins(text: str, updates: dict[str, Release]) -> str:
    """Replace only the version and checksum values of the given upstreams in text.

    Works on the original text using ruamel's positions, so every other byte stays as it was.
    """
    data = YAML(typ="rt").load(text)
    lines = text.splitlines(keepends=True)
    for key, release in updates.items():
        entry = data[key]
        for field, value in (("version", release.version), ("checksum", release.checksum)):
            line_no, col = entry.lc.value(field)
            line = lines[line_no]
            start, end = _value_span(line, col)
            quote = line[start]
            lines[line_no] = line[:start] + quote + value + quote + line[end:]
    return "".join(lines)


def load_upstreams(text: str) -> dict[str, Upstream]:
    upstreams, errors = parse_upstreams(yaml_loader().load(text))
    if errors:
        raise CatalogError(errors)
    return upstreams


def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def select(upstreams: dict[str, Upstream], keys: list[str]) -> list[Upstream]:
    unknown = [k for k in keys if k not in upstreams]
    if unknown:
        raise CatalogError(
            [f"unknown upstream {k!r} (not a key in {UPSTREAM_FILE})" for k in unknown]
        )
    return [upstreams[k] for k in keys] if keys else list(upstreams.values())


def check(root: Path, keys: list[str], update: bool, fetch: Fetch = fetch_text) -> int:
    path = root / UPSTREAM_FILE
    text = path.read_text(encoding="utf-8")
    upstreams = load_upstreams(text)
    failed = False
    updates: dict[str, Release] = {}
    for upstream in select(upstreams, keys):
        try:
            newest = find_newest(upstream, fetch)
        except (UpstreamError, OSError) as e:
            print(f"{upstream.key}: error: {e}")
            failed = True
            continue
        current = newest.version == upstream.version and newest.checksum == upstream.checksum
        state = "current" if current else "newer release available"
        print(f"{upstream.key}: pinned {upstream.version}, newest {newest.version} ({state})")
        if not current:
            updates[upstream.key] = newest

    if update and updates:
        new_text = rewrite_pins(text, updates)
        # never write a file the loader would reject, or one that lost a value
        reloaded = load_upstreams(new_text)
        for key, release in updates.items():
            if (reloaded[key].version, reloaded[key].checksum) != (
                release.version,
                release.checksum,
            ):
                raise UpstreamError(f"{key}: rewritten pin does not read back as written")
        write_atomic(path, new_text)
        for key, release in updates.items():
            print(f"{key}: pin moved to {release.version}")
    return 1 if failed else 0
