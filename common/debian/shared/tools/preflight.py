from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen
from urllib.error import HTTPError
from hcl2 import SerializationOptions

import sys
import hcl2
import json

MAX_AGE_DAYS :int = 7
METADATA_URL :str = "https://s3-api.cloudyhome.net/os-image/debian/metadata_all.json"
SOURCE_PKRVARS_FILE :str = Path(__file__).absolute().parent / "source-image.auto.pkrvars.hcl"
IMAGE_CONFIG_PKRVARS_FILE :str = Path(__file__).absolute().parent / "vars.auto.pkrvars.hcl"

BUILD_REQUIRED_RETURN_VALUE :int = 0
BUILD_NOT_REQUIRED_RETURN_VALUE :int = 10

@dataclass(frozen=True)
class SourceImage:
    url: str
    checksum: str

@dataclass(frozen=True)
class ImageConfig:
    name: str
    disk_size: str
    playbook_name: str

@dataclass(frozen=True)
class ImageMetadata:
    name: str
    sha512: str
    url: str
    build_date: datetime
    base_image_url: str
    base_image_sha512: str | None
    packer_git_remote: str
    packer_git_commit: str

def read_json_from_url(url: str) -> list[dict] | None:
    try:
        with urlopen(url) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP error: {response.status} for {url}")
            return json.load(response)
    except HTTPError as e:
        # at the very beginning it is possible that there is no metadata to read from
        return None

def parse_build_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")

def get_latest_image_metadata(url: str, prefix: str) -> ImageMetadata | None:
    data = read_json_from_url(url)
    if not data:
        return None

    image_prefix = f"{prefix}-"
    candidates = [
        item for item in data
        if isinstance(item, dict) and str(item.get("IMAGE_NAME", "")).startswith(image_prefix)
    ]

    if not candidates:
        return None

    latest_candidate= max(
        candidates,
        key=lambda item: parse_build_date(str(item["BUILD_DATE"]))
    )

    if not latest_candidate:
        return None

    return ImageMetadata(
        name=latest_candidate["IMAGE_NAME"],
        sha512=latest_candidate.get("SHA512_CHECKSUM"),
        url=latest_candidate.get("IMAGE_URL"),
        build_date=parse_build_date(latest_candidate["BUILD_DATE"]),
        base_image_url=latest_candidate.get("BASE_IMAGE"),
        base_image_sha512=latest_candidate.get("BASE_IMAGE_SHA512"),
        packer_git_remote=latest_candidate.get("PACKER_GIT_REMOTE"),
        packer_git_commit=latest_candidate.get("PACKER_GIT_COMMIT"),
    )

def read_source_pkrvars(path: Path) -> SourceImage:
    with path.open("r", encoding="utf-8") as f:
        data = hcl2.load(f, serialization_options=SerializationOptions(strip_string_quotes=True))

    return SourceImage(
        url=data["source_cloud_image_url"],
        checksum=data["source_cloud_image_checksum"],
    )

def read_image_config_pkrvars(path: Path) -> SourceImage:
    with path.open("r", encoding="utf-8") as f:
        data = hcl2.load(f, serialization_options=SerializationOptions(strip_string_quotes=True))

    return ImageConfig(
        name=data["image_name"],
        disk_size=data["disk_size"],
        playbook_name=data["playbook_name"],
    )


def build_required(source: SourceImage, latest: ImageMetadata | None, max_age_days: int) -> bool:
    if latest is None:
        return True

    too_old = latest.build_date < (datetime.now(timezone.utc) - timedelta(days=max_age_days))
    same_source_url = latest.base_image_url == source.url
    same_source_checksum = latest.base_image_sha512 == source.checksum

    return not (same_source_url and same_source_checksum and not too_old)


def main() -> int:
    source = read_source_pkrvars(SOURCE_PKRVARS_FILE)
    config = read_image_config_pkrvars(IMAGE_CONFIG_PKRVARS_FILE)
    latest = get_latest_image_metadata(METADATA_URL, config.name)

    if build_required(source, latest, MAX_AGE_DAYS):
        return BUILD_REQUIRED_RETURN_VALUE

    return BUILD_NOT_REQUIRED_RETURN_VALUE


if __name__ == "__main__":
    raise SystemExit(main())
