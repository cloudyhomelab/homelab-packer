"""Filters of the app_storage role."""

from __future__ import annotations


def mount_unit(path: str) -> str:
    """systemd's unit name for a mount point; names here are limited to [a-z0-9-]."""
    parts = path.strip("/").split("/")
    return "-".join(part.replace("-", "\\x2d") for part in parts) + ".mount"


def app_storage_mounts(
    datasets: dict, app: str, id_base: int, server: str, base: str, mount_root: str
) -> list[dict[str, object]]:
    """One mount per dataset of a storage.yml, its owner shifted into the app's ID range."""
    out = []
    for name, body in datasets.items():
        where = f"{mount_root}/{app}/{name}"
        uid, gid = (int(part) for part in body["owner"].split(":"))
        mount: dict[str, object] = {
            "unit": mount_unit(where),
            "what": f"{server}:{base}/{app}/{name}",
            "where": where,
            "owner": f"{id_base + uid}:{id_base + gid}",
            "dirs": [f"{where}/{d}" for d in body.get("dirs", [])],
        }
        if body.get("mode"):
            mount["mode"] = body["mode"]
        out.append(mount)
    return out


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {"app_storage_mounts": app_storage_mounts}
