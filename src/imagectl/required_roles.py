"""Roles a playbook must run because a folder for it exists that only that role installs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .catalog import Catalog, CatalogError, read_yaml
from .check_hash import CheckHashError, resolve_roles

REQUIRED_ROLES_FILE = "required_roles.yml"
ENTRY_FIELDS = {"folder", "role"}


@dataclass(frozen=True)
class Requirement:
    folder: str
    role: str


def read_requirements(root: Path) -> list[Requirement]:
    path = root / REQUIRED_ROLES_FILE
    if not path.is_file():
        return []
    data = read_yaml(path)
    if not isinstance(data, list):
        raise CatalogError([f"{REQUIRED_ROLES_FILE}: must be a list of folder/role entries"])
    errors = []
    requirements = []
    for number, entry in enumerate(data, start=1):
        where = f"{REQUIRED_ROLES_FILE}: entry {number}"
        if (
            not isinstance(entry, dict)
            or set(entry) != ENTRY_FIELDS
            or not all(isinstance(value, str) and value for value in entry.values())
        ):
            errors.append(f"{where}: needs exactly a non-empty folder and role")
            continue
        if "{playbook}" not in entry["folder"]:
            errors.append(f"{where}: folder {entry['folder']!r} has no {{playbook}}")
            continue
        requirements.append(Requirement(folder=str(entry["folder"]), role=str(entry["role"])))
    if errors:
        raise CatalogError(errors)
    return requirements


def missing_roles(catalog: Catalog) -> dict[str, list[str]]:
    """Per image name, a message for each required role its playbook does not run."""
    root = catalog.root
    requirements = read_requirements(root)
    problems: dict[str, list[str]] = {}
    for image in catalog.ordered():
        present = []
        for req in requirements:
            folder = req.folder.replace("{playbook}", image.playbook)
            if (root / folder).is_dir():
                present.append((folder, req.role))
        if not present:
            continue
        try:
            roles = resolve_roles(root, image.playbook)
        except CheckHashError:
            # validate already reports it as the image's CHECK_HASH error
            continue
        for folder, role in present:
            if role not in roles:
                problems.setdefault(image.name, []).append(
                    f"{folder} exists but the playbook does not run role {role}"
                )
    return problems
