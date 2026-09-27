import threading
import time

import pytest

from imagectl import build
from imagectl.build import BuildError, image_lock, prune_packer_cache, run_scheduled


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
    assert not any(n.startswith("fedora-") and n != "fedora-base" for n in built)


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


def test_current_checksums_are_pins_and_parents_latest(catalog):
    latest = {
        "debian-base": {"IMAGE_CHECKSUM": "sha512:base"},
        "debian-kubernetes": {"IMAGE_CHECKSUM": "sha512:leaf"},
    }
    sums = build.current_checksums(catalog, latest)
    assert "sha512:base" in sums
    assert "sha512:leaf" not in sums
    assert {u.checksum for u in catalog.upstreams.values()} <= sums
