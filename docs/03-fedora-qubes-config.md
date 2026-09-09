# 3. What must change for Fedora + Qubes OS

The good news first: **Fedora's stock kernel config is already a working Xen
guest and a working Xen host.** Fedora enables the whole `CONFIG_XEN_*` family
out of the box. The Qubes delta is small, and Qubes itself builds its kernel by
taking Fedora's config and merging a fragment over it.

This chapter enumerates that delta and explains each part.

## 3.1 How Qubes derives its config

Two scripts in `qubes-linux-kernel` tell the whole story:

* `get-fedora-latest-config` downloads the newest Fedora `kernel-core` RPM,
  verifies its signature, extracts `/lib/modules/<ver>/config`, runs
  `yes '' | make oldconfig` over it to drop settings that depend on
  Fedora-only patches, and writes the result as `config-base-<version>`.
* `gen-config` strips the `##` comments from `config-qubes`, merges it over the
  base with `scripts/kconfig/merge_config.sh -m`, runs
  `make KCONFIG_ALLCONFIG=.config alldefconfig`, and then **verifies that every
  symbol it asked for actually survived**, failing the build if one did not.

That last step is the part people skip and shouldn't. `merge_config.sh` will
happily accept a symbol whose dependencies are unmet, `alldefconfig` will drop
it, and nothing complains until the qube won't boot. [§3.5](#35-applying-the-fragment)
reproduces the check; `scripts/fetch_config.py` in this repo does the merge and
the verification together and refuses to continue if a symbol was lost.

## 3.2 What Fedora already gives you

Taken from a current Fedora `kernel-core` config — no changes needed to any of
these, but a `make defconfig` or an over-enthusiastic `make localmodconfig` will
lose them:

```
CONFIG_HYPERVISOR_GUEST=y   CONFIG_PARAVIRT=y         CONFIG_PARAVIRT_XXL=y
CONFIG_XEN=y                CONFIG_XEN_PV=y           CONFIG_XEN_PVH=y
CONFIG_XEN_PVHVM=y          CONFIG_XEN_DOM0=y         CONFIG_XEN_PV_DOM0=y
CONFIG_HVC_XEN=y            CONFIG_HVC_XEN_FRONTEND=y CONFIG_PCI_XEN=y
CONFIG_XEN_XENBUS_FRONTEND=y
CONFIG_XEN_BLKDEV_FRONTEND=m  CONFIG_XEN_NETDEV_FRONTEND=m
CONFIG_XEN_BLKDEV_BACKEND=m   CONFIG_XEN_NETDEV_BACKEND=m
CONFIG_XEN_PCIDEV_FRONTEND=m  CONFIG_XEN_PCIDEV_BACKEND=m
CONFIG_XEN_DEV_EVTCHN=m       CONFIG_XEN_GNTDEV=m
CONFIG_XEN_GRANT_DEV_ALLOC=m  CONFIG_XEN_PRIVCMD=m
CONFIG_XENFS=m                CONFIG_XEN_COMPAT_XENFS=y
CONFIG_XEN_SYS_HYPERVISOR=y   CONFIG_XEN_BALLOON=y
CONFIG_XEN_BALLOON_MEMORY_HOTPLUG=y  CONFIG_XEN_UNPOPULATED_ALLOC=y
```

Note `CONFIG_XEN_BLKDEV_FRONTEND=m`. The root disk driver is a module. That is
survivable only because the initramfs carries it — which is why chapter 4 insists
you build the initramfs with `qubes-prepare-vm-kernel` rather than a plain
`dracut` invocation.

`config/qubes-vm.config` in this repo restates all of the above as Group 1, so
that if you do trim the config the verification step catches the loss.

## 3.3 The real deltas

These are the settings where Fedora's answer is wrong for Qubes. Each row was
computed by diffing `config-qubes` against `config-base` in the Qubes tree.

### Functional — the qube misbehaves without these

| Setting | Fedora | Qubes | Why |
| --- | --- | --- | --- |
| `CONFIG_XEN_GRANT_DMA_ALLOC` | not set | `y` | GUI daemon turns grant refs into dma-bufs |
| `CONFIG_XEN_GNTDEV_DMABUF` | absent | `y` | same — the other half of that path |
| `CONFIG_XEN_VIRTIO` | `y` | **not set** | under PV it acts as `FORCE_GRANT`; breaks Xen nested in KVM, and Qubes uses no virtio under Xen |
| `CONFIG_MODPROBE_PATH` | `/usr/bin/modprobe` | `/sbin/modprobe` | supports unmerged `/sbin` |
| `CONFIG_SECURITY_APPARMOR` | not set | `y` | Whonix uses AppArmor |
| `CONFIG_DEFAULT_SECURITY_SELINUX` | `y` | not set | Qubes doesn't run SELinux in VMs |
| `CONFIG_LSM` | Fedora's list | `landlock,yama,loadpin,safesetid,integrity` | follows from the above |
| `CONFIG_IKCONFIG` / `_PROC` | not set | `y` | `/proc/config.gz` in every qube — very useful |
| `CONFIG_DEBUG_WX` | `y` | not set | Xen PV guests genuinely have W+X pages; the splat is noise |

