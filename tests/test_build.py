import dataclasses
import hashlib
import threading
import time
import urllib.error

import pytest

from imagectl import build
from imagectl.build import (
    BuildError,
    image_lock,
    prune_packer_cache,
    remove_build_dir,
    run_scheduled,
)


def test_parent_failure_skips_descendants_and_siblings_run(catalog):
    built = []

    def fake(image):
        built.append(image.name)
        if image.name == "fedora-base":
            raise RuntimeError("boom")

    due = [i.name for i in catalog.ordered()]
    outcomes = run_scheduled(catalog, due, fake, jobs=2)
    assert outcomes["fedora-base"].status == "failed"
    for name in ("fedora-kubernetes", "fedora-container", "fedora-edge"):
        assert outcomes[name].status == "skipped"
    assert outcomes["fedora-edge"].detail == "fedora-container skipped"
    for name in ("debian-base", "debian-kubernetes", "debian-container", "debian-edge"):
        assert outcomes[name].status == "ok"
    upstream_and_failed = ("fedora-cloud", "fedora-base")
    assert not any(n.startswith("fedora-") and n not in upstream_and_failed for n in built)


def test_sibling_failure_does_not_stop_siblings(catalog):
    def fake(image):
        if image.name == "debian-kubernetes":
            raise RuntimeError("boom")

    due = ["debian-base", "debian-kubernetes", "debian-container", "debian-edge"]
    outcomes = run_scheduled(catalog, due, fake, jobs=2)
    assert outcomes["debian-container"].status == "ok"
    assert outcomes["debian-edge"].status == "ok"


def test_jobs_limit(catalog):
    lock = threading.Lock()
    running = 0
    peak = 0

    def fake(image):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.02)
        with lock:
            running -= 1

    run_scheduled(catalog, [i.name for i in catalog.ordered()], fake, jobs=2)
    assert peak == 2
    peak = 0
    run_scheduled(catalog, [i.name for i in catalog.ordered()], fake, jobs=1)
    assert peak == 1


def test_child_starts_only_after_parent_published(catalog):
    published = set()
    order = []

    def fake(image):
        if image.parent in {"debian-base", "debian-container"}:
            # the child resolves its parent when it starts
            assert image.parent in published
        time.sleep(0.01)
        published.add(image.name)
        order.append(image.name)

    due = ["debian-base", "debian-kubernetes", "debian-container", "debian-edge"]
    outcomes = run_scheduled(catalog, due, fake, jobs=4)
    assert all(o.status == "ok" for o in outcomes.values())
    assert order[0] == "debian-base"
    assert order.index("debian-container") < order.index("debian-edge")


def test_child_of_a_parent_not_due_starts_at_once(catalog):
    started = []
    outcomes = run_scheduled(catalog, ["debian-edge"], lambda i: started.append(i.name), jobs=2)
    assert started == ["debian-edge"]
    assert outcomes == {"debian-edge": build.Outcome("ok")}


def test_second_build_of_the_same_image_fails_on_the_lock(tmp_path):
    with image_lock(tmp_path, "debian-base"):
        with (
            pytest.raises(BuildError, match="already being built"),
            image_lock(tmp_path, "debian-base"),
        ):
            pass
        with image_lock(tmp_path, "debian-edge"):
            pass
    with image_lock(tmp_path, "debian-base"):
        pass


def test_child_of_unpublished_parent_needs_the_parent_first(catalog):
    with pytest.raises(BuildError, match="publish `debian-base` first"):
        build.resolve_source(catalog, catalog.get("debian-kubernetes"), lambda image: None)


def test_top_level_image_needs_its_upstream_published_first(catalog):
    with pytest.raises(BuildError, match="publish `debian-cloud` first"):
        build.resolve_source(catalog, catalog.get("debian-base"), lambda image: None)


def test_top_level_image_builds_on_the_s3_copy(catalog):
    copy = {
        "IMAGE": "debian-cloud",
        "IMAGE_URL": "https://s3.example.net/os-image-staging/debian/debian-cloud/v/x.qcow2",
        "IMAGE_CHECKSUM": "sha512:copy",
    }
    source = build.resolve_source(catalog, catalog.get("debian-base"), lambda image: copy)
    assert (source.name, source.url, source.checksum) == (
        "debian-cloud",
        copy["IMAGE_URL"],
        "sha512:copy",
    )


UPSTREAM_BYTES = b"upstream qcow2"


def pin_upstream(catalog, data=UPSTREAM_BYTES):
    """Point debian-cloud's pin at data, so a fake download of it verifies."""
    up = catalog.upstreams["debian-cloud"]
    pinned = dataclasses.replace(up, checksum="sha512:" + hashlib.sha512(data).hexdigest())
    catalog.upstreams["debian-cloud"] = pinned
    return pinned


def fake_fetch(data=UPSTREAM_BYTES, calls=None):
    def fetch(url, dest):
        if calls is not None:
            calls.append(url)
        dest.write_bytes(data)

    return fetch


def test_upstream_node_downloads_verifies_and_publishes(catalog):
    up = pin_upstream(catalog)
    calls, published = [], []

    def publisher(result, image_path, sbom_path):
        published.append((result, image_path.name, image_path.read_bytes(), sbom_path))

    node = catalog.get("debian-cloud")
    build_dir = build.run_upstream(
        catalog, node, build.BuildOptions(), publisher, fake_fetch(calls=calls)
    )
    assert calls == [up.url]
    ((result, name, data, sbom),) = published
    assert (name, data, sbom) == (f"debian-cloud-{up.version}.qcow2", UPSTREAM_BYTES, None)
    assert result.clock.build_version == up.version
    assert (result.source.name, result.source.url, result.source.checksum) == (
        "",
        up.url,
        up.checksum,
    )
    assert result.check_hash == ""
    assert not build_dir.exists()


