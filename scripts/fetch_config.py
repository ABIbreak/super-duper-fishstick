#!/usr/bin/env python3
"""Fetch kernel source, seed a Fedora-derived .config, merge the Qubes
fragment, and verify that every requested symbol actually survived.

This reproduces what qubes-linux-kernel's get-fedora-latest-config and
gen-config do. The verification step is the point: merge_config.sh silently
accepts symbols whose dependencies are unmet, `make alldefconfig` then drops
them, and nothing complains until the qube fails to boot.
"""

import argparse
import gzip
import lzma
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import _common as c

CDN = "https://cdn.kernel.org/pub/linux/kernel"
CONFIG_LINE = re.compile(r"^(?:# )?(CONFIG_[A-Za-z0-9_]+)[= ]")


def download(url, dest):
    """Stream a URL to a file with a progress line."""
    import urllib.request  # respects http_proxy/https_proxy from the environment

    c.info(f"Downloading {url}")
    with urllib.request.urlopen(url) as response, open(dest, "wb") as out_file:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 20):
            out_file.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r    {done / 1e6:.0f}/{total / 1e6:.0f} MB", end="", flush=True)
        if total:
            print()


def fetch_source(version, srcdir):
    if srcdir.is_dir():
        c.info(f"Using existing source tree {srcdir}")
        return

    series = f"v{version.split('.')[0]}.x"
    workdir = srcdir.parent
    tar_xz = workdir / f"linux-{version}.tar.xz"
    sign = workdir / f"linux-{version}.tar.sign"
    tar = workdir / f"linux-{version}.tar"

    if not tar_xz.exists():
        download(f"{CDN}/{series}/linux-{version}.tar.xz", tar_xz)
    if not sign.exists():
        download(f"{CDN}/{series}/linux-{version}.tar.sign", sign)

    # The detached signature covers the uncompressed tar, so decompress first.
    c.info("Decompressing")
    with lzma.open(tar_xz) as src, open(tar, "wb") as dst:
        shutil.copyfileobj(src, dst, length=1 << 20)

    # gpg is an external tool with no adequate stdlib equivalent; python-gnupg
    # is not in a default Fedora install, so shell out to it.
    c.info("Verifying signature")
    if subprocess.run(["gpg", "--verify", str(sign), str(tar)], check=False).returncode:
        tar.unlink(missing_ok=True)
        c.die(
            "Signature verification FAILED or the signing key is missing.\n"
            "    Import the keys and re-run:\n"
            "      gpg --locate-keys torvalds@kernel.org gregkh@kernel.org"
        )
    c.info("Signature OK")

    c.info(f"Extracting to {srcdir}")
    with tarfile.open(tar) as archive:
        # filter='data' (Python 3.12+) rejects absolute paths, traversal and
        # special files. Harmless belt-and-braces on an already-verified tarball.
        try:
            archive.extractall(workdir, filter="data")
        except TypeError:
            archive.extractall(workdir)
    tar.unlink()


def seed_config(srcdir):
    """Start from a Fedora config, by preference the running Qubes kernel's."""
    dest = srcdir / ".config"

    running = Path("/proc/config.gz")
    if running.exists():
        # Best case: Fedora's config with the Qubes fragment already merged,
        # straight out of the kernel this qube is running.
        dest.write_bytes(gzip.decompress(running.read_bytes()))
        return "/proc/config.gz (running Qubes kernel)"

    candidates = sorted(Path("/boot").glob("config-*")) + \
        sorted(Path("/lib/modules").glob("*/config"))
    if candidates:
        newest = candidates[-1]
        shutil.copy(newest, dest)
        return str(newest)

    c.die("No Fedora config found. Install kernel-core, or enable CONFIG_IKCONFIG_PROC.")


def strip_comments(fragment):
    """merge_config.sh treats '#' lines as 'is not set' directives, so the
    fragment's '##' prose comments must go before it sees the file."""
    return "".join(
        line for line in fragment.read_text().splitlines(keepends=True)
        if not line.startswith("##")
    )


def verify(fragment_text, config_path):
    """Report every symbol the fragment asked for that is not in the result."""
    wanted = {}
    for line in fragment_text.splitlines():
        match = CONFIG_LINE.match(line)
        if match:
            wanted[match.group(1)] = line.strip()

    actual = {}
    for line in config_path.read_text().splitlines():
        match = CONFIG_LINE.match(line)
        if match:
            actual[match.group(1)] = line.strip()

    lost = [
        (symbol, want, actual.get(symbol, "<nothing>"))
        for symbol, want in wanted.items()
        if actual.get(symbol) != want
    ]
    for symbol, want, got in lost:
        print(f"    LOST {symbol:<44} wanted {want:<30} got {got}")
    return len(wanted), lost


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", help="upstream kernel version, e.g. 6.12.63")
    ap.add_argument("srcdir", nargs="?", help="where to unpack (default ./linux-<version>)")
    ap.add_argument("--localversion", default="-qubes-test",
                    help="CONFIG_LOCALVERSION suffix (default: %(default)s)")
    ap.add_argument("--fragment", help="kconfig fragment (default: config/qubes-vm.config)")
    args = ap.parse_args()

    c.require_vm("fetch_config.py")

    repo = Path(__file__).resolve().parent.parent
    fragment = Path(args.fragment) if args.fragment else repo / "config" / "qubes-vm.config"
    if not fragment.is_file():
        c.die(f"Fragment not found: {fragment}")

    srcdir = Path(args.srcdir).resolve() if args.srcdir \
        else Path.cwd() / f"linux-{args.version}"

    fetch_source(args.version, srcdir)

    c.info("Seeding .config")
    print(f"    from {seed_config(srcdir)}")
    c.run(["make", "olddefconfig"], cwd=srcdir, quiet=True)

    c.info(f"Merging {fragment}")
    fragment_text = strip_comments(fragment)
    with tempfile.NamedTemporaryFile("w", suffix=".config", delete=False) as tmp:
        tmp.write(fragment_text)
        tmp_path = tmp.name
    try:
        # merge_config.sh and scripts/config ship with the kernel; reimplementing
        # kconfig dependency resolution in Python would be strictly worse.
        c.run(["./scripts/kconfig/merge_config.sh", "-m", ".config", tmp_path],
              cwd=srcdir, quiet=True)
        c.run(["make", "KCONFIG_ALLCONFIG=.config", "alldefconfig"], cwd=srcdir, quiet=True)
        c.run(["./scripts/config", "--set-str", "CONFIG_LOCALVERSION", args.localversion],
              cwd=srcdir, quiet=True)
        c.run(["./scripts/config", "--disable", "CONFIG_LOCALVERSION_AUTO"],
              cwd=srcdir, quiet=True)
        c.run(["make", "olddefconfig"], cwd=srcdir, quiet=True)

        c.info("Verifying the fragment took effect")
        checked, lost = verify(fragment_text, srcdir / ".config")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if lost:
        c.die(f"{len(lost)} of {checked} settings did not survive. "
              "Fix their dependencies before building.")

    print(f"    {checked} symbols checked, all present")
    c.info(f"OK. kernelrelease = {c.out(['make', '-s', 'kernelrelease'], cwd=srcdir)}")
    print(f"    next: scripts/build.py {srcdir}")


if __name__ == "__main__":
    sys.exit(main())
