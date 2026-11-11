"""Persistent storage the apps declare in ansible/apps/<app>/storage.yml.

Each dataset is one NFS export mounted at /srv/<app>/<dataset>. The image bakes the mount
units; whatever deploys the image creates the datasets and exports from the published list.
An app with storage runs its containers in its own ID range (idmap.py), so its files on the
NFS server are owned by IDs no other app and no NAS account uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .catalog import KEY_RE, Catalog, CatalogError, Image, StorageConfig, read_yaml
from .check_hash import ANSIBLE_DIR, STORAGE_FILE, CheckHashError, resolve_apps, resolve_roles
from .idmap import IDMAP_FILE, IdMap
from .idmap import load as load_idmap

STORAGE_ROLE = "app_storage"
MOUNT_ROOT = "/srv"
DATASET_FIELDS = {"owner", "recordsize", "dirs", "mode"}
OWNER_RE = re.compile(r"^[0-9]+:[0-9]+$")
RECORDSIZE_RE = re.compile(r"^[1-9][0-9]*[KM]$")
MODE_RE = re.compile(r"^0[0-7]{3}$")
# quadlet keys that set a container's user namespace; only the app's named range is allowed
USERNS_KEYS = ("UIDMap", "GIDMap", "UserNS", "SubUIDMap", "SubGIDMap")


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


def export_path(config: StorageConfig, dataset: Dataset) -> str:
    return f"{config.base}/{dataset.app}/{dataset.name}"


def mount_unit(path: str) -> str:
    """systemd's unit name for a mount point; names here are limited to [a-z0-9-]."""
    parts = path.strip("/").split("/")
    return "-".join(part.replace("-", "\\x2d") for part in parts) + ".mount"


def shifted_owner(ranges: IdMap, dataset: Dataset) -> str:
    """The dataset's owner as the VM and the NFS server see it."""
    base = ranges.base(dataset.app)
    uid, gid = (int(part) for part in dataset.owner.split(":"))
    return f"{base + uid}:{base + gid}"


def ansible_vars(
    config: StorageConfig | None, ranges: IdMap | None, datasets: list[Dataset]
) -> dict[str, object]:
    """What the app_storage role renders: one mount per dataset; per app its ID range and a
    unit that prepares its directories."""
    if not datasets:
        return {"app_storage_mounts": [], "app_storage_apps": []}
    if config is None:
        raise CatalogError(["apps declare storage but images.yml has no config.storage"])
    if ranges is None:
        raise CatalogError([f"apps declare storage but {IDMAP_FILE} does not exist"])
    unmapped = sorted({d.app for d in datasets} - set(ranges.slots))
    if unmapped:
        raise CatalogError([f"{IDMAP_FILE}: no slot for {', '.join(unmapped)}"])
    too_big = [
        f"apps/{d.app}/{STORAGE_FILE}: {d.name}: owner {d.owner} is outside the app's "
        f"{ranges.size} IDs"
        for d in datasets
        if any(int(part) >= ranges.size for part in d.owner.split(":"))
    ]
    if too_big:
        raise CatalogError(too_big)
    mounts = [
        {
            "unit": mount_unit(d.path),
            "what": f"{config.server}:{export_path(config, d)}",
            "where": d.path,
        }
        for d in datasets
    ]
    apps: dict[str, list[dict[str, object]]] = {}
    for d in datasets:
        entry: dict[str, object] = {
            "where": d.path,
            "owner": shifted_owner(ranges, d),
            "dirs": [f"{d.path}/{x}" for x in d.dirs],
        }
        if d.mode:
            entry["mode"] = d.mode
        apps.setdefault(d.app, []).append(entry)
    return {
        "app_storage_mounts": mounts,
        "app_storage_apps": [
            {"app": app, "id_base": ranges.base(app), "id_count": ranges.size, "datasets": ds}
            for app, ds in apps.items()
        ],
    }


def quadlet_problems(root: Path, app: str) -> list[str]:
    """An app with storage must run every container in its named ID range, and nothing else."""
    out = []
    quadlets = sorted((root / ANSIBLE_DIR / "apps" / app / "quadlet").glob("*.container"))
    for path in quadlets:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
        found = {line for line in lines if line.split("=", 1)[0] in USERNS_KEYS}
        wanted = {f"SubUIDMap={app}", f"SubGIDMap={app}"}
        where = f"apps/{app}/quadlet/{path.name}"
        missing = sorted(wanted - found)
        if missing:
            out.append(f"{where}: needs {' and '.join(missing)}")
        other = sorted(found - wanted)
        if other:
            out.append(f"{where}: {', '.join(other)} conflicts with the app's ID range")
    return out


def problems(catalog: Catalog) -> dict[str, list[str]]:
    """Per image name, what is wrong with the storage it declares."""
    out: dict[str, list[str]] = {}
    for image in catalog.built():
        try:
            image_datasets(catalog, image)
            own = own_datasets(catalog.root, image)
            ansible_vars(catalog.storage, load_idmap(catalog.root), own)
            roles = resolve_roles(catalog.root, image.playbook) if own else []
        except CatalogError as e:
            out[image.name] = e.errors
            continue
        except CheckHashError:
            # validate already reports it as the image's CHECK_HASH error
            continue
        found = []
        if own and STORAGE_ROLE not in roles:
            found.append(
                f"its apps declare storage but the playbook does not run role {STORAGE_ROLE}"
            )
        for app in sorted({d.app for d in own}):
            found.extend(quadlet_problems(catalog.root, app))
        if found:
            out[image.name] = found
    return out