def test_upstream_node_fails_on_a_checksum_mismatch(catalog):
    pin_upstream(catalog)
    published = []
    with pytest.raises(BuildError, match="does not match"):
        build.run_upstream(
            catalog,
            catalog.get("debian-cloud"),
            build.BuildOptions(),
            lambda *args: published.append(args),
            fake_fetch(b"tampered"),
        )
    assert published == []


def test_upstream_node_fails_when_the_download_fails(catalog):
    def fetch(url, dest):
        raise urllib.error.URLError("unreachable")

    with pytest.raises(BuildError, match="unreachable"):
        build.run_upstream(catalog, catalog.get("debian-cloud"), build.BuildOptions(), None, fetch)


def test_upstream_node_retries_over_a_failed_download(catalog):
    up = pin_upstream(catalog)
    with pytest.raises(BuildError):
        build.run_upstream(
            catalog, catalog.get("debian-cloud"), build.BuildOptions(), None, fake_fetch(b"x")
        )
    build_dir = build.run_upstream(
        catalog, catalog.get("debian-cloud"), build.BuildOptions(keep=True), None, fake_fetch()
    )
    assert (build_dir / f"debian-cloud-{up.version}.qcow2").read_bytes() == UPSTREAM_BYTES


def test_prune_packer_cache_keeps_current_sources(tmp_path):
    keep = "sha512:" + "a" * 128
    old = "sha512:" + "b" * 128
    for checksum in (keep, old):
        (tmp_path / f"{build.cache_key(checksum)}.iso").write_text("x")
        (tmp_path / f"{build.cache_key(checksum)}.iso.lock").write_text("")
    (tmp_path / "unrelated").write_text("x")
    removed = prune_packer_cache(tmp_path, {keep})
    assert sorted(removed) == sorted(
        [f"{build.cache_key(old)}.iso", f"{build.cache_key(old)}.iso.lock"]
    )
    assert (tmp_path / f"{build.cache_key(keep)}.iso").exists()
    assert (tmp_path / "unrelated").exists()


def test_current_checksums_are_parents_latest(catalog):
    latest = {
        "debian-cloud": {"IMAGE_CHECKSUM": "sha512:copy"},
        "debian-base": {"IMAGE_CHECKSUM": "sha512:base"},
        "debian-kubernetes": {"IMAGE_CHECKSUM": "sha512:leaf"},
    }
    sums = build.current_checksums(catalog, latest)
    assert sums == {"sha512:copy", "sha512:base"}


def test_remove_build_dir_drops_the_emptied_image_dir(tmp_path):
    build_dir = tmp_path / "debian-base" / "20260927-1200"
    (build_dir / "output").mkdir(parents=True)
    remove_build_dir(build_dir)
    assert not (tmp_path / "debian-base").exists()


def test_remove_build_dir_leaves_kept_builds(tmp_path):
    kept = tmp_path / "debian-base" / "20260926-1200"
    kept.mkdir(parents=True)
    build_dir = tmp_path / "debian-base" / "20260927-1200"
    build_dir.mkdir()
    remove_build_dir(build_dir)
    assert not build_dir.exists()
    assert kept.is_dir()


def test_clean_removes_builds_and_test_dir_but_not_caches(tmp_path):
    root = tmp_path
    (root / "build" / "debian-base" / "20260927-1200" / "output").mkdir(parents=True)
    (root / "build" / "test" / "debian-base").mkdir(parents=True)
    (root / "build" / "debian-edge" / "20260927-1200").mkdir(parents=True)
    (root / "build" / ".cache" / "packer").mkdir(parents=True)
    removed = build.clean(root, "debian-base")
    assert removed == [root / "build" / "debian-base", root / "build" / "test" / "debian-base"]
    assert not (root / "build" / "test").exists()
    assert (root / "build" / "debian-edge" / "20260927-1200").is_dir()
    assert (root / "build" / ".cache" / "packer").is_dir()


def test_clean_of_an_image_being_built_fails_on_the_lock(tmp_path):
    (tmp_path / "build" / "debian-base" / "20260927-1200").mkdir(parents=True)
    with image_lock(tmp_path, "debian-base"), pytest.raises(BuildError, match="being built"):
        build.clean(tmp_path, "debian-base")
    assert (tmp_path / "build" / "debian-base" / "20260927-1200").is_dir()


@pytest.mark.parametrize("module", ["storage", "userns"])
def test_build_stops_before_packer_on_a_storage_or_range_problem(catalog, monkeypatch, module):
    monkeypatch.setattr(build.packer, "missing_files", lambda root, image: [])
    monkeypatch.setattr(build.storage, "problems", lambda c: {})
    monkeypatch.setattr(build.userns, "problems", lambda c: {})
    monkeypatch.setattr(getattr(build, module), "problems", lambda c: {"debian-edge": ["bad"]})

    def no_packer(*args, **kwargs):
        raise AssertionError("packer ran")

    monkeypatch.setattr(build, "run_logged", no_packer)
    options = build.BuildOptions()
    with pytest.raises(BuildError, match="debian-edge: bad"):
        build.run_build(catalog, catalog.get("debian-edge"), lambda image: None, options)
