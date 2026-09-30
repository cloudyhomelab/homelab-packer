import io
import json

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import ANY, Stubber

from imagectl import publish
from imagectl.catalog import Source
from imagectl.packer import Clock, GitInfo
from imagectl.publish import Build, Store, builds_to_prune

CLOCK = Clock("20260927-1200", "2026-09-27 12:00:00 +0000")
GIT = GitInfo("https://github.com/cloudyhomelab/homelab-packer", "abc1234")
PREFIX = "debian/debian-edge"
BUILD_PREFIX = f"{PREFIX}/20260927-1200"
IMAGE_FILE = "debian-edge-20260927-1200.qcow2"
BASE_URL = "https://s3.example.net/os-image-staging"


@pytest.fixture
def client():
    return boto3.client(
        "s3",
        endpoint_url="https://s3.example.net",
        region_name="home",
        aws_access_key_id="k",
        aws_secret_access_key="s",
        config=publish.CLIENT_CONFIG,
    )


@pytest.fixture
def build(catalog):
    source = Source(
        "debian-container",
        f"{BASE_URL}/debian/debian-container/20260926-0800/debian-container-20260926-0800.qcow2",
        "sha512:" + "c" * 128,
    )
    return Build(catalog.get("debian-edge"), source, CLOCK, "sha256:h", GIT)


@pytest.fixture
def image_path(tmp_path):
    path = tmp_path / IMAGE_FILE
    path.write_bytes(b"qcow2 bytes")
    return path


def no_check(path):
    pass


def expect_put(stub, key, content_type="application/json"):
    stub.add_response(
        "put_object",
        {},
        {"Bucket": "os-image-staging", "Key": key, "Body": ANY, "ContentType": content_type},
    )


def test_metadata_contents(catalog, build):
    meta = publish.metadata(catalog, build, "sha512:" + "d" * 128)
    assert meta == {
        "IMAGE": "debian-edge",
        "IMAGE_FILE": IMAGE_FILE,
        "OS": "debian",
        "BUILD_VERSION": "20260927-1200",
        "BUILD_DATE": "2026-09-27 12:00:00 +0000",
        "PARENT": "debian-container",
        "PARENT_URL": build.source.url,
        "PARENT_CHECKSUM": "sha512:" + "c" * 128,
        "CHECK_HASH": "sha256:h",
        "PACKER_GIT_REMOTE": GIT.remote,
        "PACKER_GIT_COMMIT": "abc1234",
        "IMAGE_URL": f"{BASE_URL}/{BUILD_PREFIX}/{IMAGE_FILE}",
        "IMAGE_CHECKSUM": "sha512:" + "d" * 128,
    }


def test_upload_order_puts_latest_json_last(catalog, client, build, image_path):
    with Stubber(client) as stub:
        expect_put(stub, f"{BUILD_PREFIX}/{IMAGE_FILE}", "application/octet-stream")
        expect_put(stub, f"{BUILD_PREFIX}/{IMAGE_FILE}.sha512", "text/plain")
        expect_put(stub, f"{BUILD_PREFIX}/metadata.json")
        stub.add_response(
            "head_object", {}, {"Bucket": "os-image-staging", "Key": f"{BUILD_PREFIX}/{IMAGE_FILE}"}
        )
        expect_put(stub, f"{PREFIX}/latest.json")
        meta = publish.publish(catalog, Store(catalog, client), build, image_path, no_check)
        stub.assert_no_pending_responses()
    assert meta["IMAGE_CHECKSUM"] == "sha512:" + publish.sha512_file(image_path)


def test_failure_before_latest_json_leaves_it_untouched(catalog, client, build, image_path):
    with Stubber(client) as stub:
        expect_put(stub, f"{BUILD_PREFIX}/{IMAGE_FILE}", "application/octet-stream")
        stub.add_client_error("put_object", "InternalError", http_status_code=500)
        with pytest.raises(ClientError):
            publish.publish(catalog, Store(catalog, client), build, image_path, no_check)
        # no further calls were made: latest.json was never written
        stub.assert_no_pending_responses()


