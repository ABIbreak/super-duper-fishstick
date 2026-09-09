#!/usr/bin/env python3
"""Turn an installed kernel into a Qubes VM-kernel directory.

Runs in the build qube (path A) or in dom0 (path B) -- qubes-prepare-vm-kernel
behaves identically in both. See docs/04-running-a-qube.md.
"""

import argparse
from pathlib import Path

import _common as c

VM_KERNELS = Path("/var/lib/qubes/vm-kernels")

# Matches what the Qubes kernel package generates. xen_scrub_pages=0 is safe
# here only because the qubes-vm-simple initramfs re-enables scrubbing before
# switch_root -- which it does, since qubes-prepare-vm-kernel built it.
DEFAULT_KERNELOPTS = (
    "root=/dev/mapper/dmroot ro nomodeset console=hvc0 "
    "rd_NO_PLYMOUTH rd.plymouth.enable=0 plymouth.enable=0 "
    "clocksource=tsc xen_privcmd.unrestricted xen_scrub_pages=0\n"
)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kver", help="kernel version exactly as `uname -r` reports it")
    ap.add_argument("name", nargs="?", help="short name for qvm-prefs (default: kver)")
    ap.add_argument("--no-kernelopts", action="store_true",
                    help="do not write default-kernelopts-common.txt")
    args = ap.parse_args()

    kver = args.kver
    name = args.name or kver

    if not c.have("qubes-prepare-vm-kernel"):
        c.die("qubes-prepare-vm-kernel not found. Install qubes-kernel-vm-support.")
    if not Path(f"/lib/modules/{kver}").is_dir():
        c.die(f"/lib/modules/{kver} missing -- run build.py first")
    if not Path(f"/boot/vmlinuz-{kver}").is_file():
        c.die(f"/boot/vmlinuz-{kver} missing -- run build.py first")

    # --include-devel packs /usr/src/kernels/<kver> into modules.img so DKMS can
    # build against this kernel inside qubes. Only possible with headers present.
    extra = []
    if Path(f"/usr/src/kernels/{kver}").is_dir():
        extra = ["--include-devel"]
        c.info("Including kernel headers in modules.img")

    c.info(f"Packaging {kver} as '{name}'")
    c.run(["sudo", "qubes-prepare-vm-kernel", *extra, kver, name])

    target = VM_KERNELS / name

    if not args.no_kernelopts and not (target / "default-kernelopts-common.txt").exists():
        c.info("Writing default-kernelopts-common.txt")
        c.sudo_write(str(target / "default-kernelopts-common.txt"), DEFAULT_KERNELOPTS)

    # Advertise hotplug ballooning only if the kernel actually supports it:
    # Qubes checks for this marker to decide whether it can balloon the qube.
    config = Path(f"/boot/config-{kver}")
    if config.is_file() and "CONFIG_XEN_BALLOON_MEMORY_HOTPLUG=y" in config.read_text():
        c.run(["sudo", "touch", str(target / "memory-hotplug-supported")])
        c.info("Marked memory-hotplug-supported")

    print()
    c.run(["sudo", "ls", "-l", str(target)])
    print()
    if c.is_dom0():
        c.info(f"Done. Point a qube at it:  qvm-prefs <qube> kernel {name}")
    else:
        import socket
        c.info("Done. From dom0, import it with:")
        print(f"    scripts/dom0_install_vm_kernel.py {socket.gethostname()} {name}")


if __name__ == "__main__":
    main()
