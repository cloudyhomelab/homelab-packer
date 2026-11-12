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


def test_app_id_range():
    app_id_range = load_filters("app_idmap", "app_idmap")["app_id_range"]
    assert app_id_range(IDMAP, "youtarr") == {"base": 2065536, "count": 65536}
    assert app_id_range(IDMAP, "immich") == {"base": 2458752, "count": 65536}


def test_app_id_range_needs_a_slot():
    app_id_range = load_filters("app_idmap", "app_idmap")["app_id_range"]
    with pytest.raises(AnsibleFilterError, match="no slot for netbox"):
        app_id_range(IDMAP, "netbox")
