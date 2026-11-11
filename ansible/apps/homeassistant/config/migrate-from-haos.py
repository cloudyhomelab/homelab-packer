"""Moves Home Assistant, Zigbee2MQTT and Matter Server state from a HAOS backup into the datasets.

  extract BACKUP STAGING   unpack an unencrypted HAOS backup, then check it
  check STAGING            check the unpacked state again, e.g. after editing it
  apply STAGING            check, then copy into /srv/homeassistant, set the owners and point
                           Home Assistant's Matter integration at the container

The backup and the staging directory are never modified by apply, so both stay as the fallback.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

APP = "homeassistant"
SRV = Path("/srv/homeassistant")
SUBUID = Path("/etc/subuid")
SUBGID = Path("/etc/subgid")
# container IDs the datasets are owned by, as in storage.yml
CONFIG_ID = 0
ZIGBEE2MQTT_ID = 1000
MATTER_ID = 1000
# stopped first: apply replaces what they hold open
UNITS = (
    "homeassistant.service",
    "homeassistant-zigbee2mqtt.service",
    "homeassistant-matter.service",
    "homeassistant-database.service",
)
DATASETS = ("config", "backups", "db", "matter", "zigbee2mqtt")

HA_ARCHIVE = "homeassistant.tar.gz"
MATTER_ARCHIVE_GLOB = "*matter_server*.tar.gz"
ZIGBEE2MQTT_ARCHIVE_GLOB = "*zigbee2mqtt*.tar.gz"
# Supervisor's layout inside each archive
ARCHIVE_DATA_DIR = "data"
APP_METADATA = "addon.json"

# history starts fresh; the image mounts its own configuration.yaml and secrets.yaml over these
HA_SKIP = re.compile(r"^(home-assistant_v2\.db.*|configuration\.yaml|secrets\.yaml)$")
CONFIG_ENTRIES = Path(".storage/core.config_entries")
# the Matter server container; the HAOS entry points at the app and has HA manage it through the
# Supervisor, which is absent here, so the integration would never load
MATTER_ENTRY = {
    "url": "ws://127.0.0.1:5580/ws",
    "use_addon": False,
    "integration_created_addon": False,
}
# Zigbee2MQTT generates these when they are missing and forms a new network on the coordinator
NETWORK_KEYS = ("network_key", "pan_id", "ext_pan_id")
# Zigbee2MQTT's advanced.channel when unset; checked against the coordinator backup instead
DEFAULT_CHANNEL = 11
COORDINATOR_BACKUP = "coordinator_backup.json"
# Zigbee2MQTT's indirection to secret.yaml, written as a quoted string rather than a YAML tag
SECRET_PREFIX = "!secret "
STOPPED_STATES = {"inactive", "failed"}


@dataclass
class Staged:
    root: Path
    ha_config: Path | None = None
    zigbee2mqtt: Path | None = None
    zigbee2mqtt_options: dict = field(default_factory=dict)
    matter: Path | None = None
    matter_options: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def extract(backup: Path, staging: Path) -> None:
    if staging.exists():
        fail(f"{staging} exists; pick a new directory")
    outer_dir = staging / "archives"
    with tarfile.open(backup) as outer:
        outer.extractall(outer_dir, filter="data")
    metadata_path = outer_dir / "backup.json"
    if not metadata_path.is_file():
        fail(f"{backup} is not a HAOS backup: no backup.json")
    metadata = json.loads(metadata_path.read_text())
    if metadata.get("protected"):
        fail("the backup is encrypted; decrypt it or download it unencrypted from HAOS")
    for archive in sorted(outer_dir.glob("*.tar.gz")):
        target = staging / archive.name.removesuffix(".tar.gz")
        with tarfile.open(archive) as inner:
            inner.extractall(target, filter="data")
    print(f"unpacked {backup} into {staging}")


def app_options(staging: Path, app_glob: str) -> dict:
    """The options set in the HAOS app's UI, which HAOS passes in and the data dir does not hold."""
    for app_dir in staging.glob(app_glob.removesuffix(".tar.gz")):
        metadata_path = app_dir / APP_METADATA
        if metadata_path.is_file():
            metadata = json.loads(metadata_path.read_text())
            # the rest of "user" holds the app's Supervisor tokens, which must not be printed
            return metadata.get("user", {}).get("options", {})
    return {}


def find_zigbee2mqtt(root: Path) -> list[Path]:
    """Directories holding a Zigbee2MQTT state; the app's data path differs between versions."""
    return sorted(
        path.parent
        for path in root.rglob("database.db")
        if (path.parent / "configuration.yaml").is_file() and "archives" not in path.parts
    )


def load_yaml(path: Path) -> dict:
    try:
        import yaml  # python3-yaml, a dependency of cloud-init; not in the standard library
    except ImportError:
        fail("python3-yaml is missing: apt install python3-yaml")
        raise
    loaded = yaml.safe_load(path.read_text()) if path.is_file() else None
    return loaded if isinstance(loaded, dict) else {}


