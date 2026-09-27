import shutil
from pathlib import Path

import pytest

from imagectl.catalog import load

# the test catalog: every shape images.yml and upstream.yml accept, see its comments
CATALOG = Path(__file__).parent / "fixtures" / "catalog"
INVALID = CATALOG / "invalid"


def copy_catalog(root: Path, images: Path | None = None, upstream: Path | None = None) -> None:
    shutil.copyfile(images or CATALOG / "images.yml", root / "images.yml")
    shutil.copyfile(upstream or CATALOG / "upstream.yml", root / "upstream.yml")


@pytest.fixture
def catalog_root(tmp_path: Path) -> Path:
    copy_catalog(tmp_path)
    return tmp_path


@pytest.fixture
def catalog(catalog_root: Path):
    return load(catalog_root)
