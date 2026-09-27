"""Boot an image in QEMU on a throwaway overlay, for a look over the serial console."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import urllib.request
from pathlib import Path

from .build import build_root
from .catalog import Catalog, Image
from .packer import detect_accelerator
from .preflight import fetch_latest

SEED_FILES = ("user-data", "meta-data", "network-config")


class TestVmError(Exception):
    pass


def workdir(root: Path, image: Image) -> Path:
    path = build_root(root) / "test" / image.name
    path.mkdir(parents=True, exist_ok=True)
    return path


def verify_checksum(path: Path, checksum: str) -> bool:
    algo, _, expected = checksum.partition(":")
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest() == expected


def published_image(catalog: Catalog, image: Image, work: Path) -> Path:
    latest = fetch_latest(catalog, image)
    if latest is None:
        raise TestVmError(f"{image.name} has not been published")
    path = work / latest["IMAGE_FILE"]
    if path.is_file() and verify_checksum(path, latest["IMAGE_CHECKSUM"]):
        return path
    for old in work.glob("*.qcow2"):
        old.unlink()
    print(f"downloading {latest['IMAGE_URL']}")
    partial = path.with_suffix(".part")
    with (
        urllib.request.urlopen(latest["IMAGE_URL"], timeout=60) as response,
        partial.open("wb") as f,
    ):
        shutil.copyfileobj(response, f, 1024 * 1024)
    if not verify_checksum(partial, latest["IMAGE_CHECKSUM"]):
        partial.unlink()
        raise TestVmError(f"checksum mismatch for {latest['IMAGE_URL']}")
    partial.rename(path)
    return path


def local_image(root: Path, image: Image) -> Path:
    builds = sorted((build_root(root) / image.name).glob("*/output/*.qcow2"))
    if not builds:
        raise TestVmError(
            f"no kept build of {image.name} under build/{image.name}/; "
            f"run `imagectl build --now --keep {image.name}` first"
        )
    return builds[-1]


def make_seed(root: Path, image: Image, work: Path) -> Path:
    seed_dir = root / "upstream" / image.os / "test"
    missing = [name for name in SEED_FILES if not (seed_dir / name).is_file()]
    if missing:
        raise TestVmError(f"missing test seed files in {seed_dir}: {', '.join(missing)}")
    seed = work / "seed.iso"
    seed.unlink(missing_ok=True)
    subprocess.run(
        [
            "xorriso",
            "-as",
            "mkisofs",
            "-quiet",
            "-output",
            str(seed),
            "-volid",
            "cidata",
            "-joliet",
            "-rock",
            *[str(seed_dir / name) for name in SEED_FILES],
        ],
        check=True,
    )
    return seed


def make_overlay(base: Path, work: Path) -> Path:
    overlay = work / "overlay.qcow2"
    overlay.unlink(missing_ok=True)
    subprocess.run(
        [
            "qemu-img",
            "create",
            "-q",
            "-f",
            "qcow2",
            "-F",
            "qcow2",
            "-b",
            str(base.resolve()),
            str(overlay),
        ],
        check=True,
    )
    return overlay


def qemu_command(overlay: Path, seed: Path, accelerator: str) -> list[str]:
    cmd = ["qemu-system-x86_64", "-m", "2048", "-smp", "2"]
    if accelerator == "kvm":
        cmd.append("-enable-kvm")
    return [
        *cmd,
        "-drive",
        f"file={overlay},if=virtio,index=0",
        "-drive",
        f"file={seed},format=raw,if=virtio,index=1",
        "-nic",
        "user,model=virtio",
        "-nographic",
        "-serial",
        "mon:stdio",
    ]


def run(catalog: Catalog, image: Image, local: bool) -> int:
    root = catalog.root
    work = workdir(root, image)
    base = local_image(root, image) if local else published_image(catalog, image, work)
    print(f"booting {base}")
    seed = make_seed(root, image, work)
    overlay = make_overlay(base, work)
    return subprocess.run(qemu_command(overlay, seed, detect_accelerator())).returncode
