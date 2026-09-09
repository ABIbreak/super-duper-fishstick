# 1. How a qube gets a kernel

You cannot usefully build a kernel for Qubes without knowing what boots it.
Qubes' boot path for a VM is unusual enough that assumptions carried over from
"normal Linux" are the main source of failure.

## 1.1 Domains

Qubes is Xen. Xen owns the hardware; every Linux you interact with is a guest.

* **dom0** — the privileged domain. Runs the Qubes admin stack, the GUI daemon,
  the block backends. It has no network. It also holds the kernels that other
  qubes boot.
* **domU** — every other qube: templates, AppVMs, StandaloneVMs, `sys-net`,
  disposables.

dom0 in Qubes R4.2 is Fedora 37 (`cat /etc/qubes-release`, `rpm -E %fedora`).
Templates are much newer Fedoras. This mismatch matters when you decide where to
compile: **build in a template-based qube or a StandaloneVM, never in dom0.**

## 1.2 Virtualisation modes

`qvm-prefs <vm> virt_mode` is one of:

| Mode | Who provides the kernel | Notes |
| --- | --- | --- |
| `pvh` | dom0 (default), or `pvgrub2-pvh` | Qubes' default. No emulated devices, no stubdomain. |
| `pv` | dom0, or `pvgrub2` | Legacy. Discouraged — larger hypervisor attack surface. |
| `hvm` | the VM's own bootloader | Needs a stubdomain; used for non-Linux guests and for qubes with PCI devices. |

The default is computed, not stored: a qube with an assigned PCI device defaults
to `hvm`, a template-based qube inherits its template's mode, and everything else
defaults to `pvh` (`_default_virt_mode` in `qubes/vm/qubesvm.py`).

**Consequence for your build:** a kernel destined for the default `pvh` mode must
be built with `CONFIG_XEN_PVH=y`, so the image carries the
`XEN_ELFNOTE_PHYS32_ENTRY` note Xen needs to enter it directly. Fedora sets this
already; just don't turn it off.

## 1.3 The dom0-provided kernel (the default)

For a qube with a non-empty `kernel` property, Xen is handed a kernel image and
an initramfs straight from dom0's filesystem. There is no bootloader in the
guest at all — no GRUB, no `/boot` that matters, no BLS entries.

```
/var/lib/qubes/vm-kernels/<name>/
├── vmlinuz                          # the kernel image (need not even be Linux)
├── initramfs                        # dracut image built with the qubes-vm-simple module
├── modules.img                      # ext3 image: /lib/modules/<kver>, plus copies of
│                                    #   vmlinuz and initramfs at its root
├── default-kernelopts-common.txt    # kernel cmdline appended to the qube's `kernelopts`
└── memory-hotplug-supported         # marker: enables hotplug-based ballooning
```

`<name>` is what `qvm-prefs <vm> kernel` shows and sets. It is a directory name,
nothing more — it need not look like a kernel version.

In Qubes R4.2 and newer, only `vmlinuz` is strictly required; the rest are
optional and each has a sensible fallback. In practice you want all of them.

### Why `modules.img` exists

The root filesystem of an AppVM comes from its template and is shared and mostly
read-only. If kernel modules lived there, changing a qube's kernel would mean
rewriting its template. So dom0 attaches the modules as a separate block device
and the initramfs grafts them on:

* `xvda` — root volume. Read-only for AppVMs, read-write for templates.
* `xvdb` — private volume, `/rw`.
* `xvdc` — volatile volume. The initramfs partitions it: `xvdc1` is swap, the
  rest backs the copy-on-write snapshot of a read-only root.
* `xvdd` — `modules.img`, mounted as an overlay over `/lib/modules`.

**This is the single most important consequence of the whole design:** your
modules must be inside `modules.img`. Installing them into a template's
`/lib/modules` accomplishes nothing.

### What the initramfs actually does

