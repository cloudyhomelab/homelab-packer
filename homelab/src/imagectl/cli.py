"""imagectl: build, publish and test the homelab VM images."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import build, check_hash, packer, preflight, publish, testvm, upstream
from .catalog import IMAGES_FILE, Catalog, CatalogError, Image, Source, load


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def select_images(catalog: Catalog, names: list[str]) -> list[Image]:
    if not names:
        return catalog.ordered()
    unknown = [n for n in names if n not in catalog.images]
    if unknown:
        raise CatalogError([f"unknown image {n!r}" for n in unknown])
    return [i for i in catalog.ordered() if i.name in names]


def table(rows: list[list[str]]) -> str:
    widths = [max(len(row[c]) for row in rows) for c in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)) for row in rows]
    return "\n".join(line.rstrip() for line in lines)


def cmd_list(catalog: Catalog, args: argparse.Namespace) -> int:
    rows = [["IMAGE", "PLAYBOOK", "DISK", "MEMORY", "CPUS", "SOURCE"]]
    for image in catalog.ordered():
        if image.parent is None:
            source = f"{image.upstream} {catalog.upstream_source(image).url}"
        else:
            source = image.parent
        rows.append(
            [
                "  " * image.depth + image.name,
                image.playbook,
                image.disk_size,
                str(image.memory),
                str(image.cpus),
                source,
            ]
        )
    print(table(rows))
    return 0


def validate_source(catalog: Catalog, image: Image) -> Source:
    """What packer validate gets as the source: the pin, or the parent's folder for children.

    validate never reads latest.json, so a child is validated without a published parent.
    """
    if image.parent is None:
        return catalog.upstream_source(image)
    parent = catalog.get(image.parent)
    return Source(parent.name, catalog.public_url(catalog.image_prefix(parent) + "/"), "none")


def run_check(label: str, cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> bool:
    print(f"--- {label}", flush=True)
    try:
        ok = subprocess.run(cmd, cwd=cwd, env=env).returncode == 0
    except FileNotFoundError:
        print(f"{cmd[0]} not found")
        ok = False
    print(f"{label}: {'ok' if ok else 'FAILED'}", flush=True)
    return ok


def cmd_validate(catalog: Catalog, args: argparse.Namespace) -> int:
    root = catalog.root
    targets = select_images(catalog, args.images)
    failures: dict[str, list[str]] = {i.name: [] for i in targets}
    global_ok = True

    collections = build.install_collections(root)
    env = packer.environment(root, build.packer_cache_dir(root), collections)
    build.packer_init(root, targets, env)

    if (root / "upstream").is_dir():
        global_ok &= run_check(
            "packer fmt", ["packer", "fmt", "-check", "-diff", "-recursive", "upstream"], root
        )

    hashes = check_hash.compute_all(catalog)
    for rule in hashes.unmatched:
        print(f".check_hash:{rule.line_no}: {rule.template!r} matches no file for any image")
        global_ok = False

    git = packer.git_info(root)
    clock = packer.Clock.now()
    with tempfile.TemporaryDirectory(prefix="imagectl-validate-") as tmp:
        ssh = packer.generate_ssh(Path(tmp))
        for image in targets:
            missing = packer.missing_files(root, image)
            if missing:
                failures[image.name].append("missing " + ", ".join(missing))
                continue
            if image.name in hashes.errors:
                failures[image.name].append(f"CHECK_HASH: {hashes.errors[image.name]}")
            inputs = packer.BuildInputs(
                image=image,
                source=validate_source(catalog, image),
                clock=clock,
                check_hash=hashes.hashes.get(image.name, "unknown"),
                git=git,
                output_directory=(build.build_root(root) / image.name / "validate").resolve(),
                accelerator="none",
                ssh=ssh,
            )
            print(f"--- packer validate {image.name}", flush=True)
            result = subprocess.run(
                packer.validate_command(inputs), cwd=root, env=env, capture_output=True, text=True
            )
            if result.returncode != 0:
                print(result.stdout + result.stderr, end="")
                failures[image.name].append("packer validate failed")

    for os_name in sorted({i.os for i in targets}):
        scripts = sorted((root / "upstream" / os_name / "scripts").glob("*.sh"))
        if scripts:
            global_ok &= run_check(
                f"shellcheck {os_name}",
                ["shellcheck", *[str(s.relative_to(root)) for s in scripts]],
                root,
            )

    global_ok &= run_check("ruff check", ["ruff", "check", "."], root)
    global_ok &= run_check("ruff format", ["ruff", "format", "--check", "--quiet", "."], root)
    ansible = root / packer.ANSIBLE_DIR
    if ansible.is_dir():
        global_ok &= run_check(
            "ansible-lint", ["ansible-lint", "--offline", "-q"], ansible, env=env
        )

    print()
    rows = [["IMAGE", "RESULT"]]
    for image in targets:
        problems = failures[image.name]
        rows.append([image.name, "ok" if not problems else "FAILED: " + "; ".join(problems)])
    print(table(rows))
    if not global_ok:
        print("\nrepository checks failed, see above")
    return 0 if global_ok and not any(failures.values()) else 1


def print_plan(due: list[preflight.Due]) -> None:
    if not due:
        print("nothing is due")
        return
    print(table([["IMAGE", "REASON"], *[[d.image, d.reason] for d in due]]))


def hash_errors(result: check_hash.Result) -> None:
    for name, error in result.errors.items():
        print(f"{name}: cannot compute CHECK_HASH: {error}", file=sys.stderr)


def cmd_plan(catalog: Catalog, args: argparse.Namespace) -> int:
    hashes = check_hash.compute_all(catalog)
    due, _ = preflight.plan(
        catalog,
        dict(hashes.hashes),
        lambda image: preflight.fetch_latest(catalog, image),
        datetime.now(UTC),
    )
    print_plan(due)
    hash_errors(hashes)
    return 1 if hashes.errors else 0


def cmd_build(catalog: Catalog, args: argparse.Namespace) -> int:
    root = catalog.root
    image = catalog.get(args.image)
    env = packer.environment(root, build.packer_cache_dir(root), build.install_collections(root))
    build.packer_init(root, [image], env)
    try:
        build_dir = build.run_build(
            catalog,
            image,
            lambda img: preflight.fetch_latest(catalog, img),
            build.BuildOptions(verbose=args.verbose, keep=args.keep),
        )
    except build.BuildError as e:
        return fail(str(e))
    if args.keep:
        print(f"{image.name}: built, kept in {build_dir}")
    else:
        print(f"{image.name}: built")
    return 0


def cmd_publish(catalog: Catalog, args: argparse.Namespace) -> int:
    root = catalog.root
    jobs = args.jobs if args.jobs is not None else 2
    if jobs < 1:
        return fail("-j must be at least 1")
    store = publish.Store(catalog, publish.s3_client(catalog))

    hashes = check_hash.compute_all(catalog)
    due, latest = preflight.plan(catalog, dict(hashes.hashes), store.latest, datetime.now(UTC))
    print_plan(due)
    hash_errors(hashes)

    removed = build.prune_packer_cache(
        build.packer_cache_dir(root), build.current_checksums(catalog, latest)
    )
    for name in removed:
        print(f"packer cache: removed {name}")
    if not due:
        return 1 if hashes.errors else 0

    due_images = [catalog.get(d.image) for d in due]
    env = packer.environment(root, build.packer_cache_dir(root), build.install_collections(root))
    build.packer_init(root, due_images, env)

    def publisher(result: publish.Build, image_path: Path) -> None:
        meta = publish.publish(catalog, store, result, image_path)
        print(f"{result.image.name}: published {meta['IMAGE_URL']}", flush=True)
        for key in publish.prune(catalog, store, result.image):
            print(f"{result.image.name}: pruned {key}", flush=True)

    def build_one(image: Image) -> None:
        print(f"{image.name}: building", flush=True)
        build.run_build(
            catalog, image, store.latest, build.BuildOptions(verbose=args.verbose), publisher
        )

    outcomes = build.run_scheduled(catalog, [d.image for d in due], build_one, jobs)
    print()
    rows = [["IMAGE", "RESULT", "DETAIL"]]
    rows += [[name, o.status, o.detail] for name, o in outcomes.items()]
    print(table(rows))
    failed = any(o.status != "ok" for o in outcomes.values())
    return 1 if failed or hashes.errors else 0


def cmd_upstream(args: argparse.Namespace) -> int:
    # reads and writes upstream.yml only; images.yml is never opened
    return upstream.check(Path.cwd(), args.upstreams, args.update)


def cmd_test(catalog: Catalog, args: argparse.Namespace) -> int:
    try:
        return testvm.run(catalog, catalog.get(args.image), args.local)
    except testvm.TestVmError as e:
        return fail(str(e))


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imagectl",
        description=__doc__,
        epilog="Run `imagectl COMMAND -h` for a command's arguments.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="stream packer output while building"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add(name: str, summary: str, description: str, epilog: str) -> argparse.ArgumentParser:
        return sub.add_parser(
            name,
            help=summary,
            description=description,
            epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

    add(
        "list",
        "print the image tree",
        "Print every image in images.yml as a tree, children under their parent.",
        "example:\n  imagectl list",
    )

    p = add(
        "validate",
        "validate templates, scripts, driver and playbooks",
        "Check the Packer templates, scripts, .check_hash rules and Ansible playbooks.\n"
        "Reads no latest.json, so a child validates without a published parent.",
        "examples:\n  imagectl validate\n  imagectl validate debian-base debian-container",
    )
    p.add_argument("images", nargs="*", metavar="IMAGE", help="image to validate (default: all)")

    add(
        "plan",
        "list the images that are due, with reasons",
        "List the images publish would build and why: inputs changed, source changed,\n"
        "aged out, or parent due. Reads latest.json anonymously; needs no credentials.",
        "example:\n  imagectl plan",
    )

    p = add(
        "build",
        "build one image locally, never published",
        "Build IMAGE locally, whether or not it is due. Never publishes. A child builds on\n"
        "its parent's published latest.json, so the parent has to be published first.",
        "examples:\n  imagectl build debian-base\n  imagectl -v build --keep debian-container",
    )
    p.add_argument("image", metavar="IMAGE", help="the image to build")
    p.add_argument(
        "--keep",
        action="store_true",
        help="keep the build dir under build/IMAGE/ for `imagectl test --local`",
    )

    p = add(
        "publish",
        "build and publish everything due (CI)",
        "Build every image `imagectl plan` lists, parents first, then publish each build\n"
        "and prune old ones. Needs S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY.",
        "examples:\n  imagectl publish\n  imagectl -v publish -j 4",
    )
    p.add_argument("-j", "--jobs", type=int, metavar="N", help="parallel builds (default 2)")

    p = add(
        "upstream",
        "check upstreams for newer releases",
        "Check each upstream in upstream.yml for a newer release. Writes nothing\n"
        "unless --update is given.",
        "examples:\n  imagectl upstream\n  imagectl upstream --update debian-cloud",
    )
    p.add_argument(
        "upstreams", nargs="*", metavar="UPSTREAM", help="upstream to check (default: all)"
    )
    p.add_argument(
        "--update", action="store_true", help="write newer versions and checksums to upstream.yml"
    )

    p = add(
        "test",
        "boot an image in QEMU",
        "Boot an image in QEMU with the test cloud-init seed from upstream/<os>/test/.",
        "examples:\n  imagectl test debian-base\n  imagectl test debian-base --local",
    )
    p.add_argument("image", metavar="IMAGE", help="the image to boot")
    p.add_argument(
        "--local",
        action="store_true",
        help="boot the newest kept local build instead of downloading the published one",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    root = Path.cwd()
    if not (root / IMAGES_FILE).is_file():
        return fail(f"run imagectl from the project root ({IMAGES_FILE} not found in {root})")
    try:
        if args.command == "upstream":
            return cmd_upstream(args)
        catalog = load(root)
        if args.command == "list":
            return cmd_list(catalog, args)
        if args.command == "validate":
            return cmd_validate(catalog, args)
        if args.command == "plan":
            return cmd_plan(catalog, args)
        if args.command == "build":
            return cmd_build(catalog, args)
        if args.command == "publish":
            return cmd_publish(catalog, args)
        if args.command == "test":
            return cmd_test(catalog, args)
    except CatalogError as e:
        for error in e.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    except (
        build.BuildError,
        publish.PublishError,
        preflight.PreflightError,
        upstream.UpstreamError,
        check_hash.CheckHashError,
    ) as e:
        return fail(str(e))
    except FileNotFoundError as e:
        if e.filename and "/" not in str(e.filename):
            return fail(f"{e.filename} not found on PATH (see README for host tools)")
        raise
    except subprocess.CalledProcessError as e:
        return fail(f"{' '.join(map(str, e.cmd[:3]))} failed with exit code {e.returncode}")
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
