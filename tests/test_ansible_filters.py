import importlib.util
from pathlib import Path

import pytest
from ansible.errors import AnsibleFilterError

ROLES = Path(__file__).parent.parent / "ansible" / "roles"


def load_filters(role: str, module: str) -> dict:
    path = ROLES / role / "filter_plugins" / f"{module}.py"
    spec = importlib.util.spec_from_file_location(f"{role}_{module}", path)
    assert spec is not None and spec.loader is not None
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    return plugin.FilterModule().filters()


IDMAP = {"start": 2000000, "size": 65536, "slots": {"youtarr": 1, "immich": 7}}


def test_app_id_ranges():
    app_id_ranges = load_filters("app_idmap", "app_idmap")["app_id_ranges"]
    assert app_id_ranges(IDMAP, ["youtarr", "immich"]) == {
        "youtarr": {"base": 2065536, "count": 65536},
        "immich": {"base": 2458752, "count": 65536},
    }


def test_app_id_ranges_need_a_slot_for_every_app():
    app_id_ranges = load_filters("app_idmap", "app_idmap")["app_id_ranges"]
    with pytest.raises(AnsibleFilterError, match="no slot for netbox, jellyfin"):
        app_id_ranges(IDMAP, ["youtarr", "netbox", "jellyfin"])


DATASETS = {
    "db": {"owner": "999:999", "recordsize": "16K"},
    "data": {"owner": "1000:1000", "dirs": ["config", "jobs"]},
    "media": {"owner": "1:1", "mode": "0755"},
}


def test_app_storage_mounts():
    mounts = load_filters("app_storage", "app_storage")["app_storage_mounts"]
    found = mounts(DATASETS, "caddy-lab", 2065536, "nfs.example.net", "/mnt/tank/apps", "/srv")
    assert found == [
        {
            "unit": "srv-caddy\\x2dlab-db.mount",
            "what": "nfs.example.net:/mnt/tank/apps/caddy-lab/db",
            "where": "/srv/caddy-lab/db",
            "owner": "2066535:2066535",
            "dirs": [],
        },
        {
            "unit": "srv-caddy\\x2dlab-data.mount",
            "what": "nfs.example.net:/mnt/tank/apps/caddy-lab/data",
            "where": "/srv/caddy-lab/data",
            "owner": "2066536:2066536",
            "dirs": ["/srv/caddy-lab/data/config", "/srv/caddy-lab/data/jobs"],
        },
        {
            "unit": "srv-caddy\\x2dlab-media.mount",
            "what": "nfs.example.net:/mnt/tank/apps/caddy-lab/media",
            "where": "/srv/caddy-lab/media",
            "owner": "2065537:2065537",
            "dirs": [],
            "mode": "0755",
        },
    ]


def test_app_id_lines_are_sorted_by_app():
    filters = load_filters("app_idmap", "app_idmap")
    ranges = filters["app_id_ranges"](IDMAP, ["youtarr", "immich"])
    assert filters["app_id_lines"](ranges, ["youtarr", "immich"]) == [
        {"app": "immich", "line": "immich:2458752:65536"},
        {"app": "youtarr", "line": "youtarr:2065536:65536"},
    ]
