"""Filters of the grafana_plugins role."""

from __future__ import annotations

from ansible.errors import AnsibleFilterError


def quadlet_image(content: str) -> str:
    """The image reference of a Quadlet .image file."""
    images = [
        line.split("=", 1)[1].strip()
        for line in content.splitlines()
        if line.strip().startswith("Image=")
    ]
    if len(images) != 1:
        raise AnsibleFilterError(f"expected exactly one Image= line, found {len(images)}")
    return images[0]


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {"quadlet_image": quadlet_image}
