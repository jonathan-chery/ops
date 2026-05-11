"""Rootfs image builder for Firecracker microVMs."""

import subprocess
from pathlib import Path
from typing import Optional

from ops.models.blueprint import AppBlueprint
from ops.utils.safe_shell import quote


class RootfsBuilder:
    """Creates ext4 rootfs images for Firecracker microVMs.

    Supports two packaging modes:
    1. debootstrap — create a minimal Debian/Ubuntu rootfs from scratch.
    2. pre-built — verify that an existing image path is valid.
    """

    def __init__(
        self, size_mb: int = 512, output_path: str = "/var/lib/firecracker/rootfs.ext4"
    ):
        self.size_mb = size_mb
        self.output_path = Path(output_path)
        self.loop_device: Optional[str] = None

    def build(self, blueprint: AppBlueprint) -> str:
        """Build or verify the rootfs and return its absolute path."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.output_path.exists():
            return str(self.output_path)

        self._create_blank_image()
        self._format_ext4()
        self._mount_and_populate(blueprint)
        return str(self.output_path)

    def _create_blank_image(self) -> None:
        subprocess.run(
            [
                "dd",
                "if=/dev/zero",
                f"of={self.output_path}",
                "bs=1M",
                f"count={self.size_mb}",
            ],
            check=True,
        )

    def _format_ext4(self) -> None:
        subprocess.run(["mkfs.ext4", "-F", str(self.output_path)], check=True)

    def _mount_and_populate(self, blueprint: AppBlueprint) -> None:
        mount_point = Path("/tmp/ops_rootfs_build")
        mount_point.mkdir(parents=True, exist_ok=True)

        # Find free loop device
        result = subprocess.run(
            ["losetup", "-f"], capture_output=True, text=True, check=True
        )
        loop = result.stdout.strip()
        self.loop_device = loop

        subprocess.run(["losetup", loop, str(self.output_path)], check=True)
        subprocess.run(["mount", loop, str(mount_point)], check=True)

        try:
            # Install base system via debootstrap
            subprocess.run(
                [
                    "debootstrap",
                    "--variant=minbase",
                    "noble",
                    str(mount_point),
                    "http://archive.ubuntu.com/ubuntu",
                ],
                check=True,
            )

            # Install required packages
            packages = blueprint.dependencies.get("packages", [])
            if packages:
                pkg_str = " ".join(quote(p) for p in packages)
                subprocess.run(
                    f"chroot {quote(str(mount_point))} apt-get update -y && "
                    f"chroot {quote(str(mount_point))} apt-get install -y {pkg_str}",
                    shell=True,
                    check=True,
                )

            # Install an init system
            subprocess.run(
                f"chroot {quote(str(mount_point))} apt-get install -y systemd systemd-sysv",
                shell=True,
                check=True,
            )

            # Enable getty on serial console (hvc0 for Firecracker)
            subprocess.run(
                f"chroot {quote(str(mount_point))} systemctl enable serial-getty@hvc0.service",
                shell=True,
                check=True,
            )
        finally:
            subprocess.run(["umount", str(mount_point)], check=False)
            if self.loop_device:
                subprocess.run(["losetup", "-d", self.loop_device], check=False)
            self.loop_device = None

    def __del__(self):
        if self.loop_device:
            subprocess.run(["losetup", "-d", self.loop_device], check=False)
