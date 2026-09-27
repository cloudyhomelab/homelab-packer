"""Load images.yml and upstream.yml into a validated image tree."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString

IMAGES_FILE = "images.yml"
UPSTREAM_FILE = "upstream.yml"

SETTINGS = ("disk_size", "memory", "cpus", "max_age_days", "retain_images")
IMAGE_FIELDS = {"from", "children", *SETTINGS}
UPSTREAM_FIELDS = ("os", "index", "image_file", "checksum_file", "version", "checksum")
NAMING_FIELDS = ("image_name", "playbook", "s3_prefix")
S3_FIELDS = ("endpoint", "region", "bucket")

HASH_LENGTHS = {"sha256": 64, "sha384": 96, "sha512": 128}
CHECKSUM_RE = re.compile(r"^(sha256|sha384|sha512):([0-9a-f]+)$")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DISK_SIZE_RE = re.compile(r"^[1-9][0-9]*[KMGT]?$")


class CatalogError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass(frozen=True)
class S3Config:
    endpoint: str
    region: str
    bucket: str


@dataclass(frozen=True)
class Upstream:
    key: str
    os: str
    index: str
    image_file: str
    checksum_file: str
    version: str
    checksum: str

    @property
    def url(self) -> str:
        return self.index + self.image_file.format(version=self.version)


@dataclass(frozen=True)
class Source:
    """The image a build starts from: an upstream pin or a parent's latest build."""

    name: str
    url: str
    checksum: str


@dataclass
class Image:
    key: str
    os: str
    name: str
    playbook: str
    s3_prefix: str
    disk_size: str
    memory: int
    cpus: int
    max_age_days: int
    retain_images: int
    parent: str | None
    upstream: str | None
    depth: int
    children: list[str] = field(default_factory=list)

    def settings(self) -> dict[str, object]:
        """The resolved settings that shape what gets built (part of CHECK_HASH)."""
        return {
            "name": self.name,
            "playbook": self.playbook,
            "disk_size": self.disk_size,
            "memory": self.memory,
            "cpus": self.cpus,
        }


@dataclass
class Catalog:
    root: Path
    s3: S3Config
    naming: dict[str, str]
    upstreams: dict[str, Upstream]
    images: dict[str, Image]

    def ordered(self) -> list[Image]:
        """Images in tree order: every parent comes before its children."""
        return list(self.images.values())

    def get(self, name: str) -> Image:
        try:
            return self.images[name]
        except KeyError:
            raise CatalogError([f"unknown image {name!r}"]) from None

    def ancestors(self, name: str) -> list[Image]:
        out = []
        parent = self.images[name].parent
        while parent is not None:
            out.append(self.images[parent])
            parent = self.images[parent].parent
        return out

    def descendants(self, name: str) -> list[Image]:
        out = []
        for child in self.images[name].children:
            out.append(self.images[child])
            out.extend(self.descendants(child))
        return out

    def upstream_source(self, image: Image) -> Source:
        if image.upstream is None:
            raise ValueError(f"{image.name} is not a top-level image")
        up = self.upstreams[image.upstream]
        return Source(name=up.key, url=up.url, checksum=up.checksum)

    def image_prefix(self, image: Image) -> str:
        return f"{image.s3_prefix}/{image.name}"

    def public_url(self, key: str) -> str:
        return f"{self.s3.endpoint.rstrip('/')}/{self.s3.bucket}/{key}"


def yaml_loader() -> YAML:
    # round-trip mode keeps quoting, so an unquoted version can be told apart
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.allow_duplicate_keys = False
    return yaml


def read_yaml(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as f:
            return yaml_loader().load(f)
    except FileNotFoundError:
        raise CatalogError([f"{path.name}: file not found"]) from None
    except YAMLError as e:
        raise CatalogError([f"{path.name}: {e}"]) from None


def _template_fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name is not None}


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_checksum(value: object) -> str | None:
    """Return an error message if value is not a well-formed `<algo>:<hex>` checksum."""
    if not isinstance(value, str):
        return "must be a string"
    m = CHECKSUM_RE.match(value)
    if not m:
        return f"must look like sha256:<hex> or sha512:<hex>, got {value!r}"
    algo, digest = m.groups()
    if len(digest) != HASH_LENGTHS[algo]:
        return f"{algo} hash must be {HASH_LENGTHS[algo]} hex characters, got {len(digest)}"
    return None


