# Scripts

Python 3.9+, no third-party dependencies — dom0 and Fedora templates both ship
a usable interpreter, and Qubes' own admin tooling is Python, so these fit in
without pulling anything into the TCB.

Each script says which domain it runs in and enforces it: `build_deps.py`,
`fetch_config.py` and `build.py` refuse to run in dom0; `dom0_install_vm_kernel.py`
refuses to run in a qube. On a non-Qubes machine no guard fires.

| Script | Runs in | Does |
| --- | --- | --- |
| `build_deps.py` | build qube | installs the toolchain and `qubes-kernel-vm-support` |
| `fetch_config.py <ver>` | build qube | downloads + GPG-verifies source, seeds a Fedora config, merges `config/qubes-vm.config`, **fails if any symbol was silently dropped** |
| `build.py [srcdir]` | build qube | `make`, `modules_install`, installs the image to `/boot` without invoking `kernel-install` |
| `package_vm_kernel.py <kver> [name]` | build qube *or* dom0 | runs `qubes-prepare-vm-kernel`, writes the default cmdline and the hotplug marker |
| `dom0_install_vm_kernel.py <srcvm> <name> [target]` | **dom0** | pulls the directory over `qvm-run --pass-io \| tar x`, fixes ownership, optionally sets `qvm-prefs kernel` |

`_common.py` holds the shared helpers (domain detection, subprocess wrappers,
`sudo_write`). It is imported, not run.

Full walkthrough: [`../docs/04-running-a-qube.md`](../docs/04-running-a-qube.md).

```console
# build qube
$ ./scripts/build_deps.py
$ ./scripts/fetch_config.py 6.12.63
$ ./scripts/build.py linux-6.12.63
$ ./scripts/package_vm_kernel.py 6.12.63-qubes-test mykernel

# dom0
$ ./scripts/dom0_install_vm_kernel.py kbuild mykernel ktest
$ qvm-start ktest
```

`--localversion` (default `-qubes-test`) and `-j/--jobs` (default: all CPUs) are
the two options worth setting.

## Where shell survives, and why

The scripts are Python; four things are still shelled out to, each because the
alternative is worse:

1. **`make`, `scripts/kconfig/merge_config.sh`, `scripts/config`** — the kernel's
   own build system. Reimplementing kconfig dependency resolution in Python to
   avoid calling it would be strictly worse than calling it.
2. **`dnf`, `gpg`, `tar`, `qubes-prepare-vm-kernel`, `qvm-*`** — external tools
   with no adequate in-process equivalent. All are invoked with argument lists,
   never through a shell, so no quoting or injection is in play.
3. **The `qvm-run` command string** in `dom0_install_vm_kernel.py`
   (`cd … && tar c …`) is a command line for the *remote* qube's shell. That is
   `qvm-run`'s interface; there is no argv-style alternative. The only
   interpolated value is the directory name, passed through `repr()`.
4. **`sudo`** prefixes rather than running the whole script as root, so the
   privileged surface stays visible at each call site. `sudo_write` routes
   file creation through a temp file and `install`, so `sudo` never runs a
   shell or sees file content on a command line.

Documentation examples stay as shell transcripts: they are commands a person
types at a prompt, and rendering them as Python would obscure what is actually
being run.