def resolve_secret(value: object, secrets: dict) -> object:
    if isinstance(value, str) and value.startswith(SECRET_PREFIX):
        return secrets.get(value.removeprefix(SECRET_PREFIX).strip())
    return value


def check(staging: Path) -> Staged:
    staged = Staged(root=staging)

    ha_config = staging / "homeassistant" / ARCHIVE_DATA_DIR
    if (ha_config / ".storage").is_dir():
        staged.ha_config = ha_config
    else:
        staged.errors.append(f"no Home Assistant config with .storage in {ha_config}")

    matter_dirs = [
        p / ARCHIVE_DATA_DIR for p in staging.glob(MATTER_ARCHIVE_GLOB.removesuffix(".tar.gz"))
    ]
    matter_dirs = [p for p in matter_dirs if p.is_dir() and any(p.iterdir())]
    if len(matter_dirs) == 1:
        staged.matter = matter_dirs[0]
        staged.matter_options = app_options(staging, MATTER_ARCHIVE_GLOB)
    else:
        staged.errors.append(
            f"expected one non-empty Matter Server data dir, found {matter_dirs or 'none'}"
        )

    zigbee_dirs = find_zigbee2mqtt(staging)
    if len(zigbee_dirs) == 1:
        staged.zigbee2mqtt = zigbee_dirs[0]
        check_zigbee2mqtt(staged)
    else:
        staged.errors.append(
            "expected one Zigbee2MQTT dir with configuration.yaml and database.db, "
            f"found {zigbee_dirs or 'none'}"
        )
    return staged


def check_zigbee2mqtt(staged: Staged) -> None:
    staged.zigbee2mqtt_options = app_options(staged.root, ZIGBEE2MQTT_ARCHIVE_GLOB)
    config_path = staged.zigbee2mqtt / "configuration.yaml"
    config = load_yaml(config_path)
    secrets = load_yaml(staged.zigbee2mqtt / "secret.yaml")
    advanced = config.get("advanced") or {}
    for key in NETWORK_KEYS:
        value = resolve_secret(advanced.get(key), secrets)
        if value in (None, "") or str(value).upper() == "GENERATE":
            staged.errors.append(f"{config_path}: advanced.{key} is missing or GENERATE")
    channel = resolve_secret(advanced.get("channel"), secrets)
    check_channel(staged, config_path, channel)

    serial = config.get("serial") or {}
    port = str(resolve_secret(serial.get("port"), secrets) or "")
    if not port.startswith("tcp://"):
        app_serial = staged.zigbee2mqtt_options.get("serial", {})
        staged.errors.append(
            f"{config_path}: serial port is {port or 'missing'}, expected tcp://<slzb>:6638; "
            f"the HAOS app options had serial {app_serial or 'unset'}; "
            "add port and adapter under serial:"
        )
    if not serial.get("adapter"):
        staged.warnings.append(f"{config_path}: no serial adapter; Zigbee2MQTT then probes for it")

    if not (staged.zigbee2mqtt / COORDINATOR_BACKUP).is_file():
        staged.warnings.append(
            f"{staged.zigbee2mqtt}: no coordinator_backup.json, the fallback if the network breaks"
        )


def check_channel(staged: Staged, config_path: Path, channel: object) -> None:
    """The channel Zigbee2MQTT will use must be the one the coordinator's network is on."""
    expected = DEFAULT_CHANNEL if channel is None else int(channel)
    backup_path = staged.zigbee2mqtt / COORDINATOR_BACKUP
    if not backup_path.is_file():
        if channel is None:
            staged.errors.append(
                f"{config_path}: advanced.channel is unset and there is no {COORDINATOR_BACKUP} "
                f"to confirm the default {DEFAULT_CHANNEL}"
            )
        return
    backup = json.loads(backup_path.read_text())
    actual = backup.get("channel")
    if actual != expected:
        staged.errors.append(
            f"{config_path}: Zigbee2MQTT would use channel {expected}, "
            f"the coordinator backup says {actual}; set advanced.channel: {actual}"
        )
        return
    source = "default" if channel is None else "configured"
    staged.notes.append(f"Zigbee channel {expected} ({source}) matches the coordinator backup")


def report(staged: Staged) -> None:
    print(f"Home Assistant config: {staged.ha_config}")
    print(f"Zigbee2MQTT:           {staged.zigbee2mqtt}")
    print(f"Matter Server:         {staged.matter}")
    # the image sets these itself; compare, so no HAOS app setting is dropped silently
    print(f"HAOS Zigbee2MQTT app options:   {staged.zigbee2mqtt_options or 'none'}")
    print(f"HAOS Matter Server app options: {staged.matter_options or 'none'}")
    for note in staged.notes:
        print(note)
    for warning in staged.warnings:
        print(f"warning: {warning}")
    for error in staged.errors:
        print(f"error: {error}", file=sys.stderr)
    if staged.errors:
        print("fix the staged files and run check again; nothing was copied", file=sys.stderr)
    else:
        print("checks passed")


