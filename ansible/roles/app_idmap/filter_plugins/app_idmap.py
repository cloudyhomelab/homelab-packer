"""Filters of the app_idmap role."""

from __future__ import annotations

from ansible.errors import AnsibleFilterError


def app_id_range(idmap: dict, app: str) -> dict[str, int]:
    """The app's range in an idmap.yml mapping: container ID n is base + n on the VM."""
    slots = idmap.get("slots") or {}
    if app not in slots:
        raise AnsibleFilterError(f"the ID map has no slot for {app}")
    size = idmap["size"]
    return {"base": idmap["start"] + slots[app] * size, "count": size}


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {"app_id_range": app_id_range}