### Host-side and platform

| Setting | Fedora | Qubes | Why |
| --- | --- | --- | --- |
| `CONFIG_PREEMPT` | not set | `y` | dm-thin/dm-crypt work in dom0 otherwise stalls the desktop |
| `CONFIG_HOTPLUG_PCI` | `y` | **not set** | DMA attack surface via ExpressCard/Thunderbolt (qubes-issues#1673) |
| `CONFIG_USB_{U,O,E,X}HCI_HCD` | `y` | `m` | so a controller can be bound to `pciback` before a driver claims it |
| `CONFIG_PHYSICAL_START` | `0x1000000` | `0x200000` | avoids an `EfiACPIMemoryNVS` conflict on some AMD Threadripper boards |
| `CONFIG_DRM_ACCEL_AMDXDNA` | `m` | not set | needs PASID, which Xen exposes to no guest; breaks boot under Xen |
| `CONFIG_INTEL_IOMMU_DEFAULT_ON` | not set | `y` | Qubes' isolation depends on the IOMMU |

### Hardening and policy — safe to skip on a debug kernel

`KERNEL_XZ` instead of `KERNEL_ZSTD`; `ARCH_MMAP_RND_BITS=32`; `KEXEC`,
`CRASH_DUMP`, `HIBERNATION`, `PROC_KCORE` all off; `LEGACY_VSYSCALL_NONE`;
`INIT_ON_FREE_DEFAULT_ON`; `GCC_PLUGINS` with `LATENT_ENTROPY`;
`PANIC_ON_OOPS=y` with `PANIC_TIMEOUT=-1`.

That last pair is a deliberate choice worth understanding before you copy it: an
oops kills the qube instead of leaving it running in an unknown state, and
`-1` means "do not reboot", so the console log in
`/var/log/xen/console/guest-<vm>.log` survives for you to read. For kernel
development that is exactly what you want.

## 3.4 Fedora-specific traps

**Boot Loader Spec entries.** Fedora's `kernel-install` writes BLS entries under
`/boot/loader/entries/`. For a dom0-provided VM kernel this is irrelevant —
nothing reads them. For an in-VM kernel it is actively wrong, and
`qubes-kernel-vm-support` sets `GRUB_ENABLE_BLSCFG=false` in
`/etc/default/grub.qubes-kernel-vm-support` precisely to disable it.

**Module signing.** Fedora's spec signs modules; the Qubes spec sets
`%global signmodules 1`. For a locally built kernel you neither need nor want
enforcement — leave `CONFIG_MODULE_SIG_FORCE` off. If you enabled
`CONFIG_MODULE_SIG_ALL`, the build generates an ephemeral key and signs with it,
which is fine, but do not also set `CONFIG_MODULE_SIG_KEY` to a path that
doesn't exist.

**Secure Boot is not in play for guests.** A qube's kernel is loaded by Xen from
dom0, not by shim/GRUB, so an unsigned custom kernel boots fine in a qube. dom0's
own kernel is a different question and outside this document's scope.

**`localmodconfig` in a qube is misleading.** See
[02 §2.4](02-building.md#24-getting-a-config) — the set of loaded modules in an
AppVM is not the set another qube needs.

**Don't build in dom0.** Beyond the trust argument, dom0 has no network, and
adding a compiler and the kernel's build dependencies to it materially enlarges
the thing every qube's security rests on.

## 3.5 Applying the fragment

```console
[user@kbuild linux-6.12.63]$ zcat /proc/config.gz > .config          # Fedora+Qubes base
[user@kbuild linux-6.12.63]$ grep -v '^##' ../config/qubes-vm.config > /tmp/frag
[user@kbuild linux-6.12.63]$ ./scripts/kconfig/merge_config.sh -m .config /tmp/frag
[user@kbuild linux-6.12.63]$ make KCONFIG_ALLCONFIG=.config alldefconfig
```

Then verify — this is the step `gen-config` exists to perform:

```console
[user@kbuild linux-6.12.63]$ for cfg in $(sed -n \
    's/^\(# \)\{0,1\}\(CONFIG_[a-zA-Z0-9_]*\)[= ].*/\2/p' /tmp/frag); do
      want=$(grep -w "$cfg" /tmp/frag)
      got=$(grep -w "$cfg" .config)
      [ "$want" = "$got" ] || echo "LOST: $cfg (wanted '$want', got '$got')"
    done
```

Anything printed here is a symbol whose dependencies were not met. Chase it down
before building — a missing `CONFIG_XEN_BLKDEV_FRONTEND` costs you an hour of
compile time and a qube that hangs.

`scripts/fetch_config.py` does all of §3.5 for you.