`initramfs` is a dracut image built with the `qubes-vm-simple` module from
`qubes-kernel-vm-support`. Its `init` (see `dracut/simple/init.sh` in
`qubes-linux-utils`) is short and worth knowing:

1. Re-enables `xen-balloon` page scrubbing, which the cmdline turned off for
   boot speed.
2. `modprobe xenblk || modprobe xen-blkfront` — **Fedora ships
   `CONFIG_XEN_BLKDEV_FRONTEND=m`, so this must be in the initramfs.**
3. Waits for `/dev/xvda`, repairs its GPT with `gptfix`, and locates the root
   partition by partition label `Root filesystem`, falling back to `xvda3`,
   falling back to the whole disk.
4. Partitions `xvdc`, makes swap on `xvdc1`.
5. If root is read-only (AppVM), builds a `dm-snapshot` named `dmroot` over it
   with `xvdc2` as the COW store. If read-write (template), symlinks
   `/dev/mapper/dmroot` at the root device. Either way the cmdline's
   `root=/dev/mapper/dmroot` resolves.
6. Mounts root, then mounts `xvdd` and overlays it onto `/lib/modules`
   (`overlay` if available, otherwise a bind mount of just the `uname -r`
   subdirectory).
7. `switch_root`.

The modules that initramfs needs — `xenblk`/`xen-blkfront`, `ext4`, `jbd2`,
`crc16`, `dm_snapshot`, `overlay`, `cdrom` — are forced in at build time by
`qubes-prepare-vm-kernel`. If you build your own initramfs by hand and forget
them, the qube hangs at "Waiting for /dev/xvda* devices…".

### The default kernel command line

`default-kernelopts-common.txt` is generated at package time (`kernel.spec.in`)
and currently reads:

```
root=/dev/mapper/dmroot ro nomodeset console=hvc0 rd_NO_PLYMOUTH \
rd.plymouth.enable=0 plymouth.enable=0 clocksource=tsc \
xen_privcmd.unrestricted xen_scrub_pages=0
```

Two of these are not optional:

* `xen_privcmd.unrestricted` — **required for vchan**, which is qrexec, which is
  the GUI, the clipboard, file copy, and qubes-db. Lose it and the qube boots
  but is deaf.
* `xen_scrub_pages=0` — a boot-time speedup, safe only because the
  `qubes-vm-simple` initramfs turns scrubbing back on before `switch_root`. Do
  not set it with an initramfs that doesn't.

Qubes composes the final cmdline as this file plus the qube's own `kernelopts`
property (plus a `systemd.machine_id=` for Linux guests). `nomodeset` is dropped
automatically when a display PCI device is assigned.

## 1.4 The in-VM kernel (the alternative)

Setting `qvm-prefs <vm> kernel ''` makes the qube boot a kernel from its own
filesystem. What happens then depends on `virt_mode`:

* `pvh` → Xen boots `/var/lib/qubes/vm-kernels/pvgrub2-pvh/vmlinuz`, a GRUB
  built as a PVH kernel, which then reads `/boot/grub2/grub.cfg` inside the qube.
  Requires `grub2-xen-pvh` in dom0.
* `pv` → same idea with `pvgrub2`.
* `hvm` → no dom0 kernel at all; the stubdomain's firmware boots the qube's own
  disk, exactly like a normal machine. Nothing extra needed in dom0.

This path is covered in [04 §4](04-running-a-qube.md#45-alternative-let-the-qube-boot-its-own-kernel).
It is the right choice when you want the qube to manage its own kernel updates
and DKMS modules; the dom0 path is the right choice when you want one kernel
shared by many qubes, or you're testing a kernel you might need to back out of
from outside.

## 1.5 Which mental model to keep

> A Qubes VM kernel is not installed *in* a system. It is a small directory of
> artifacts in dom0 that Xen hands to a guest at boot, plus a disk image of
> modules that the guest's initramfs grafts onto itself.

Everything in the next three documents follows from that sentence.
