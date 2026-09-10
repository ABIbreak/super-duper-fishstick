# 2. Building the kernel

This chapter is the generic part: get a toolchain, get sources, get a config,
compile. The Qubes-specific config changes are chapter 3; packaging for a qube is
chapter 4.

## 2.1 Where to build

Build in a **StandaloneVM** (recommended) or a template-based AppVM. Not dom0.

A StandaloneVM is better because `/usr` persists, so the toolchain, the source
tree and the installed kernel survive a reboot, and because you can safely give it
its own kernel later to test with.

Sizing, for a Fedora-derived config, which is large:

```console
[user@dom0 ~]$ qvm-create --class StandaloneVM --template fedora-42 --label green kbuild
[user@dom0 ~]$ qvm-volume resize kbuild:root 40g
[user@dom0 ~]$ qvm-prefs kbuild memory 4000
[user@dom0 ~]$ qvm-prefs kbuild maxmem 12000
[user@dom0 ~]$ qvm-prefs kbuild vcpus 8
```

A full Fedora-config build needs roughly 25–30 GB of build tree and an hour or
more of wall time on a laptop. `make localmodconfig` (below) cuts both by a large
factor and is usually the right call for a test kernel.

## 2.2 Toolchain

```console
[user@kbuild ~]$ sudo dnf install -y \
    gcc gcc-c++ make bison flex bc \
    elfutils-libelf-devel openssl openssl-devel \
    dwarves rpm-build rsync perl python3 \
    ncurses-devel gcc-plugin-devel libuuid-devel \
    xz zstd cpio kmod
```

If the tree has Rust enabled (`CONFIG_RUST=y`, which Fedora does not set by
default), add `rust rust-src bindgen-cli rustfmt` — the same set
`qubes-linux-kernel` lists in `BuildRequires`.

Three of these bite people:

* **`dwarves`** provides `pahole`. Without it, `CONFIG_DEBUG_INFO_BTF=y` fails
  late in the build with an unhelpful message.
* **`elfutils-libelf-devel`** is needed for objtool. Without it you get
  `fatal error: libelf.h: No such file or directory`.
