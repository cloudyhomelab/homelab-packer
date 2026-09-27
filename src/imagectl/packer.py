"""Run Packer for one image with every input resolved by the driver.

Listed in .check_hash: a change here rebuilds every image.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .catalog import Image, Source

USERNAME = "packeruser"
BUILD_VERSION_FORMAT = "%Y%m%d-%H%M"
BUILD_DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"
ANSIBLE_DIR = "ansible"


def template_dir(image: Image) -> str:
    return f"upstream/{image.os}/packer"


def playbook_file(image: Image) -> str:
    return f"{ANSIBLE_DIR}/{image.playbook}.yml"


def missing_files(root: Path, image: Image) -> list[str]:
    """What an image needs on disk before it can be validated or built."""
    missing = []
    if not (root / playbook_file(image)).is_file():
        missing.append(f"playbook {playbook_file(image)}")
    if not (root / template_dir(image)).is_dir():
        missing.append(f"template {template_dir(image)}/")
    cloud_init = f"upstream/{image.os}/cloud-init"
    if not (root / cloud_init).is_dir():
        missing.append(f"cloud-init {cloud_init}/")
    return missing


def detect_accelerator() -> str:
    return "kvm" if os.access("/dev/kvm", os.R_OK | os.W_OK) else "none"


@dataclass(frozen=True)
class Clock:
    build_version: str
    build_timestamp: str

    @classmethod
    def now(cls, now: datetime | None = None) -> Clock:
        # one reading for both values
        now = now or datetime.now(UTC)
        return cls(now.strftime(BUILD_VERSION_FORMAT), now.strftime(BUILD_DATE_FORMAT))


@dataclass(frozen=True)
class SshMaterial:
    ca_public_key: Path
    private_key: Path
    certificate: Path


def generate_ssh(workdir: Path) -> SshMaterial:
    """A throwaway user CA and a key signed by it, for the build VM's SSH login."""
    ca = workdir / "user_ca"
    key = workdir / "id_ed25519"

    def keygen(*args: str) -> None:
        subprocess.run(["ssh-keygen", "-q", *args], check=True)

    keygen("-t", "ed25519", "-N", "", "-f", str(ca), "-C", "ssh-user-ca")
    keygen("-t", "ed25519", "-N", "", "-f", str(key), "-C", f"for {USERNAME} user")
    keygen("-s", str(ca), "-I", "packer-build", "-n", USERNAME, "-V", "+4h", f"{key}.pub")
    return SshMaterial(
        ca_public_key=Path(f"{ca}.pub"),
        private_key=key,
        certificate=Path(f"{key}-cert.pub"),
    )


def normalize_remote(url: str) -> str:
    """https URL without credentials or .git, whatever form origin was cloned with."""
    url = url.strip()
    if m := re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+)$", url):
        url = f"https://{m.group(1)}/{m.group(2)}"
    url = re.sub(r"^(https?://)[^@/]+@", r"\1", url)
    return url.removesuffix("/").removesuffix(".git")


@dataclass(frozen=True)
class GitInfo:
    remote: str
    commit: str


def git_info(root: Path) -> GitInfo:
    def git(*args: str) -> str:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else ""

    return GitInfo(
        remote=normalize_remote(git("config", "--get", "remote.origin.url")) or "unknown",
        commit=git("describe", "--always", "--dirty") or "unknown",
    )


@dataclass(frozen=True)
class BuildInputs:
    image: Image
    source: Source
    clock: Clock
    check_hash: str
    git: GitInfo
    output_directory: Path
    accelerator: str
    ssh: SshMaterial


def image_file(image: Image, clock: Clock) -> str:
    return f"{image.name}-{clock.build_version}.qcow2"


def variables(inputs: BuildInputs) -> dict[str, str]:
    image = inputs.image
    return {
        "image_name": image.name,
        "os": image.os,
        "playbook_file": playbook_file(image),
        "disk_size": image.disk_size,
        "memory": str(image.memory),
        "cpus": str(image.cpus),
        "accelerator": inputs.accelerator,
        "parent_name": inputs.source.name,
        "parent_url": inputs.source.url,
        "parent_checksum": inputs.source.checksum,
        "build_version": inputs.clock.build_version,
        "build_timestamp": inputs.clock.build_timestamp,
        "check_hash": inputs.check_hash,
        "git_remote": inputs.git.remote,
        "git_commit": inputs.git.commit,
        "username": USERNAME,
        "password": secrets.token_urlsafe(24),
        "output_directory": str(inputs.output_directory),
        "ssh_user_ca_public_key_file": str(inputs.ssh.ca_public_key),
        "ssh_private_key_file": str(inputs.ssh.private_key),
        "ssh_certificate_file": str(inputs.ssh.certificate),
    }


def var_args(inputs: BuildInputs) -> list[str]:
    args = []
    for key, value in variables(inputs).items():
        args += ["-var", f"{key}={value}"]
    return args


def environment(root: Path, cache_dir: Path, collections_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PACKER_CACHE_DIR"] = str(cache_dir)
    env["ANSIBLE_COLLECTIONS_PATH"] = str(collections_dir)
    env["ANSIBLE_NOCOLOR"] = "1"
    cfg = root / ANSIBLE_DIR / "ansible.cfg"
    if cfg.is_file():
        env["ANSIBLE_CONFIG"] = str(cfg)
    return env


def init_command(image: Image) -> list[str]:
    return ["packer", "init", template_dir(image)]


def validate_command(inputs: BuildInputs) -> list[str]:
    return ["packer", "validate", *var_args(inputs), template_dir(inputs.image)]


def build_command(inputs: BuildInputs) -> list[str]:
    return [
        "packer",
        "build",
        "-color=false",
        "-on-error=abort",
        *var_args(inputs),
        template_dir(inputs.image),
    ]
