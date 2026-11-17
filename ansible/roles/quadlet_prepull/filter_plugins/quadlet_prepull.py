"""Filters of the quadlet_prepull role."""

from __future__ import annotations

import base64
import os

from ansible.errors import AnsibleFilterError


def _repository(reference: str) -> str:
    name = reference.split("@", 1)[0]
    host, _, path = name.partition("/")
    # a registry host has a dot or a port; anything else is a short name the policy cannot scope
    if not path or not ("." in host or ":" in host or host == "localhost"):
        raise AnsibleFilterError(f"{reference} is not a fully qualified image reference")
    last = path.rsplit("/", 1)
    last[-1] = last[-1].split(":", 1)[0]
    return f"{host}/{'/'.join(last)}"


def image_repositories(slurped: list[dict]) -> list[str]:
    """The registry repositories that Quadlet .image files pull from, given the results of a
    looped slurp over them; sorted and without duplicates."""
    repositories = set()
    for result in slurped:
        name = os.path.basename(result["item"]["path"])
        content = base64.b64decode(result["content"]).decode()
        images = [
            line.split("=", 1)[1].strip()
            for line in content.splitlines()
            if line.strip().startswith("Image=")
        ]
        if len(images) != 1:
            raise AnsibleFilterError(
                f"{name} must have exactly one Image= line, found {len(images)}"
            )
        repositories.add(_repository(images[0]))
    return sorted(repositories)


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {"image_repositories": image_repositories}
