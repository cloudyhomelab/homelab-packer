"""Filters of the app_idmap role."""

from __future__ import annotations

from ansible.errors import AnsibleFilterError


def app_id_ranges(idmap: dict, apps: list[str]) -> dict[str, dict[str, int]]:
    """Per app, its range in an idmap.yml mapping: container ID n is base + n on the VM."""
    slots = idmap.get("slots") or {}
    unmapped = [app for app in apps if app not in slots]
    if unmapped:
        raise AnsibleFilterError(f"the ID map has no slot for {', '.join(unmapped)}")
    size = idmap["size"]
    return {app: {"base": idmap["start"] + slots[app] * size, "count": size} for app in apps}


def app_id_lines(ranges: dict[str, dict[str, int]], apps: list[str]) -> list[dict[str, str]]:
    """The apps' /etc/subuid and /etc/subgid lines, sorted by app so the files do not depend on
    the order a playbook lists the apps in."""
    return [
        {"app": app, "line": f"{app}:{ranges[app]['base']}:{ranges[app]['count']}"}
        for app in sorted(apps)
    ]


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {"app_id_ranges": app_id_ranges, "app_id_lines": app_id_lines}
