# homelab images

Builds the homelab VM images (Debian and Fedora) with Packer and Ansible, and publishes them to S3.

The images are for ephemeral VMs: a VM is replaced from a newer image, never upgraded in place. A
change to an image does not need to stay compatible with earlier builds or clean up after them.

- `images.yml`: global config and the image tree. Every image builds on its parent's latest
  published build; top-level images build on an upstream cloud image.
- `upstream.yml`: the upstream cloud images and their pinned versions.
- `.check_hash`: the files that feed each image's `CHECK_HASH`; a change to them rebuilds the image.
- `upstream/<os>/`: the Packer template, build-time cloud-init, guest scripts and test seed per OS.
- `ansible/`: the playbooks (`packer-<os>-<image>.yml`) and roles.
- `src/imagectl/`: the driver.

## Host tools

- [uv](https://docs.astral.sh/uv/) (installs Python, Ansible and the driver's dependencies)
- Packer, in the range the templates' `required_version` allows
- QEMU (`qemu-system-x86_64`, `qemu-img`), with `/dev/kvm` for acceleration
- `ssh-keygen` (OpenSSH), `shellcheck`, `xorriso`, `git`

## Usage

Run from the project root:

```bash
uv run imagectl list                          # the image tree
uv run imagectl validate [IMAGE...]           # templates, scripts, driver, playbooks
uv run imagectl plan                          # images that are due, and why
uv run imagectl build --now --keep IMAGE      # local build, never published
uv run imagectl test IMAGE --local            # boot the newest kept local build
uv run imagectl test IMAGE                    # boot the latest published build
uv run imagectl upstream [UPSTREAM...]        # newer upstream releases, writes nothing
uv run pytest
```

`build --now` of a child needs its parent published; it builds on the parent's `latest.json`.

## Adding an image

Add its name under its parent's `children:` in `images.yml` and write
`ansible/packer-<os>-<name>.yml`. Settings not given come from `defaults`, never from the parent.

## Publishing

CI is the only publisher:

- `refresh-packer-images` runs `imagectl build --plan` on every push to `main` and hourly. It builds
  what is due (inputs changed, source changed, or aged out) and the descendants of anything it
  rebuilds, parents first, then publishes each build and prunes old ones.
- `refresh-upstream` runs `imagectl upstream --update` daily and opens a pull request when a pin
  moves. The pull request is opened by the cloudyhome bot GitHub App (secrets
  `CLOUDYHOME_BOT_CLIENT_ID` and `CLOUDYHOME_BOT_PRIVATE_KEY`), so `validate` runs on it.
- `validate` runs on pull requests and shows `imagectl plan` in the job summary.

The publish credentials are the `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` secrets of the
`publish` environment. The bucket and its anonymous read policy are set up outside the driver.

Each build lands at `<bucket>/<os>/<image>/<build_version>/` with the qcow2, its `.sha512` and
`metadata.json`; `<bucket>/<os>/<image>/latest.json` is a copy of the newest `metadata.json`.
Inside the image, `/etc/os-image-metadata` holds the same facts.

## License

AGPL-3.0, see `LICENSE`. `ansible/` was imported from homelab-self-provisioner and keeps its own
`ansible/LICENSE`.
