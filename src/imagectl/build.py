"""Build images: locks, build dirs, logs, and running a plan parents first."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from . import check_hash, packer
from .catalog import Catalog, Image, Source
from .preflight import Latest, source_from_latest
from .publish import Build

BUILD_DIR = "build"
CACHE_ENTRY_RE = re.compile(r"^([0-9a-f]{40})\.")

LatestReader = Callable[[Image], "Latest | None"]
Publisher = Callable[[Build, Path], None]


class BuildError(Exception):
    pass


def build_root(root: Path) -> Path:
    return root / BUILD_DIR


def packer_cache_dir(root: Path) -> Path:
    configured = os.environ.get("PACKER_CACHE_DIR")
    path = Path(configured) if configured else build_root(root) / ".cache" / "packer"
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def collections_dir(root: Path) -> Path:
    return (build_root(root) / ".cache" / "collections").resolve()


@contextmanager
def image_lock(root: Path, name: str) -> Iterator[None]:
    locks = build_root(root) / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / f"{name}.lock").open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BuildError(f"{name} is already being built") from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def run_logged(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    verbose: bool,
    prefix: str,
) -> None:
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"$ {' '.join(cmd[:2])} ...\n")
        log.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            if verbose:
                sys.stdout.write(f"[{prefix}] {line}")
                sys.stdout.flush()
        code = proc.wait()
    if code != 0:
        raise BuildError(f"{cmd[0]} {cmd[1]} failed with exit code {code}, see {log_path}")


def install_collections(root: Path) -> Path:
    """Install ansible/requirements.yml once per run into build/.cache/collections."""
    target = collections_dir(root)
    target.mkdir(parents=True, exist_ok=True)
    requirements = root / packer.ANSIBLE_DIR / "requirements.yml"
    if requirements.is_file():
        subprocess.run(
            [
                "ansible-galaxy",
                "collection",
                "install",
                "-r",
                str(requirements),
                "-p",
                str(target),
            ],
            cwd=root,
            env={**os.environ, "ANSIBLE_COLLECTIONS_PATH": str(target)},
            check=True,
            stdout=subprocess.DEVNULL,
        )
    return target


def packer_init(root: Path, images: list[Image], env: dict[str, str]) -> None:
    """One packer init per template dir, before any build starts."""
    done = set()
    for image in images:
        if image.os in done or not (root / packer.template_dir(image)).is_dir():
            continue
        done.add(image.os)
        subprocess.run(packer.init_command(image), cwd=root, env=env, check=True)


def cache_key(checksum: str) -> str:
    # the name Packer gives a download it verified against checksum
    return hashlib.sha1(checksum.encode()).hexdigest()


def prune_packer_cache(cache: Path, current_checksums: set[str]) -> list[str]:
    keep = {cache_key(c) for c in current_checksums}
    removed = []
    for entry in sorted(cache.iterdir()):
        m = CACHE_ENTRY_RE.match(entry.name)
        if entry.is_file() and m and m.group(1) not in keep:
            entry.unlink()
            removed.append(entry.name)
    return removed


def current_checksums(catalog: Catalog, latest: dict[str, Latest | None]) -> set[str]:
    """Checksums of every image's current source: upstream pins and parents' latest.json."""
    sums = {up.checksum for up in catalog.upstreams.values()}
    for image in catalog.ordered():
        parent_latest = latest.get(image.name)
        if image.children and parent_latest and parent_latest.get("IMAGE_CHECKSUM"):
            sums.add(parent_latest["IMAGE_CHECKSUM"])
    return sums


def resolve_source(catalog: Catalog, image: Image, read_latest: LatestReader) -> Source:
    if image.parent is None:
        return catalog.upstream_source(image)
    parent = catalog.get(image.parent)
    latest = read_latest(parent)
    if latest is None:
        raise BuildError(f"publish `{parent.name}` first")
    return source_from_latest(latest)


@dataclass
class BuildOptions:
    verbose: bool = False
    keep: bool = False


def run_build(
    catalog: Catalog,
    image: Image,
    read_latest: LatestReader,
    options: BuildOptions,
    publisher: Publisher | None = None,
) -> Path:
    """Build one image; publish it if a publisher is given. Returns the build dir."""
    root = catalog.root
    missing = packer.missing_files(root, image)
    if missing:
        raise BuildError(f"{image.name}: missing {', '.join(missing)}")

    with image_lock(root, image.name):
        source = resolve_source(catalog, image, read_latest)
        image_hash = check_hash.for_image(catalog, image)
        git = packer.git_info(root)
        clock = packer.Clock.now()
        build_dir = build_root(root) / image.name / clock.build_version
        try:
            build_dir.mkdir(parents=True)
        except FileExistsError:
            raise BuildError(f"{build_dir} already exists") from None
        log_path = build_dir / "packer.log"
        env = packer.environment(root, packer_cache_dir(root), collections_dir(root))

        with tempfile.TemporaryDirectory(prefix=f"imagectl-{image.name}-") as tmp:
            inputs = packer.BuildInputs(
                image=image,
                source=source,
                clock=clock,
                check_hash=image_hash,
                git=git,
                output_directory=(build_dir / "output").resolve(),
                accelerator=packer.detect_accelerator(),
                ssh=packer.generate_ssh(Path(tmp)),
            )
            run_logged(
                packer.build_command(inputs), root, env, log_path, options.verbose, image.name
            )

        image_path = inputs.output_directory / packer.image_file(image, clock)
        if not image_path.is_file():
            raise BuildError(f"packer finished but {image_path} does not exist")
        if publisher is not None:
            publisher(Build(image, source, clock, image_hash, git), image_path)
        if not options.keep:
            remove_build_dir(build_dir)
        return build_dir


def remove_build_dir(build_dir: Path) -> None:
    """Remove a finished build, and its image's dir once no kept build is left in it."""
    shutil.rmtree(build_dir)
    # safe under the image lock; a kept build or a failed one leaves the dir non-empty
    with suppress(OSError):
        build_dir.parent.rmdir()


@dataclass(frozen=True)
class Outcome:
    status: str  # "ok", "failed" or "skipped"
    detail: str = ""


def run_scheduled(
    catalog: Catalog,
    due: list[str],
    build_one: Callable[[Image], None],
    jobs: int,
) -> dict[str, Outcome]:
    """Build the due images parents first, at most `jobs` at once.

    A child starts only after its parent (if due) has finished successfully. A failure skips
    the image's descendants only.
    """
    due_set = set(due)
    pending = [name for name in (i.name for i in catalog.ordered()) if name in due_set]
    results: dict[str, Outcome] = {}
    running: dict[Future, str] = {}

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        while pending or running:
            for name in list(pending):
                parent = catalog.get(name).parent
                if parent in due_set:
                    if parent not in results:
                        continue
                    if results[parent].status != "ok":
                        results[name] = Outcome("skipped", f"{parent} {results[parent].status}")
                        pending.remove(name)
                        continue
                if len(running) >= jobs:
                    break
                pending.remove(name)
                running[pool.submit(build_one, catalog.get(name))] = name

            if not running:
                continue
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in finished:
                name = running.pop(future)
                error = future.exception()
                if error is None:
                    results[name] = Outcome("ok")
                else:
                    results[name] = Outcome("failed", str(error) or type(error).__name__)
    return {name: results[name] for name in (i.name for i in catalog.ordered()) if name in results}
