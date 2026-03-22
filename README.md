# Packer Image Builds for Homelab

A Debian Linux image building and distribution system for the CloudyHome homelab infrastructure. It uses [HashiCorp Packer](https://www.packer.io/) to create customized, reproducible Debian cloud images and publishes them to a S3 bucket.

## Objective

Build role-specific Debian VM images optimized for different workloads:

| Role | Purpose |
|------|---------|
| **debian-base** | Foundation image with basic system setup |
| **debian-container** | Optimized for container runtimes |
| **debian-kubernetes** | Kubernetes node deployment |

## How It Works

1. **Source** - Downloads the official Debian cloud image.
2. **Provision** - Boots the image with cloud-init, then runs a role-specific Ansible playbook (from [homelab-self-provisioner](https://github.com/cloudyhomelab/homelab-self-provisioner)).
3. **Clean up** - Removes build-time users, SSH keys, apt caches, and logs; zeros free space for compression.
4. **Publish** - Generates a SHA-512 checksum and JSON metadata, then uploads the QCOW2 image to S3 bucket.

CI is handled by two GitHub Actions workflows:

- **validate.yml** - Runs Packer validation and shellcheck on every push to `main`.
- **update-source-image.yml** - Checks daily for newer upstream Debian images and opens a PR when one is available.

## How to Use

### Prerequisites

- Packer (>= 1.8)
- Ansible
- QEMU / KVM
- jq, curl, git, ssh-keygen

### Build an image

```bash
# With KVM acceleration (recommended)
make debian-base-build-kvm

# Without KVM
make debian-container-build
```

Each target follows the pattern `<os>-<role>-<action>`:

```bash
make debian-base-fmt            # Format Packer files
make debian-base-validate       # Validate configuration
make debian-base-build          # Build image
make debian-base-build-kvm      # Build with KVM
make debian-base-test           # Boot the image in QEMU for testing
```

### Test a built image

```bash
make debian-base-test
```

This downloads the latest matching image from S3 bucket, verifies its checksum, and boots it in QEMU with a serial console.

### Output

Built images are written to `workspace/build/` as QCOW2 files (e.g. `debian-base-20260322-1234.qcow2`) alongside their checksums and metadata.

After publishing, a cumulative `metadata_all.json` file is maintained in the S3 bucket. It serves as a catalog of all built images, storing each image's name, version, build timestamp, SHA-512 checksum, and source reference. Downstream systems use this file to discover available image versions and verify integrity before downloading.
