#!/usr/bin/env python3
"""Install the kernel build toolchain. Run in a Fedora build qube, not dom0."""

import argparse

import _common as c

PACKAGES = [
    "gcc", "gcc-c++", "make", "bison", "flex", "bc",
    "elfutils-libelf-devel", "openssl", "openssl-devel",
    "dwarves",              # pahole; without it CONFIG_DEBUG_INFO_BTF fails late
    "rpm-build", "rsync", "perl", "python3",
    "ncurses-devel", "gcc-plugin-devel", "libuuid-devel",
    "xz", "zstd", "cpio", "kmod",
    # needed by package_vm_kernel.py
    "qubes-kernel-vm-support", "dracut", "busybox", "e2fsprogs",
]

# Only when the tree enables CONFIG_RUST, which Fedora does not by default.
RUST_PACKAGES = ["rust", "rust-src", "bindgen-cli", "rustfmt"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--with-rust", action="store_true",
                    help="also install the Rust toolchain (for CONFIG_RUST=y trees)")
    args = ap.parse_args()

    c.require_vm("build_deps.py")

    packages = PACKAGES + (RUST_PACKAGES if args.with_rust else [])
    c.info(f"Installing {len(packages)} packages")
    # dnf is the package manager; there is no Python API for it worth binding to
    # here, so we invoke it as a subprocess with an argument list (no shell).
    c.run(["sudo", "dnf", "install", "-y", *packages])
    c.info("Done.")


if __name__ == "__main__":
    main()