def test_missing_image_object_stops_before_latest_json(catalog, client, build, image_path):
    with Stubber(client) as stub:
        expect_put(stub, f"{BUILD_PREFIX}/{IMAGE_FILE}", "application/octet-stream")
        expect_put(stub, f"{BUILD_PREFIX}/{IMAGE_FILE}.sha512", "text/plain")
        expect_put(stub, f"{BUILD_PREFIX}/metadata.json")
        stub.add_client_error("head_object", "404", http_status_code=404)
        with pytest.raises(ClientError):
            publish.publish(catalog, Store(catalog, client), build, image_path, no_check)
        stub.assert_no_pending_responses()


def test_failed_image_check_uploads_nothing(catalog, client, build, image_path):
    def bad_check(path):
        raise RuntimeError("qemu-img check failed")

    with Stubber(client) as stub, pytest.raises(RuntimeError):
        publish.publish(catalog, Store(catalog, client), build, image_path, bad_check)
        stub.assert_no_pending_responses()


def test_latest_missing_is_none_and_other_errors_raise(catalog, client):
    store = Store(catalog, client)
    image = catalog.get("debian-base")
    with Stubber(client) as stub:
        stub.add_client_error("get_object", "NoSuchKey", http_status_code=404)
        assert store.latest(image) is None
        stub.add_client_error("get_object", "AccessDenied", http_status_code=403)
        with pytest.raises(ClientError):
            store.latest(image)
        body = json.dumps({"IMAGE": "debian-base"}).encode()
        stub.add_response("get_object", {"Body": io.BytesIO(body)})
        assert store.latest(image) == {"IMAGE": "debian-base"}


def build_keys(prefix, versions):
    keys = [f"{prefix}/latest.json"]
    for v in versions:
        name = prefix.rsplit("/", 1)[1]
        keys += [
            f"{prefix}/{v}/{name}-{v}.qcow2",
            f"{prefix}/{v}/{name}-{v}.qcow2.sha512",
            f"{prefix}/{v}/metadata.json",
        ]
    return keys


def test_prune_keeps_newest_retain_images(catalog):
    image = catalog.get("debian-container")
    image.retain_images = 2
    versions = ["20260901-0000", "20260910-0000", "20260920-0000", "20260927-0000"]
    doomed = builds_to_prune(catalog, image, build_keys("debian/debian-container", versions), set())
    assert {k.split("/")[2] for k in doomed} == {"20260901-0000", "20260910-0000"}
    assert len(doomed) == 6
    assert "debian/debian-container/latest.json" not in doomed


def test_prune_never_deletes_a_current_parent(catalog):
    image = catalog.get("debian-container")
    image.retain_images = 1
    versions = ["20260901-0000", "20260910-0000", "20260927-0000"]
    protected = {
        f"{BASE_URL}/debian/debian-container/20260910-0000/debian-container-20260910-0000.qcow2"
    }
    doomed = builds_to_prune(
        catalog, image, build_keys("debian/debian-container", versions), protected
    )
    assert {k.split("/")[2] for k in doomed} == {"20260901-0000"}


def test_prune_reads_every_latest_json_for_protection(catalog, client):
    image = catalog.get("debian-container")
    image.retain_images = 1
    versions = ["20260910-0000", "20260927-0000"]
    old_url = (
        f"{BASE_URL}/debian/debian-container/20260910-0000/debian-container-20260910-0000.qcow2"
    )

    class FakeStore:
        def latest(self, other):
            return {"PARENT_URL": old_url} if other.name == "debian-edge" else None

        def list_keys(self, prefix):
            return build_keys("debian/debian-container", versions)

        def delete(self, keys):
            raise AssertionError("nothing should be deleted")

    assert publish.prune(catalog, FakeStore(), image) == []


def test_credentials_are_required(catalog, monkeypatch):
    monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "s")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fallback")
    with pytest.raises(publish.PublishError, match="S3_ACCESS_KEY_ID"):
        publish.s3_client(catalog)