def parse_upstreams(data: object) -> tuple[dict[str, Upstream], list[str]]:
    errors: list[str] = []
    upstreams: dict[str, Upstream] = {}
    if not isinstance(data, dict):
        return upstreams, [f"{UPSTREAM_FILE}: must be a mapping of upstream keys"]

    for key, entry in data.items():
        where = f"{UPSTREAM_FILE}: {key}"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        unknown = set(entry) - set(UPSTREAM_FIELDS)
        if unknown:
            errors.append(f"{where}: unknown fields {sorted(unknown)}")
        missing = [f for f in UPSTREAM_FIELDS if f not in entry]
        if missing:
            errors.append(f"{where}: missing fields {missing}")
            continue

        bad = False
        for f in ("os", "index", "image_file", "checksum_file"):
            if not isinstance(entry[f], str) or not entry[f]:
                errors.append(f"{where}: {f} must be a non-empty string")
                bad = True
        if bad:
            continue

        if not KEY_RE.match(entry["os"]):
            errors.append(f"{where}: os {entry['os']!r} must be lowercase letters, digits and -")
        if not entry["index"].startswith(("https://", "http://")) or not entry["index"].endswith(
            "/"
        ):
            errors.append(f"{where}: index must be an http(s) URL ending in /")
        for f in ("image_file", "checksum_file"):
            fields = _template_fields(entry[f])
            if fields - {"version"}:
                errors.append(f"{where}: {f} may only use {{version}}, got {sorted(fields)}")
        if "version" not in _template_fields(entry["image_file"]):
            errors.append(f"{where}: image_file must contain {{version}}")

        version = entry["version"]
        if not isinstance(version, DoubleQuotedScalarString | SingleQuotedScalarString):
            errors.append(f"{where}: version must be a quoted string, got {version!r}")
        elif not str(version):
            errors.append(f"{where}: version must not be empty")

        checksum_error = check_checksum(entry["checksum"])
        if checksum_error:
            errors.append(f"{where}: checksum {checksum_error}")

        upstreams[str(key)] = Upstream(
            key=str(key),
            os=str(entry["os"]),
            index=str(entry["index"]),
            image_file=str(entry["image_file"]),
            checksum_file=str(entry["checksum_file"]),
            version=str(version),
            checksum=str(entry["checksum"]),
        )
    return upstreams, errors


def _parse_settings(where: str, data: object, required: bool) -> tuple[dict, list[str]]:
    errors: list[str] = []
    out: dict[str, object] = {}
    if not isinstance(data, dict):
        return out, [f"{where}: must be a mapping"]
    for name in SETTINGS:
        if name not in data:
            if required:
                errors.append(f"{where}: missing {name}")
            continue
        value = data[name]
        if name == "disk_size":
            if not isinstance(value, str) or not DISK_SIZE_RE.match(value):
                errors.append(f"{where}: disk_size must be a size like 3G, got {value!r}")
                continue
            value = str(value)
        elif name == "max_age_days":
            if not _is_int(value) or value < 0:
                errors.append(f"{where}: max_age_days must be an integer >= 0, got {value!r}")
                continue
        elif not _is_int(value) or value < 1:
            errors.append(f"{where}: {name} must be an integer >= 1, got {value!r}")
            continue
        out[name] = value
    return out, errors


def _split_item(item: object, where: str) -> tuple[str | None, dict, list[str]]:
    """An item is a bare name or a one-key mapping from the name to its settings."""
    if isinstance(item, str):
        return item, {}, []
    if isinstance(item, dict):
        if len(item) != 1:
            keys = ", ".join(str(k) for k in item)
            return (
                None,
                {},
                [
                    f"{where}: item has {len(item)} keys ({keys}); an image is one key "
                    "with its settings indented below it"
                ],
            )
        ((name, body),) = item.items()
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return None, {}, [f"{where}: settings of {name!r} must be a mapping"]
        return str(name), dict(body), []
    return None, {}, [f"{where}: item {item!r} is neither a name nor a one-key mapping"]


