"""The containers' user namespaces.

An app with a slot in idmap.yml runs every container in its named range, and the image's
playbook writes that range with the app_idmap role. Storage relies on the range, so app_storage
runs app_idmap for its app; the range does not need storage.
"""

from __future__ import annotations

from pathlib import Path

from .catalog import Catalog, CatalogError
from .check_hash import (
    ANSIBLE_DIR,
    CheckHashError,
    resolve_apps,
    resolve_role_params,
    resolve_roles,
)
from .idmap import IDMAP_FILE
from .idmap import load as load_idmap

IDMAP_ROLE = "app_idmap"
IDMAP_APP_KEY = "app_idmap_app"
# app_storage's meta dependency runs app_idmap for the same app
STORAGE_ROLE = "app_storage"
STORAGE_APP_KEY = "app_storage_app"
# quadlet keys that set a container's user namespace; an app with a slot allows only its range
USERNS_KEYS = ("UIDMap", "GIDMap", "UserNS", "SubUIDMap", "SubGIDMap")
NAMED_KEYS = ("SubUIDMap", "SubGIDMap")


def quadlet_problems(root: Path, app: str, has_slot: bool) -> list[str]:
    """An app with a slot runs every container in its range and nothing else; an app without
    one names no range."""
    out = []
    quadlets = sorted((root / ANSIBLE_DIR / "apps" / app / "quadlet").glob("*.container"))
    for path in quadlets:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
        where = f"apps/{app}/quadlet/{path.name}"
        if not has_slot:
            named = sorted(line for line in lines if line.split("=", 1)[0] in NAMED_KEYS)
            if named:
                out.append(f"{where}: {', '.join(named)} needs a slot for {app} in {IDMAP_FILE}")
            continue
        found = {line for line in lines if line.split("=", 1)[0] in USERNS_KEYS}
        wanted = {f"{key}={app}" for key in NAMED_KEYS}
        missing = sorted(wanted - found)
        if missing:
            out.append(f"{where}: needs {' and '.join(missing)}")
        other = sorted(found - wanted)
        if other:
            out.append(f"{where}: {', '.join(other)} conflicts with the app's ID range")
    return out


def problems(catalog: Catalog) -> dict[str, list[str]]:
    """Per image name, what is wrong with its apps' ID ranges."""
    root = catalog.root
    try:
        ranges = load_idmap(root)
    except CatalogError:
        # validate already reports it as each image's CHECK_HASH error
        return {}
    slots = ranges.slots if ranges is not None else {}
    out: dict[str, list[str]] = {}
    for image in catalog.built():
        try:
            roles = resolve_roles(root, image.playbook)
            apps = resolve_apps(root, image.playbook, roles)
            given = {
                *resolve_role_params(root, image.playbook, roles, IDMAP_ROLE, IDMAP_APP_KEY),
                *resolve_role_params(root, image.playbook, roles, STORAGE_ROLE, STORAGE_APP_KEY),
            }
        except CheckHashError:
            # validate already reports it as the image's CHECK_HASH error
            continue
        found = [
            f"the playbook runs {IDMAP_ROLE} for {app}, but {IDMAP_FILE} has no slot for it"
            for app in sorted(given)
            if app not in slots
        ]
        for app in apps:
            if app in slots and app not in given:
                found.append(f"{app} has a slot, but the playbook does not run {IDMAP_ROLE} for it")
            found.extend(quadlet_problems(root, app, app in slots))
        if found:
            out[image.name] = found
    return out
