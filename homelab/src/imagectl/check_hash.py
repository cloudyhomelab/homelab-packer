"""CHECK_HASH: a hash over an image's resolved settings and the files that shape it."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pathspec
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .catalog import Catalog, Image

CHECK_HASH_FILE = ".check_hash"
ANSIBLE_DIR = "ansible"
PLACEHOLDERS = ("{os}", "{playbook}", "{roles}")
ROLE_INCLUDE_KEYS = {
    "import_role",
    "include_role",
    "ansible.builtin.import_role",
    "ansible.builtin.include_role",
    "ansible.legacy.import_role",
    "ansible.legacy.include_role",
}
PLAY_TASK_KEYS = ("pre_tasks", "tasks", "post_tasks", "handlers")


class CheckHashError(Exception):
    pass


@dataclass(frozen=True)
class Rule:
    line_no: int
    template: str


def read_rules(root: Path) -> list[Rule]:
    path = root / CHECK_HASH_FILE
    rules = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rules.append(Rule(line_no, line))
    return rules


def list_files(root: Path) -> list[str]:
    """Files in the working tree that .gitignore does not exclude, relative to root."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    names = {name for name in out.decode().split("\0") if name}
    # tracked files deleted in the working tree are still listed by --cached
    return sorted(name for name in names if (root / name).is_file())


def _yaml_docs(path: Path) -> object:
    try:
        return YAML(typ="safe", pure=True).load(path.read_text(encoding="utf-8"))
    except YAMLError as e:
        raise CheckHashError(f"{path}: {e}") from None


def _role_name(entry: object, where: str) -> str:
    if isinstance(entry, str):
        name = entry
    elif isinstance(entry, dict):
        name = entry.get("role", entry.get("name"))
    else:
        name = None
    if not isinstance(name, str) or not name:
        raise CheckHashError(f"{where}: cannot read a role name from {entry!r}")
    if "{{" in name or "{%" in name:
        raise CheckHashError(f"{where}: role name {name!r} is templated and cannot be resolved")
    return name


def _included_roles(node: object, where: str) -> Iterable[str]:
    """Statically named import_role/include_role anywhere below node (tasks, blocks)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ROLE_INCLUDE_KEYS:
                if isinstance(value, str):
                    # free-form `include_role: name=foo`
                    args = dict(part.split("=", 1) for part in value.split() if "=" in part)
                    value = {"name": args.get("name", value)}
                yield _role_name(value, where)
            else:
                yield from _included_roles(value, where)
    elif isinstance(node, list):
        for item in node:
            yield from _included_roles(item, where)


def _playbook_roles(playbook: Path) -> list[str]:
    plays = _yaml_docs(playbook)
    if not isinstance(plays, list):
        raise CheckHashError(f"{playbook}: a playbook must be a list of plays")
    names = []
    for play in plays:
        if not isinstance(play, dict):
            continue
        for entry in play.get("roles") or []:
            names.append(_role_name(entry, str(playbook)))
        for key in PLAY_TASK_KEYS:
            names.extend(_included_roles(play.get(key), str(playbook)))
    return names


def _role_references(role_dir: Path) -> list[str]:
    names = []
    meta = role_dir / "meta" / "main.yml"
    if meta.is_file():
        data = _yaml_docs(meta)
        if isinstance(data, dict):
            for entry in data.get("dependencies") or []:
                names.append(_role_name(entry, str(meta)))
    for sub in ("tasks", "handlers"):
        for path in sorted((role_dir / sub).glob("**/*.y*ml")):
            names.extend(_included_roles(_yaml_docs(path), str(path)))
    return names


def resolve_roles(root: Path, playbook: str) -> list[str]:
    """Roles a playbook pulls in: named in plays, meta dependencies, static includes."""
    ansible = root / ANSIBLE_DIR
    playbook_path = ansible / f"{playbook}.yml"
    if not playbook_path.is_file():
        raise CheckHashError(f"playbook {ANSIBLE_DIR}/{playbook}.yml does not exist")

    found: set[str] = set()
    pending = _playbook_roles(playbook_path)
    while pending:
        name = pending.pop()
        if name in found:
            continue
        if "." in name:
            # a collection role (namespace.collection.role); ansible/requirements.yml covers it
            continue
        role_dir = ansible / "roles" / name
        if not role_dir.is_dir():
            raise CheckHashError(f"role {name!r} used by {playbook} not found in {role_dir}")
        found.add(name)
        pending.extend(_role_references(role_dir))
    return sorted(found)


def expand(rule: Rule, image: Image, roles: list[str]) -> list[str]:
    line = rule.template.replace("{os}", image.os).replace("{playbook}", image.playbook)
    if "{roles}" in line:
        return [line.replace("{roles}", role) for role in roles]
    return [line]


def _match(pattern: str, files: list[str]) -> set[str]:
    positive = pattern[1:] if pattern.startswith("!") else pattern
    spec = pathspec.PathSpec.from_lines("gitignore", [positive])
    return set(spec.match_files(files))


@dataclass
class ImageFiles:
    files: list[str]
    matched_rules: set[int]


def select_files(rules: list[Rule], image: Image, roles: list[str], files: list[str]) -> ImageFiles:
    """Apply the rules in order, gitignore style: the last matching line wins."""
    selected: set[str] = set()
    matched_rules: set[int] = set()
    for rule in rules:
        for pattern in expand(rule, image, roles):
            hits = _match(pattern, files)
            if hits:
                matched_rules.add(rule.line_no)
            if pattern.startswith("!"):
                selected -= hits
            else:
                selected |= hits
    return ImageFiles(sorted(selected), matched_rules)


def compute(root: Path, image: Image, selected: list[str]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(image.settings(), sort_keys=True).encode())
    for name in selected:
        h.update(b"\0" + name.encode() + b"\0")
        h.update(hashlib.sha256((root / name).read_bytes()).digest())
    return "sha256:" + h.hexdigest()


@dataclass
class Result:
    hashes: dict[str, str]
    errors: dict[str, str]
    unmatched: list[Rule]
    files: dict[str, list[str]]


def compute_all(catalog: Catalog, images: list[Image] | None = None) -> Result:
    """CHECK_HASH for each image, per-image errors, and rules that matched nothing at all.

    Unmatched rules are only judged over the whole catalog, so pass images=None for that check.
    """
    root = catalog.root
    rules = read_rules(root)
    files = list_files(root)
    targets = images if images is not None else catalog.ordered()
    result = Result(hashes={}, errors={}, unmatched=[], files={})
    matched: set[int] = set()
    for image in targets:
        try:
            roles = resolve_roles(root, image.playbook)
        except CheckHashError as e:
            result.errors[image.name] = str(e)
            continue
        picked = select_files(rules, image, roles, files)
        matched |= picked.matched_rules
        result.files[image.name] = picked.files
        result.hashes[image.name] = compute(root, image, picked.files)
    if images is None:
        result.unmatched = [rule for rule in rules if rule.line_no not in matched]
    return result


def for_image(catalog: Catalog, image: Image) -> str:
    result = compute_all(catalog, [image])
    if image.name in result.errors:
        raise CheckHashError(result.errors[image.name])
    return result.hashes[image.name]
