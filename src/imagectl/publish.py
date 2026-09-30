"""Publish a finished build to S3: checksum, metadata, upload, latest.json, pruning."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

from .catalog import Catalog, Image, Source
from .packer import Clock, GitInfo, image_file

CREDENTIAL_VARS = ("S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
CLIENT_CONFIG = Config(
    s3={"addressing_style": "path"},
    retries={"mode": "standard"},
    # S3-compatible stores may not support boto3's default flexible checksums
    request_checksum_calculation="when_required",
    response_checksum_validation="when_required",
)


class PublishError(Exception):
    pass


def s3_client(catalog: Catalog):
    """boto3 client with credentials from S3_* only, so boto3 never looks anywhere else."""
    missing = [name for name in CREDENTIAL_VARS if not os.environ.get(name)]
    if missing:
        raise PublishError(f"missing credentials: {', '.join(missing)}")
    return boto3.session.Session().client(
        "s3",
        endpoint_url=catalog.s3.endpoint,
        region_name=catalog.s3.region,
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        config=CLIENT_CONFIG,
    )


class Store:
    def __init__(self, catalog: Catalog, client):
        self.catalog = catalog
        self.client = client
        self.bucket = catalog.s3.bucket

    def latest(self, image: Image) -> dict | None:
        key = f"{self.catalog.image_prefix(image)}/latest.json"
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise
        return json.loads(body)

    def put_file(self, key: str, path: Path, content_type: str) -> None:
        self.client.upload_file(
            str(path),
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
            Config=TransferConfig(use_threads=False),
        )

    def put_bytes(self, key: str, body: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)

    def head(self, key: str) -> None:
        self.client.head_object(Bucket=self.bucket, Key=key)

    def list_keys(self, prefix: str) -> list[str]:
        keys = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys

    def delete(self, keys: list[str]) -> None:
        for start in range(0, len(keys), 1000):
            batch = keys[start : start + 1000]
            response = self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
            )
            if response.get("Errors"):
                raise PublishError(f"delete failed: {response['Errors']}")


def sha512_file(path: Path) -> str:
    h = hashlib.sha512()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def qemu_img_check(path: Path) -> None:
    subprocess.run(["qemu-img", "check", str(path)], check=True, capture_output=True)


@dataclass(frozen=True)
class Build:
    """What a build started with; the metadata is made from these values."""

    image: Image
    source: Source
    clock: Clock
    check_hash: str
    git: GitInfo


def build_prefix(catalog: Catalog, build: Build) -> str:
    return f"{catalog.image_prefix(build.image)}/{build.clock.build_version}"


def metadata(catalog: Catalog, build: Build, image_checksum: str) -> dict[str, str]:
    name = image_file(build.image, build.clock)
    return {
        "IMAGE": build.image.name,
        "IMAGE_FILE": name,
        "OS": build.image.os,
        "BUILD_VERSION": build.clock.build_version,
        "BUILD_DATE": build.clock.build_timestamp,
        "PARENT": build.source.name,
        "PARENT_URL": build.source.url,
        "PARENT_CHECKSUM": build.source.checksum,
        "CHECK_HASH": build.check_hash,
        "PACKER_GIT_REMOTE": build.git.remote,
        "PACKER_GIT_COMMIT": build.git.commit,
        "IMAGE_URL": catalog.public_url(f"{build_prefix(catalog, build)}/{name}"),
        "IMAGE_CHECKSUM": image_checksum,
    }


def publish(
    catalog: Catalog,
    store: Store,
    build: Build,
    image_path: Path,
    check_image=qemu_img_check,
) -> dict[str, str]:
    """Upload image, checksum and metadata, then latest.json last."""
    check_image(image_path)
    digest = sha512_file(image_path)
    meta = metadata(catalog, build, f"sha512:{digest}")
    prefix = build_prefix(catalog, build)
    name = meta["IMAGE_FILE"]
    meta_json = (json.dumps(meta, indent=2) + "\n").encode()

    store.put_file(f"{prefix}/{name}", image_path, "application/octet-stream")
    store.put_bytes(f"{prefix}/{name}.sha512", f"{digest}  {name}\n".encode(), "text/plain")
    store.put_bytes(f"{prefix}/metadata.json", meta_json, "application/json")
    # latest.json must never point at an object that is not there
    store.head(f"{prefix}/{name}")
    store.put_bytes(
        f"{catalog.image_prefix(build.image)}/latest.json", meta_json, "application/json"
    )
    return meta


def builds_to_prune(
    catalog: Catalog,
    image: Image,
    keys: Iterable[str],
    protected_urls: set[str],
) -> list[str]:
    """Keys of every build beyond the newest retain_images, except protected parents."""
    prefix = catalog.image_prefix(image) + "/"
    by_version: dict[str, list[str]] = {}
    for key in keys:
        rest = key[len(prefix) :] if key.startswith(prefix) else None
        if not rest or "/" not in rest:
            continue  # latest.json and anything not in a build folder
        version = rest.split("/", 1)[0]
        by_version.setdefault(version, []).append(key)

    doomed = []
    for version in sorted(by_version, reverse=True)[image.retain_images :]:
        build_keys = by_version[version]
        if any(catalog.public_url(k) in protected_urls for k in build_keys):
            continue
        doomed.extend(build_keys)
    return sorted(doomed)


def prune(catalog: Catalog, store: Store, image: Image) -> list[str]:
    protected = set()
    for other in catalog.ordered():
        latest = store.latest(other)
        if latest and latest.get("PARENT_URL"):
            protected.add(latest["PARENT_URL"])
    # the build latest.json names is always the newest, so retain_images >= 1 keeps it
    keys = store.list_keys(catalog.image_prefix(image) + "/")
    doomed = builds_to_prune(catalog, image, keys, protected)
    if doomed:
        store.delete(doomed)
    return doomed