def parse_catalog(root: Path, images_data: object, upstream_data: object) -> Catalog:
    errors: list[str] = []
    upstreams, up_errors = parse_upstreams(upstream_data)
    errors.extend(up_errors)

    if not isinstance(images_data, dict):
        raise CatalogError([*errors, f"{IMAGES_FILE}: must be a mapping"])
    unknown = set(images_data) - {"config", "defaults", "images"}
    if unknown:
        errors.append(f"{IMAGES_FILE}: unknown top-level keys {sorted(unknown)}")

    config = images_data.get("config")
    s3 = None
    naming: dict[str, str] = {}
    if not isinstance(config, dict):
        errors.append(f"{IMAGES_FILE}: config must be a mapping")
    else:
        unknown = set(config) - {"s3", "naming"}
        if unknown:
            errors.append(f"{IMAGES_FILE}: config: unknown fields {sorted(unknown)}")
        s3_data = config.get("s3")
        if not isinstance(s3_data, dict):
            errors.append(f"{IMAGES_FILE}: config.s3 must be a mapping")
        else:
            unknown = set(s3_data) - set(S3_FIELDS)
            if unknown:
                errors.append(f"{IMAGES_FILE}: config.s3: unknown fields {sorted(unknown)}")
            missing = [f for f in S3_FIELDS if not isinstance(s3_data.get(f), str)]
            if missing:
                errors.append(f"{IMAGES_FILE}: config.s3: missing or non-string {missing}")
            else:
                s3 = S3Config(**{f: str(s3_data[f]) for f in S3_FIELDS})
        naming_data = config.get("naming")
        if not isinstance(naming_data, dict):
            errors.append(f"{IMAGES_FILE}: config.naming must be a mapping")
        else:
            unknown = set(naming_data) - set(NAMING_FIELDS)
            if unknown:
                errors.append(f"{IMAGES_FILE}: config.naming: unknown fields {sorted(unknown)}")
            for f in NAMING_FIELDS:
                value = naming_data.get(f)
                if not isinstance(value, str) or not value:
                    errors.append(f"{IMAGES_FILE}: config.naming.{f} must be a non-empty string")
                    continue
                fields = _template_fields(value)
                if fields - {"os", "key"}:
                    errors.append(
                        f"{IMAGES_FILE}: config.naming.{f} may only use {{os}} and {{key}}, "
                        f"got {sorted(fields)}"
                    )
                    continue
                naming[f] = str(value)

    defaults, def_errors = _parse_settings(
        f"{IMAGES_FILE}: defaults", images_data.get("defaults"), required=True
    )
    errors.extend(def_errors)

    tree = images_data.get("images")
    if not isinstance(tree, list) or not tree:
        errors.append(f"{IMAGES_FILE}: images must be a non-empty list")
        tree = []

    if errors:
        # naming and defaults are needed to resolve any image
        raise CatalogError(errors)

    images: dict[str, Image] = {}
    keys_per_os: dict[str, set[str]] = {}

    def fill(template: str, os_name: str, key: str) -> str:
        return template.format(os=os_name, key=key)

    def walk(items: object, parent: Image | None, os_name: str | None, depth: int, where: str):
        if not isinstance(items, list):
            errors.append(f"{where}: children must be a list")
            return
        for index, item in enumerate(items):
            item_where = f"{where}[{index}]"
            key, body, item_errors = _split_item(item, item_where)
            if item_errors:
                errors.extend(item_errors)
                continue
            assert key is not None
            item_where = f"{where}: {key}"
            if not KEY_RE.match(key):
                errors.append(f"{item_where}: key must be lowercase letters, digits and -")
                continue

            unknown_fields = set(body) - IMAGE_FIELDS
            if unknown_fields:
                errors.append(f"{item_where}: unknown fields {sorted(unknown_fields)}")

            upstream_key = None
            image_os = os_name
            if parent is None:
                if "from" not in body:
                    errors.append(f"{item_where}: a top-level image must set from")
                    continue
                upstream_key = body["from"]
                if upstream_key not in upstreams:
                    errors.append(
                        f"{item_where}: from {upstream_key!r} is not a key in {UPSTREAM_FILE}"
                    )
                    continue
                image_os = upstreams[upstream_key].os
            elif "from" in body:
                errors.append(
                    f"{item_where}: only a top-level image sets from; "
                    "a nested image builds on the image it sits under"
                )
                continue
            assert image_os is not None

            seen = keys_per_os.setdefault(image_os, set())
            if key in seen:
                errors.append(f"{item_where}: key {key!r} is repeated within os {image_os!r}")
                continue
            seen.add(key)

            own, setting_errors = _parse_settings(item_where, body, required=False)
            if setting_errors:
                errors.extend(setting_errors)
                continue
            resolved = {**defaults, **own}

            name = fill(naming["image_name"], image_os, key)
            if name in images:
                errors.append(f"{item_where}: image name {name!r} collides with another image")
                continue

            image = Image(
                key=key,
                os=image_os,
                name=name,
                playbook=fill(naming["playbook"], image_os, key),
                s3_prefix=fill(naming["s3_prefix"], image_os, key),
                parent=parent.name if parent else None,
                upstream=str(upstream_key) if upstream_key else None,
                depth=depth,
                **resolved,
            )
            images[name] = image
            if parent is not None:
                parent.children.append(name)
            if "children" in body:
                walk(body["children"], image, image_os, depth + 1, f"{item_where}.children")

    walk(tree, None, None, 0, f"{IMAGES_FILE}: images")

    if errors:
        raise CatalogError(errors)
    assert s3 is not None
    return Catalog(root=root, s3=s3, naming=naming, upstreams=upstreams, images=images)


def load(root: Path) -> Catalog:
    images_data = read_yaml(root / IMAGES_FILE)
    upstream_data = read_yaml(root / UPSTREAM_FILE)
    return parse_catalog(root, images_data, upstream_data)
