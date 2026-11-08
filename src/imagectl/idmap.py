"""The apps' ID ranges, from ansible/apps/idmap.yml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .catalog import KEY_RE, CatalogError, _is_int, read_yaml

IDMAP_FILE = "ansible/apps/idmap.yml"
FIELDS = {"start", "size", "slots"}
# below this the range would overlap the VM's own users
MIN_START = 65536


@dataclass(frozen=True)
class IdMap:
    start: int
    size: int
    slots: dict[str, int]

    def base(self, app: str) -> int:
        """The VM's ID for the app's container ID 0."""
        return self.start + self.slots[app] * self.size


def load(root: Path) -> IdMap | None:
    path = root / IDMAP_FILE
    if not path.is_file():
        return None
    data = read_yaml(path)
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise CatalogError([f"{IDMAP_FILE}: needs exactly {sorted(FIELDS)}"])
    errors = []
    start, size, slots = data["start"], data["size"], data["slots"]
    if not _is_int(start) or start < MIN_START:
        errors.append(f"{IDMAP_FILE}: start must be an integer >= {MIN_START}, got {start!r}")
    if not _is_int(size) or size < 1:
        errors.append(f"{IDMAP_FILE}: size must be an integer >= 1, got {size!r}")
    if not isinstance(slots, dict):
        errors.append(f"{IDMAP_FILE}: slots must be a mapping of app to slot")
        slots = {}
    seen: dict[int, str] = {}
    for app, slot in slots.items():
        if not isinstance(app, str) or not KEY_RE.match(app):
            errors.append(f"{IDMAP_FILE}: app {app!r} must be lowercase letters, digits and -")
        elif not _is_int(slot) or slot < 0:
            errors.append(f"{IDMAP_FILE}: slot of {app} must be an integer >= 0, got {slot!r}")
        elif slot in seen:
            errors.append(f"{IDMAP_FILE}: slot {slot} is given to both {seen[slot]} and {app}")
        else:
            seen[slot] = app
    if errors:
        raise CatalogError(errors)
    return IdMap(start=int(start), size=int(size), slots={str(a): int(s) for a, s in slots.items()})
