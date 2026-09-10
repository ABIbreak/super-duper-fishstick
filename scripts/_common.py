"""Shared helpers for the kernel build scripts.

Imported by the sibling scripts; Python puts a script's own directory on
sys.path, so a plain ``import _common`` works when they are run directly.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Qubes marks a VM with this file; dom0 has /etc/qubes-release and no marker.
_MARKER_VM = "/usr/share/qubes/marker-vm"
_QUBES_RELEASE = "/etc/qubes-release"


def info(msg):
    print(f"==> {msg}", flush=True)


def warn(msg):
    print(f"!!! {msg}", file=sys.stderr, flush=True)


def die(msg, code=1):
    warn(msg)
    sys.exit(code)


def is_vm():
    return os.path.exists(_MARKER_VM)


def is_dom0():
    return os.path.exists(_QUBES_RELEASE) and not is_vm()


def require_vm(what="This"):
    if is_dom0():
        die(f"{what} must not run in dom0. Build in a qube.")


def require_dom0(what="This"):
    if is_vm():
        die(f"{what} must run in dom0, not in a qube.")


# sudo's secure_path includes the sbin directories, but a regular user's PATH
# on Fedora may not. qubes-prepare-vm-kernel installs to /usr/sbin, so a plain
# which() would report it missing for exactly the users who can still run it.
_SBIN_DIRS = ("/usr/local/sbin", "/usr/sbin", "/sbin")


def have(tool):
    if shutil.which(tool) is not None:
        return True
    return any(os.access(os.path.join(d, tool), os.X_OK) for d in _SBIN_DIRS)


def run(cmd, *, cwd=None, check=True, quiet=False, capture=False, env=None):
    """Run a command, echoing it unless quiet. Returns stdout when capture."""
    if not quiet:
        print("    $ " + " ".join(map(str, cmd)), flush=True)
    result = subprocess.run(
        [str(c) for c in cmd],
        cwd=cwd,
        check=False,
        env=env,
        stdout=subprocess.PIPE if capture else None,
        text=True,
    )
    if check and result.returncode != 0:
        die(f"command failed ({result.returncode}): {' '.join(map(str, cmd))}")
    return result.stdout if capture else result.returncode


def out(cmd, *, cwd=None):
    """Capture stdout of a command, stripped. Raises on failure."""
    return run(cmd, cwd=cwd, capture=True, quiet=True).strip()


def kernelrelease(srcdir):
    """The kernel's `uname -r` string, computed reliably.

    `make kernelrelease` just echoes KERNELRELEASE, which is read from a cached
    include/config/kernel.release -- and `kernelrelease` is listed in the
    Makefile's no-sync-config-targets, so nothing regenerates that file. On a
    tree that has been configured but not yet built it is stale or empty, and
    CONFIG_LOCALVERSION is missing from the answer. Regenerate it first, then
    read the file.
    """
    src = Path(srcdir)
    run(["make", "-s", "include/config/kernel.release"], cwd=src, quiet=True)
    release = (src / "include" / "config" / "kernel.release").read_text().strip()
    if not release:
        die(f"could not determine kernelrelease for {src}")
    return release


def sudo_write(path, content, mode="0644"):
    """Write a root-owned file. Content goes through a temp file so that no
    shell quoting is involved and `sudo` only ever runs `install`."""
    with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        run(["sudo", "install", "-m", mode, "-o", "root", "-g", "root", tmp_path, path])
    finally:
        os.unlink(tmp_path)
