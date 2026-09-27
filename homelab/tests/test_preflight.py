import io
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest
from conftest import write_catalog

from imagectl.catalog import Source, load
from imagectl.preflight import PreflightError, build_required, fetch_latest, plan

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
SOURCE = Source("debian-cloud", "https://example.net/debian.qcow2", "sha512:" + "a" * 128)


def latest(**overrides):
    base = {
        "IMAGE": "debian-base",
        "BUILD_DATE": "2026-09-26 12:00:00 +0000",
        "PARENT_CHECKSUM": SOURCE.checksum,
        "CHECK_HASH": "sha256:h",
        "IMAGE_URL": "https://s3.example.net/os-image-staging/debian/debian-base/x.qcow2",
        "IMAGE_CHECKSUM": "sha512:" + "c" * 128,
    }
    return base | overrides


def required(entry, source=SOURCE, check_hash="sha256:h", max_age=timedelta(days=7)):
    return build_required(entry, source, check_hash, NOW, max_age)


def test_current_build_is_not_required():
    assert required(latest()) is None


def test_rule_1_never_built():
    assert required(None) == "never built"


def test_rule_2_source_changed():
    assert required(latest(PARENT_CHECKSUM="sha512:" + "b" * 128)) == "source changed"


def test_rule_2_parent_never_published():
    assert required(latest(), source=None) == "source changed"


def test_rule_3_check_hash_changed():
    assert required(latest(), check_hash="sha256:other") == "check hash changed"
    assert required(latest(), check_hash=None) == "check hash changed"


def test_rule_4_aged_out():
    assert required(latest(), max_age=timedelta(days=1)) == "aged out"
    assert required(latest(), max_age=timedelta(days=2)) is None
    assert required(latest(), max_age=timedelta(0)) == "aged out"


def test_child_ages_out_before_its_parent(tmp_path):
    write_catalog(
        tmp_path,
        images="""\
        images:
          - base:
              from: debian-cloud
              children:
                - honeypot:
                    max_age_days: 1
                - container
        """,
    )
    catalog = load(tmp_path)
    up = catalog.upstream_source(catalog.get("debian-base"))
    base = latest(PARENT_CHECKSUM=up.checksum)
    child = latest(PARENT_CHECKSUM=base["IMAGE_CHECKSUM"])
    published = {"debian-base": base, "debian-honeypot": child, "debian-container": child}
    hashes = dict.fromkeys(published, "sha256:h")

    due, _ = plan(catalog, hashes, lambda image: published[image.name], NOW)
    assert [(d.image, d.reason) for d in due] == [("debian-honeypot", "aged out")]


def test_plan_marks_descendants_of_a_due_image(catalog):
    base_up = catalog.upstream_source(catalog.get("debian-base"))
    fedora_up = catalog.upstream_source(catalog.get("fedora-base"))
    published = {}
    for image in catalog.ordered():
        if image.parent is None:
            parent_sum = (base_up if image.os == "debian" else fedora_up).checksum
        else:
            parent_sum = f"sha512:{image.parent}"
        published[image.name] = latest(
            IMAGE=image.name, PARENT_CHECKSUM=parent_sum, IMAGE_CHECKSUM=f"sha512:{image.name}"
        )
    hashes = dict.fromkeys(published, "sha256:h")
    hashes["debian-base"] = "sha256:changed"

    due, _ = plan(catalog, hashes, lambda image: published[image.name], NOW)
    assert [(d.image, d.reason) for d in due] == [
        ("debian-base", "check hash changed"),
        ("debian-kubernetes", "parent due (debian-base)"),
        ("debian-container", "parent due (debian-base)"),
        ("debian-edge", "parent due (debian-container)"),
    ]


def test_plan_on_an_empty_bucket_lists_everything_as_never_built(catalog):
    due, _ = plan(catalog, {}, lambda image: None, NOW)
    assert [d.reason for d in due] == ["never built"] * len(catalog.images)


class FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, body):
        super().__init__("https://x", code, "err", {}, io.BytesIO(body))


@pytest.mark.parametrize(
    ("code", "body", "expected"),
    [
        (404, b"<Code>NoSuchKey</Code>", None),
        (404, b"", None),
    ],
)
def test_fetch_latest_404_means_never_built(catalog, monkeypatch, code, body, expected):
    def urlopen(url, timeout):
        raise FakeHTTPError(code, body)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert fetch_latest(catalog, catalog.get("debian-base")) is expected


@pytest.mark.parametrize(
    ("code", "body"), [(404, b"<Code>NoSuchBucket</Code>"), (403, b""), (500, b"")]
)
def test_fetch_latest_other_errors_raise(catalog, monkeypatch, code, body):
    def urlopen(url, timeout):
        raise FakeHTTPError(code, body)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(PreflightError):
        fetch_latest(catalog, catalog.get("debian-base"))
