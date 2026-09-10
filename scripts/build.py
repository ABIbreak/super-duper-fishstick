#!/usr/bin/env python3
"""Compile the kernel and install it into this build qube's /boot and
/lib/modules, which is where qubes-prepare-vm-kernel reads from.

The image is installed by hand rather than with `make install`, so that
Fedora's kernel-install (BLS entries, host initramfs) stays out of it. Nothing
in a qube boots from /boot when the kernel comes from dom0.
"""

import argparse
import os
from pathlib import Path

import _common as c


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srcdir", nargs="?", default=".", help="kernel source tree")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count(),
                    help="parallel make jobs (default: all CPUs)")
    args = ap.parse_args()

    c.require_vm("build.py")

    src = Path(args.srcdir).resolve()
    if not (src / ".config").is_file():
        c.die(f"No .config in {src} -- run fetch_config.py first")

    # `make` is the kernel's build system; driving it as a subprocess is the
    # only sane option. kernelrelease() rather than `make -s kernelrelease`:
    # the latter returns a stale value on a not-yet-built tree, which would put
    # the image in /boot under a different version than modules_install uses.
    kver = c.kernelrelease(src)

    c.info(f"Building {kver} with -j{args.jobs}")
    c.run(["make", f"-j{args.jobs}"], cwd=src)

    c.info("Installing modules")
    c.run(["sudo", "make", f"-j{args.jobs}", "modules_install"], cwd=src)

    c.info(f"Installing image as /boot/vmlinuz-{kver}")
    for source, dest in [
        ("arch/x86/boot/bzImage", f"/boot/vmlinuz-{kver}"),
        ("System.map", f"/boot/System.map-{kver}"),
        (".config", f"/boot/config-{kver}"),
    ]:
        c.run(["sudo", "install", "-m", "0644", str(src / source), dest])

    c.info("Done.")
    print(f"    /boot/vmlinuz-{kver}")
    print(f"    /lib/modules/{kver}")
    print(f"    next: scripts/package_vm_kernel.py {kver} <short-name>")


if __name__ == "__main__":
    main()
