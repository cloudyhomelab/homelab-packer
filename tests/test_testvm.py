from pathlib import Path

import pytest

from imagectl.testvm import qemu_command


def nic(network: bool) -> str:
    cmd = qemu_command(Path("overlay.qcow2"), Path("seed.img"), "tcg", network)
    return cmd[cmd.index("-nic") + 1]


@pytest.mark.parametrize(
    ("network", "expected"),
    [(True, "user,model=virtio"), (False, "user,model=virtio,restrict=on")],
)
def test_network_option_sets_the_nic(network: bool, expected: str):
    assert nic(network) == expected