* **`gcc-plugin-devel`** is needed for `CONFIG_GCC_PLUGINS`, which the Qubes
  fragment sets. Its Kconfig entry is gated on a compile test against
  `gcc-plugin.h`, so without the headers the symbol is simply *unavailable* —
  `merge_config.sh` accepts it, `alldefconfig` drops it, and you get a kernel
  quietly missing `GCC_PLUGIN_LATENT_ENTROPY`. This is the exact failure the
  verification step in [03 §3.5](03-fedora-qubes-config.md#35-applying-the-fragment)
  exists to catch, and it is not hypothetical: it is what that check caught
  when these scripts were first run against a real tree.

`scripts/build_deps.py` in this repo installs the whole set.

## 2.3 Getting the source

Pick one. They differ only in what patches you start from.

**Upstream tarball** — cleanest baseline, no distro or Qubes patches:

```console
[user@kbuild ~]$ v=6.12.63
[user@kbuild ~]$ curl -LO https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-$v.tar.xz
[user@kbuild ~]$ curl -LO https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-$v.tar.sign
[user@kbuild ~]$ unxz -k linux-$v.tar.xz && gpg --verify linux-$v.tar.sign linux-$v.tar
[user@kbuild ~]$ tar xf linux-$v.tar
```

Verify the signature. You are about to run this code with full control of a VM's
address space; `curl | tar` is not the moment to save thirty seconds.

**Upstream git** — for bisecting or tracking a branch:

```console
[user@kbuild ~]$ git clone --depth 1 -b v6.12.63 \
    https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
```

**The Qubes tree** — upstream plus the patches Qubes actually ships. Worth
reading even if you don't build from it: `series.conf` lists them, and several
are Xen-guest fixes you may want.

```console
[user@kbuild ~]$ git clone https://github.com/QubesOS/qubes-linux-kernel
[user@kbuild ~]$ cat qubes-linux-kernel/series.conf
```

Notable ones for guests: `0004-pvops-respect-removable-xenstore-flag-for-block-devi.patch`,
`0006-block-add-no_part_scan-module-parameter.patch`, and two
`xen-xenbus` diagnostics patches.

## 2.4 Getting a config

Never `make defconfig` for this. A defconfig kernel has no Xen frontends and
will not boot as a qube.

**Start from Fedora's config.** This is exactly what Qubes does — their
`get-fedora-latest-config` script pulls the current `kernel-core` RPM, extracts
`/lib/modules/<ver>/config`, and runs `make oldconfig` over it to drop
settings that depend on Fedora-only patches.

The easy version, from inside a running Fedora qube:

```console
[user@kbuild linux-6.12.63]$ cp /boot/config-$(uname -r) .config
[user@kbuild linux-6.12.63]$ make olddefconfig
```

Note that in a qube booting a dom0 kernel there is no `/boot/config-*` — the
running kernel came from dom0. Two ways around it:

```console
# a) from the config of any installed Fedora kernel package
[user@kbuild ~]$ sudo dnf install -y kernel-core
[user@kbuild ~]$ cp /lib/modules/*/config linux-6.12.63/.config

# b) from the running kernel itself, if CONFIG_IKCONFIG_PROC=y (Qubes sets it)
[user@kbuild ~]$ zcat /proc/config.gz > linux-6.12.63/.config
```

Option (b) is the interesting one: `/proc/config.gz` in any qube is the config of
the kernel Qubes is currently booting it with — Fedora's config plus the Qubes
fragment, already merged. It is the best possible starting point, and
`scripts/fetch_config.py` prefers it.

**Then trim, if you want a fast build.** With the target hardware's modules
loaded:

```console
[user@kbuild linux-6.12.63]$ make localmodconfig
```

This drops every module not currently loaded. For a VM kernel that is a huge win
— a qube loads a couple of dozen modules — but be careful: it will also drop
drivers a *different* qube needs. A kernel `localmodconfig`'d inside an AppVM
will be missing everything `sys-net` and `sys-usb` require. Build the general
kernel from the full config; use `localmodconfig` only for a kernel you will
point at one specific qube.

## 2.5 Version identification

Set a `LOCALVERSION` so the result is unmistakable and cannot collide with a
distro kernel:

```console
[user@kbuild linux-6.12.63]$ ./scripts/config --set-str CONFIG_LOCALVERSION -qubes-test
[user@kbuild linux-6.12.63]$ ./scripts/config --disable CONFIG_LOCALVERSION_AUTO
[user@kbuild linux-6.12.63]$ make olddefconfig
```

That string is `uname -r`, the name of the `/lib/modules` directory, and the
argument you will pass to `qubes-prepare-vm-kernel`. Keep it stable.

**Do not read it back with `make kernelrelease` on a tree you have not built
yet — it lies.** `KERNELRELEASE` is read from a cached
`include/config/kernel.release`, and `kernelrelease` is one of the Makefile's
`no-sync-config-targets`, so nothing regenerates that file. On a freshly
configured tree it is stale or empty and your `LOCALVERSION` is missing from
the answer:

```console
[user@kbuild linux-6.12.63]$ make -s kernelrelease
6.12.63                       # wrong -- stale
[user@kbuild linux-6.12.63]$ make -s include/config/kernel.release
[user@kbuild linux-6.12.63]$ cat include/config/kernel.release
6.12.63-qubes-test            # correct
```

This matters more than it looks. If you take the stale string and use it to
name the image in `/boot`, while `make modules_install` uses the real one, the
two disagree and `qubes-prepare-vm-kernel` cannot find a matching pair.
`scripts/build.py` regenerates the file before reading it, via
`_common.kernelrelease()`.

## 2.6 Compiling

```console
[user@kbuild linux-6.12.63]$ make -j"$(nproc)"
```

Then install into the build qube's own filesystem — not because the build qube
will boot it, but because `qubes-prepare-vm-kernel` reads
`/boot/vmlinuz-<kver>` and `/lib/modules/<kver>` from wherever it runs:

```console
[user@kbuild linux-6.12.63]$ sudo make modules_install
[user@kbuild linux-6.12.63]$ sudo make install
```

`make install` on Fedora calls `kernel-install`, which will also try to generate
an initramfs and add a boot entry. In a qube that boots a dom0 kernel both are
harmless no-ops as far as booting goes. If `kernel-install` fails or you'd rather
it not run, copy the image by hand — that is all that's needed:

```console
[user@kbuild linux-6.12.63]$ kver=$(make -s kernelrelease)
[user@kbuild linux-6.12.63]$ sudo cp arch/x86/boot/bzImage /boot/vmlinuz-$kver
[user@kbuild linux-6.12.63]$ sudo cp System.map /boot/System.map-$kver
[user@kbuild linux-6.12.63]$ sudo cp .config /boot/config-$kver
```

`scripts/build.py` takes this second path deliberately, so that a build never
touches the build qube's own boot configuration.

Sanity check before going further:

```console
[user@kbuild ~]$ ls -l /boot/vmlinuz-$kver /lib/modules/$kver/kernel | head
```

Both must exist. Chapter 4 turns them into a qube kernel.

## 2.7 Optional: build RPMs instead

If you'd rather have installable packages — useful if you want the same kernel in
several qubes' filesystems, or in dom0 — the kernel tree can build them itself:

```console
[user@kbuild linux-6.12.63]$ make -j"$(nproc)" binrpm-pkg   # binary only, fast
[user@kbuild linux-6.12.63]$ make -j"$(nproc)" rpm-pkg      # with a source RPM
```

Results land in `~/rpmbuild/RPMS/x86_64/`. Note these are *upstream's* RPMs, not
Fedora's — different package names, no BLS integration, no `kernel-devel` layout
Qubes expects. For a faithful Fedora package, build from Fedora's own spec
instead:

```console
[user@kbuild ~]$ sudo dnf install -y fedpkg rpmdevtools
[user@kbuild ~]$ fedpkg clone -a kernel && cd kernel
[user@kbuild kernel]$ fedpkg switch-branch f42
[user@kbuild kernel]$ sudo dnf builddep kernel.spec
[user@kbuild kernel]$ fedpkg local
```

That is a long build and mostly of interest if you're carrying a patch against
Fedora's kernel specifically. For getting a qube onto a custom kernel, §2.6 is
enough — chapter 4 never needs an RPM.

## 2.8 Rebuilding after a config change

```console
[user@kbuild linux-6.12.63]$ ./scripts/config --enable CONFIG_SOMETHING
[user@kbuild linux-6.12.63]$ make olddefconfig
[user@kbuild linux-6.12.63]$ make -j"$(nproc)"
[user@kbuild linux-6.12.63]$ sudo make modules_install install
```

`scripts/config` edits `.config` without an interactive menu, which makes it
scriptable; `make olddefconfig` then resolves the dependencies it implies.
Always re-run `olddefconfig` after `scripts/config` — otherwise a symbol whose
dependencies are unmet is silently dropped, and you find out at boot.
