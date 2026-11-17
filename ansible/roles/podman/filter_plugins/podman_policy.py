"""Filters of the podman role."""

from __future__ import annotations


def podman_image_policy(repositories: list[str]) -> dict:
    """A containers-policy.json(5) document that rejects every image except pulls from the given
    registry repositories. Every other transport, the archives `podman load` reads included, falls
    to the default and is rejected."""
    accept = [{"type": "insecureAcceptAnything"}]
    return {
        "default": [{"type": "reject"}],
        "transports": {"docker": {repo: accept for repo in sorted(set(repositories))}},
    }


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {"podman_image_policy": podman_image_policy}
