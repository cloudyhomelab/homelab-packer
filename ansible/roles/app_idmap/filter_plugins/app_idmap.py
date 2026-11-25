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


def app_id_lines(
    ranges: dict[str, dict[str, int]], apps: list[str], rootless: list[str] | None = None
) -> list[dict[str, str]]:
    """The apps' /etc/subuid and /etc/subgid lines, sorted by app so the files do not depend on
    the order a playbook lists the apps in. A rootless app's user is the base itself, and Podman
    maps container ID 0 to it, so its line starts one ID higher to keep container ID n at
    base + n."""
    rootless = rootless or []
    out = []
    for app in sorted(apps):
        skip = 1 if app in rootless else 0
        first, count = ranges[app]["base"] + skip, ranges[app]["count"] - skip
        out.append({"app": app, "line": f"{app}:{first}:{count}"})
    return out


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {"app_id_ranges": app_id_ranges, "app_id_lines": app_id_lines}
