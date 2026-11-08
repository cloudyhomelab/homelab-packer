from pathlib import Path

import pytest

from imagectl import idmap
from imagectl.catalog import CatalogError


def write_idmap(root: Path, text: str) -> None:
    path = root / idmap.IDMAP_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_base_is_start_plus_slot_ranges(tmp_path):
    write_idmap(tmp_path, "start: 2000000\nsize: 65536\nslots:\n  youtarr: 1\n  immich: 2\n")
    ranges = idmap.load(tmp_path)
    assert ranges is not None
    assert ranges.base("youtarr") == 2065536
    assert ranges.base("immich") == 2131072


def test_missing_file_is_none(tmp_path):
    assert idmap.load(tmp_path) is None


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("start: 2000000\nsize: 65536\n", "needs exactly"),
        ("start: 1000\nsize: 65536\nslots: {}\n", "start must be an integer >= 65536"),
        ("start: 2000000\nsize: 0\nslots: {}\n", "size must be an integer >= 1"),
        ("start: 2000000\nsize: 65536\nslots: {a: 1, b: 1}\n", "slot 1 is given to both a and b"),
        ("start: 2000000\nsize: 65536\nslots: {a: -1}\n", "slot of a must be an integer >= 0"),
        ("start: 2000000\nsize: 65536\nslots: {A: 1}\n", "app 'A' must be lowercase"),
    ],
)
def test_invalid_idmap(tmp_path, text, error):
    write_idmap(tmp_path, text)
    with pytest.raises(CatalogError) as e:
        idmap.load(tmp_path)
    assert error in "\n".join(e.value.errors)
