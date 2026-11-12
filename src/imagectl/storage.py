"""Persistent storage the apps declare in ansible/apps/<app>/storage.yml.

Each dataset is one NFS export mounted at /srv/<app>/<dataset>. The app_storage role bakes the
mount units from the file; whatever deploys the image creates the datasets and exports from the
published list. An app with storage needs a slot in idmap.py, so its files on the NFS server are
owned by IDs no other app and no NAS account uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .catalog import KEY_RE, Catalog, CatalogError, Image, read_yaml
from .check_hash import (
    ANSIBLE_DIR,
    STORAGE_FILE,
    CheckHashError,
    resolve_apps,
    resolve_role_params,
    resolve_roles,
)
from .idmap import IDMAP_FILE, IdMap
from .idmap import load as load_idmap

STORAGE_ROLE = "app_storage"
STORAGE_APP_KEY = "app_storage_app"
MOUNT_ROOT = "/srv"
DATASET_FIELDS = {"owner", "recordsize", "dirs", "mode"}
OWNER_RE = re.compile(r"^[0-9]+:[0-9]+$")
RECORDSIZE_RE = re.compile(r"^[1-9][0-9]*[KM]$")
MODE_RE = re.compile(r"^0[0-7]{3}$")


@dataclass(frozen=True)
class Dataset:
    app: str
    name: str
    owner: str
    recordsize: str | None
    dirs: tuple[str, ...]
    mode: str | None = None

    @property
    def path(self) -> str:
        return f"{MOUNT_ROOT}/{self.app}/{self.name}"

    def published(self) -> dict[str, str]:
        out = {"app": self.app, "dataset": self.name}
        if self.recordsize:
            out["recordsize"] = self.recordsize
        return out


def storage_file(root: Path, app: str) -> Path:
    return root / ANSIBLE_DIR / "apps" / app / STORAGE_FILE


def read_app(root: Path, app: str) -> list[Dataset]:
    """The app's datasets, or none when it ships no storage.yml."""
    path = storage_file(root, app)
    if not path.is_file():
        return []
    where = f"apps/{app}/{STORAGE_FILE}"
    data = read_yaml(path)
    if not isinstance(data, dict) or set(data) != {"datasets"}:
        raise CatalogError([f"{where}: must be a mapping with only datasets"])
    entries = data["datasets"]
    if not isinstance(entries, dict) or not entries:
        raise CatalogError([f"{where}: datasets must be a non-empty mapping"])

    errors = []
    datasets = []
    for name, body in entries.items():
        at = f"{where}: {name}"
        if not isinstance(name, str) or not KEY_RE.match(name):
            errors.append(f"{at}: name must be lowercase letters, digits and -")
            continue
        if not isinstance(body, dict):
            errors.append(f"{at}: must be a mapping")
            continue
        unknown = set(body) - DATASET_FIELDS
        if unknown:
            errors.append(f"{at}: unknown fields {sorted(unknown)}")
        owner = body.get("owner")
        if not isinstance(owner, str) or not OWNER_RE.match(owner):
            errors.append(f"{at}: owner must be a quoted uid:gid, got {owner!r}")
        recordsize = body.get("recordsize")
        if recordsize is not None and (
            not isinstance(recordsize, str) or not RECORDSIZE_RE.match(recordsize)
        ):
            errors.append(f"{at}: recordsize must be a size like 16K or 1M, got {recordsize!r}")
        mode = body.get("mode")
        if mode is not None and (not isinstance(mode, str) or not MODE_RE.match(mode)):
            errors.append(f"{at}: mode must be a quoted octal mode like '0755', got {mode!r}")
        dirs = body.get("dirs", [])
        if not isinstance(dirs, list) or not all(
            isinstance(d, str) and KEY_RE.match(d) for d in dirs
        ):
            errors.append(f"{at}: dirs must be a list of lowercase names")
            dirs = []
        elif len(set(dirs)) != len(dirs):
            errors.append(f"{at}: dirs has duplicates")
        datasets.append(
            Dataset(
                app=app,
                name=name,
                owner=str(owner),
                recordsize=str(recordsize) if recordsize is not None else None,
                dirs=tuple(str(d) for d in dirs),
                mode=str(mode) if mode is not None else None,
            )
        )
    if errors:
        raise CatalogError(errors)
    return datasets


def own_datasets(root: Path, image: Image) -> list[Dataset]:
    """Datasets of the apps this image's own playbook deploys; mounts go in this layer."""
    roles = resolve_roles(root, image.playbook)
    apps = resolve_apps(root, image.playbook, roles)
    return [dataset for app in apps for dataset in read_app(root, app)]


def image_datasets(catalog: Catalog, image: Image) -> list[Dataset]:
    """Every dataset a VM of this image mounts: its ancestors' layers and its own."""
    layers = [*reversed(catalog.ancestors(image.name)), image]
    built = [layer for layer in layers if layer.upstream is None]
    datasets = [d for layer in built for d in own_datasets(catalog.root, layer)]
    seen: set[str] = set()
    for dataset in datasets:
        if dataset.path in seen:
            raise CatalogError([f"{image.name}: {dataset.app}/{dataset.name} declared twice"])
        seen.add(dataset.path)
    return datasets


def range_problems(ranges: IdMap | None, datasets: list[Dataset]) -> list[str]:
    """Every app with storage has a slot, and every dataset owner fits in the app's range."""
    if not datasets:
        return []
    if ranges is None:
        return [f"apps declare storage but {IDMAP_FILE} does not exist"]
    unmapped = sorted({d.app for d in datasets} - set(ranges.slots))
    if unmapped:
        return [f"{IDMAP_FILE}: no slot for {', '.join(unmapped)}"]
    return [
        f"apps/{d.app}/{STORAGE_FILE}: {d.name}: owner {d.owner} is outside the app's "
        f"{ranges.size} IDs"
        for d in datasets
        if any(int(part) >= ranges.size for part in d.owner.split(":"))
    ]


def problems(catalog: Catalog) -> dict[str, list[str]]:
    """Per image name, what is wrong with the storage it declares."""
    root = catalog.root
    out: dict[str, list[str]] = {}
    for image in catalog.built():
        try:
            image_datasets(catalog, image)
            own = own_datasets(root, image)
            ranges = load_idmap(root) if own else None
            roles = resolve_roles(root, image.playbook)
            apps = resolve_apps(root, image.playbook, roles)
            given = resolve_role_params(root, image.playbook, roles, STORAGE_ROLE, STORAGE_APP_KEY)
        except CatalogError as e:
            out[image.name] = e.errors
            continue
        except CheckHashError:
            # validate already reports it as the image's CHECK_HASH error
            continue
        found = range_problems(ranges, own)
        with_storage = {d.app for d in own}
        found.extend(
            f"{app} declares storage, but the playbook does not run {STORAGE_ROLE} for it"
            for app in sorted(with_storage - set(given))
        )
        found.extend(
            f"the playbook runs {STORAGE_ROLE} for {app}, which has no {STORAGE_FILE}"
            for app in given
            if not storage_file(root, app).is_file()
        )
        found.extend(
            f"the playbook runs {STORAGE_ROLE} for {app}, but does not deploy it"
            for app in given
            if app not in apps
        )
        if found:
            out[image.name] = found
    return out
