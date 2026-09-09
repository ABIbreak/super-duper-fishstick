#!/usr/bin/env python3
"""Pull a VM-kernel directory from a build qube into dom0 and register it.

RUN THIS IN DOM0.

Everything in the imported directory is executed with full control over any
qube that boots it, so import only from a build qube you trust. dom0 pulls --
the source qube never gets to run anything here; it only writes to a pipe.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import _common as c

VM_KERNELS = Path("/var/lib/qubes/vm-kernels")
MIN_FREE_BYTES = 2 * 1024**3  # modules.img alone runs 300-600 MB


def qubes_using(name):
    """Names of qubes whose `kernel` property is `name`."""
    listing = c.out(["qvm-ls", "--fields", "NAME,KERNEL"])
    users = []
    for line in listing.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and fields[1] == name:
            users.append(fields[0])
    return users


def pull(source_vm, name):
    """Stream `tar c <name>` from the source qube into `tar x` under sudo.

    The string passed to qvm-run is a command line for the *remote* qube's
    shell -- that is qvm-run's interface, not a shell invocation on this side.
    """
    remote = f"cd {VM_KERNELS} && tar c {name!r}"
    producer = subprocess.Popen(
        ["qvm-run", "--pass-io", source_vm, remote], stdout=subprocess.PIPE)
    consumer = subprocess.Popen(
        ["sudo", "tar", "x", "--no-same-owner", "-C", str(VM_KERNELS)],
        stdin=producer.stdout)
    producer.stdout.close()  # so the producer sees SIGPIPE if tar x dies
    consumer_rc = consumer.wait()
    producer_rc = producer.wait()
    if producer_rc:
        c.die(f"qvm-run on '{source_vm}' failed ({producer_rc})")
    if consumer_rc:
        c.die(f"extracting into {VM_KERNELS} failed ({consumer_rc})")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source_vm", help="qube holding /var/lib/qubes/vm-kernels/<name>")
    ap.add_argument("name", help="the VM-kernel directory name")
    ap.add_argument("target", nargs="?",
                    help="optionally, a qube to point at this kernel")
    ap.add_argument("--yes", action="store_true", help="do not prompt before overwriting")
    args = ap.parse_args()

    c.require_dom0("dom0_install_vm_kernel.py")
    if not c.have("qvm-prefs"):
        c.die("qvm-prefs not found -- is this really dom0?")

    dest = VM_KERNELS / args.name

    if dest.exists():
        users = qubes_using(args.name)
        if users:
            c.die(f"Refusing: these qubes currently use kernel '{args.name}': "
                  f"{', '.join(users)}.\n    Point them elsewhere first.")
        if not args.yes:
            if input(f"{dest} exists. Overwrite? [y/N] ").strip().lower() != "y":
                sys.exit(1)

    free = shutil.disk_usage(VM_KERNELS).free
    if free < MIN_FREE_BYTES:
        c.warn(f"Only {free / 1e6:.0f} MB free in {VM_KERNELS}")

    c.info(f"Pulling '{args.name}' from {args.source_vm}")
    pull(args.source_vm, args.name)

    # Set ownership and modes here rather than trusting what came over the pipe.
    c.info("Fixing ownership and modes")
    c.run(["sudo", "chown", "-R", "root:root", str(dest)], quiet=True)
    c.run(["sudo", "chmod", "0755", str(dest)], quiet=True)
    c.run(["sudo", "find", str(dest), "-type", "f", "-exec", "chmod", "0644", "{}", "+"],
          quiet=True)

    c.run(["sudo", "ls", "-l", str(dest)])

    if not (dest / "vmlinuz").is_file():
        c.die(f"No vmlinuz in {dest} -- a qube set to this kernel will not start.")

    if args.target:
        c.info(f"Setting {args.target} kernel = {args.name}")
        c.run(["qvm-shutdown", "--wait", args.target], check=False, quiet=True)
        c.run(["qvm-prefs", args.target, "kernel", args.name])
        print(f"    now: {c.out(['qvm-prefs', args.target, 'kernel'])}")
        print()
        print("    Start it, and watch from a second dom0 terminal:")
        print(f"      qvm-start {args.target}")
        print(f"      qvm-console-dispvm {args.target}")
        print("    Roll back with:")
        print(f"      qvm-shutdown --force {args.target} && qvm-prefs -D {args.target} kernel")


if __name__ == "__main__":
    main()