def id_base(path: Path) -> int:
    for line in path.read_text().splitlines():
        fields = line.split(":")
        if len(fields) == 3 and fields[0] == APP:
            return int(fields[1])
    fail(f"no ID range for {APP} in {path}")
    raise AssertionError


def require_stopped() -> None:
    result = subprocess.run(["systemctl", "is-active", *UNITS], capture_output=True, text=True)
    active = [
        unit
        for unit, state in zip(UNITS, result.stdout.split(), strict=True)
        if state not in STOPPED_STATES
    ]
    if active:
        fail(f"stop these first: systemctl stop {' '.join(active)}")


def require_datasets(srv: Path, replace: bool) -> None:
    for name in DATASETS:
        dataset = srv / name
        if not dataset.is_mount():
            fail(f"{dataset} is not mounted")
        if any(dataset.iterdir()) and not replace:
            fail(
                f"{dataset} is not empty; "
                "--replace empties every dataset first (test data, old database)"
            )


def empty(dataset: Path) -> None:
    for entry in dataset.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def chown_tree(root: Path, uid: int, gid: int) -> None:
    # lchown: a symlink's own owner, never its target, which may be outside the dataset
    os.lchown(root, uid, gid)
    for directory, dirs, files in os.walk(root):
        for name in dirs + files:
            os.lchown(os.path.join(directory, name), uid, gid)


def apply(staged: Staged, srv: Path, replace: bool) -> None:
    require_stopped()
    require_datasets(srv, replace)
    uid_base = id_base(SUBUID)
    gid_base = id_base(SUBGID)

    if replace:
        for name in DATASETS:
            empty(srv / name)

    def ignore_ha(directory: str, names: list[str]) -> set[str]:
        skipped = {n for n in names if Path(directory) == staged.ha_config and HA_SKIP.match(n)}
        if staged.zigbee2mqtt is not None and Path(directory) == staged.zigbee2mqtt.parent:
            skipped.add(staged.zigbee2mqtt.name)
        return skipped

    copies = (
        (staged.ha_config, srv / "config", CONFIG_ID, ignore_ha),
        (staged.zigbee2mqtt, srv / "zigbee2mqtt", ZIGBEE2MQTT_ID, None),
        (staged.matter, srv / "matter", MATTER_ID, None),
    )
    for source, target, container_id, ignore in copies:
        shutil.copytree(source, target, symlinks=True, ignore=ignore, dirs_exist_ok=True)
        chown_tree(target, uid_base + container_id, gid_base + container_id)
        print(f"copied {source} -> {target}, owner {uid_base + container_id}")

    repoint_matter(srv / "config" / CONFIG_ENTRIES)

    print(
        "\nnext: start Zigbee2MQTT alone and watch it reuse the existing network:\n"
        "  systemctl start homeassistant-zigbee2mqtt && journalctl -fu homeassistant-zigbee2mqtt\n"
        "stop it at once if it forms a new network; then start the rest:\n"
        "  systemctl start homeassistant-matter homeassistant"
    )


def repoint_matter(path: Path) -> None:
    """Point HA's Matter integration at the container; HA has no UI to reconfigure it."""
    if not path.is_file():
        print(f"no {path}; Matter integration unchanged")
        return
    doc = json.loads(path.read_text())
    entries = [e for e in doc["data"]["entries"] if e["domain"] == "matter"]
    if not entries:
        print("no Matter integration in Home Assistant; nothing to repoint")
        return

    backup = path.with_name(path.name + ".before-matter")
    shutil.copy2(path, backup)
    owner = path.stat()
    os.lchown(backup, owner.st_uid, owner.st_gid)
    for entry in entries:
        print(f"Matter integration was: {entry['data']}")
        entry["data"].update(MATTER_ENTRY)
        print(f"Matter integration now: {entry['data']}")
    # written in place, so the file keeps its owner
    path.write_text(json.dumps(doc, indent=2))
    print(f"kept the previous version as {backup}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    extract_cmd = commands.add_parser("extract")
    extract_cmd.add_argument("backup", type=Path)
    extract_cmd.add_argument("staging", type=Path)
    check_cmd = commands.add_parser("check")
    check_cmd.add_argument("staging", type=Path)
    apply_cmd = commands.add_parser("apply")
    apply_cmd.add_argument("staging", type=Path)
    apply_cmd.add_argument("--replace", action="store_true", help="empty every dataset first")
    apply_cmd.add_argument("--srv", type=Path, default=SRV, help=argparse.SUPPRESS)
    args = parser.parse_args()

    staging = args.staging.resolve()
    if args.command == "extract":
        extract(args.backup, staging)
    staged = check(staging)
    report(staged)
    if staged.errors:
        sys.exit(1)
    if args.command == "apply":
        apply(staged, args.srv, args.replace)


if __name__ == "__main__":
    main()
