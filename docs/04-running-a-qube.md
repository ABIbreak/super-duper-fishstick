# 4. Making a qube run your kernel

At this point the build qube has `/boot/vmlinuz-<kver>` and
`/lib/modules/<kver>`. Turning that into a bootable qube is three steps:
package, transfer, select.

Throughout, `<kver>` is the `uname -r` string (`make -s kernelrelease`), and
`<name>` is the short label you'll see in `qvm-prefs`. They do not have to
match; keeping them related saves confusion later.

## 4.1 Package the kernel into a VM-kernel directory

The tool is `qubes-prepare-vm-kernel`, from `qubes-kernel-vm-support`. It reads
`/boot/vmlinuz-<kver>` and `/lib/modules/<kver>` from wherever it runs and
produces `/var/lib/qubes/vm-kernels/<name>/`.

It is available in both dom0 and the VM repos, and that gives you a choice.

### Path A — package in the build qube (recommended)

Nothing unusual ever enters dom0 except three finished files.

```console
[user@kbuild ~]$ sudo dnf install -y qubes-kernel-vm-support dracut busybox e2fsprogs
[user@kbuild ~]$ kver=6.12.63-qubes-test
[user@kbuild ~]$ sudo qubes-prepare-vm-kernel "$kver" mykernel
--> Building files for 6.12.63-qubes-test in /var/lib/qubes/vm-kernels/mykernel
---> Generating initramfs
---> Generating modules.img
--> Done.
```

What it did, in order:

1. Copied `/boot/vmlinuz-<kver>` to `<dir>/vmlinuz`.
2. Ran `dracut --no-hostonly` with `--modules "kernel-modules qubes-vm-simple
   busybox"`, omitting `nss-softokn extra-modules qubes-pciback qubes-udev`, and
   forcing in `xenblk xen-blkfront cdrom ext4 jbd2 crc16 dm_snapshot`. That is
   the initramfs described in [01 §1.3](01-concepts.md#what-the-initramfs-actually-does).
3. Copied `/lib/modules/<kver>` into a staging tree, added copies of `vmlinuz`
   and `initramfs` at its root (a stubdomain's qemu reads them from there in HVM
   mode), made a reproducible `mkfs.ext3` image from it, shrank it with
   `resize2fs -M`, and marked it immutable.

Useful flags:

* `--include-devel` also packs `/usr/src/kernels/<kver>` into `modules.img`, so
  DKMS can build inside qubes using this kernel. Needs the headers present.
* `--modules-only` rebuilds just `modules.img` against an existing `vmlinuz` —
  what you want after recompiling only a module.

**Path A caveat:** if your build qube is a template-based AppVM, `/boot` and
`/lib/modules` writes do not survive a restart. That is fine within one session,
but it's the main reason to use a StandaloneVM.

### Path B — package in dom0

This is the flow the Qubes documentation describes. Use it when the kernel is
already an RPM you want dom0 to own, or when you also want dom0 itself to boot it.

```console
[user@dom0 ~]$ sudo qubes-dom0-update qubes-kernel-vm-support
# copy your kernel RPMs in (see 4.2), then:
[user@dom0 ~]$ sudo dnf install ./kernel-*.rpm
[user@dom0 ~]$ sudo qubes-prepare-vm-kernel 6.12.63-qubes-test mykernel
```

**Understand what installing a kernel RPM in dom0 does.** It runs
`kernel-install`, which writes a bootloader entry and can change which kernel
dom0 boots by default. dom0 is the one domain where a boot failure is not
recoverable from another qube. If you take this path, check
`/boot/loader/entries/` and your GRUB default afterwards, and keep the previous
dom0 kernel installed.

Path A avoids all of that. Prefer it unless you specifically want a dom0 kernel.

## 4.2 Transfer to dom0

Qubes has no "copy into dom0" tool, by design. The supported idiom is for dom0
to *pull*, running a command in the source qube and capturing its stdout:

```console
[user@dom0 ~]$ qvm-run -p kbuild 'cd /var/lib/qubes/vm-kernels && tar c mykernel' \
                 | sudo tar x -C /var/lib/qubes/vm-kernels/
[user@dom0 ~]$ ls -l /var/lib/qubes/vm-kernels/mykernel/
total 512000
-rw-r--r-- 1 root root  12345678 initramfs
-rw-r--r-- 1 root root 498073600 modules.img
-rw-r--r-- 1 root root  11223344 vmlinuz
```

`scripts/dom0_install_vm_kernel.py <srcvm> <name>` wraps this, including the
`sudo`, ownership and mode fixups.

Two things to be deliberate about:

* **You are importing code into the TCB's filesystem.** Everything in that
  directory is executed with full control over the qube that boots it. Import
  only from a build qube you trust, and prefer `qvm-run -p` piped into `tar x`
  over anything that runs code in dom0.
* **`modules.img` is large** — 300–600 MB for a Fedora-derived config. Check
  dom0 free space first (`df -h /var/lib/qubes`).

### Optional: default kernel options and the hotplug marker

Neither file is required, but without `default-kernelopts-common.txt` Qubes
falls back to a built-in default that may not match your kernel:

```console
[user@dom0 ~]$ sudo tee /var/lib/qubes/vm-kernels/mykernel/default-kernelopts-common.txt <<'OPTS'
root=/dev/mapper/dmroot ro nomodeset console=hvc0 rd_NO_PLYMOUTH rd.plymouth.enable=0 plymouth.enable=0 clocksource=tsc xen_privcmd.unrestricted xen_scrub_pages=0
OPTS
[user@dom0 ~]$ sudo touch /var/lib/qubes/vm-kernels/mykernel/memory-hotplug-supported
```

Only add `xen_scrub_pages=0` if the initramfs is the `qubes-vm-simple` one that
re-enables scrubbing — which it is, if you used `qubes-prepare-vm-kernel`.
Create `memory-hotplug-supported` only if you kept
`CONFIG_XEN_BALLOON_MEMORY_HOTPLUG=y`.

## 4.3 Point a qube at it

Test on something disposable. Clone a template or make a scratch AppVM; do not
start with `sys-net` or your only template.

```console
[user@dom0 ~]$ qvm-create --template fedora-42 --label red ktest
[user@dom0 ~]$ qvm-prefs ktest kernel                # what it uses now
6.12.59-1.fc37
[user@dom0 ~]$ qvm-prefs ktest kernel mykernel       # switch it
[user@dom0 ~]$ qvm-prefs ktest kernel
mykernel
[user@dom0 ~]$ qvm-start ktest
```

Watch the boot from a second dom0 terminal, started before or as the qube starts:

```console
[user@dom0 ~]$ qvm-console-dispvm ktest
```

Verify from inside once it's up:

```console
[user@ktest ~]$ uname -r
6.12.63-qubes-test
[user@ktest ~]$ findmnt /lib/modules          # should be the xvdd overlay
[user@ktest ~]$ lsmod | grep -E 'xen_blkfront|xen_netfront'
[user@ktest ~]$ ls /dev/xen/                  # evtchn, gntdev, gntalloc, privcmd, xenbus
[user@ktest ~]$ zcat /proc/config.gz | grep XEN_GNTDEV_DMABUF
```

If `uname -r` is right but the clipboard and file copy don't work, you lost
vchan — check `/dev/xen/evtchn` and `/dev/xen/gntdev` exist and that
`xen_privcmd.unrestricted` is on the command line (`cat /proc/cmdline`).

### Other knobs

```console
[user@dom0 ~]$ qvm-prefs ktest kernelopts "loglevel=7 systemd.log_level=debug"
[user@dom0 ~]$ qvm-prefs -D ktest kernel        # revert to the default
[user@dom0 ~]$ qubes-prefs default-kernel       # what new qubes will get
[user@dom0 ~]$ qvm-ls --fields NAME,KERNEL      # who is running what
```

`kernelopts` is *added to* `default-kernelopts-common.txt`, it does not replace
it. So you can add debug options without having to restate `root=` and
`xen_privcmd.unrestricted`.

Only make it the system-wide default once it has proven itself:

```console
[user@dom0 ~]$ qubes-prefs default-kernel mykernel
```

## 4.4 Rolling back

The reason to test on a scratch qube is that this is the entire recovery
procedure, and it runs from dom0 with the qube shut down:

```console
[user@dom0 ~]$ qvm-shutdown --force ktest
[user@dom0 ~]$ qvm-prefs ktest kernel 6.12.59-1.fc37
```

You cannot fix a broken kernel from inside the qube — there is no bootloader
prompt and no way in. Keep at least one Qubes-packaged kernel installed at all
times, and never remove the one `qubes-prefs default-kernel` names (the
`kernel` package's `%preun` refuses to let you, but a hand-made directory has no
such protection).

To retire a custom kernel:

```console
[user@dom0 ~]$ qvm-ls --fields NAME,KERNEL | grep mykernel     # must be empty
[user@dom0 ~]$ sudo rm -rf /var/lib/qubes/vm-kernels/mykernel
```

## 4.5 Alternative: let the qube boot its own kernel

Sometimes you want the opposite arrangement — the kernel lives inside the qube,
updates with `dnf`, and DKMS modules build normally. The cost is that a bad
kernel is now a bad qube, recoverable only through the GRUB menu on the console.

Do this on a **clone** of the template, never the original.

Inside the Fedora template or standalone:

```console
[root@fedora-vm ~]# dnf install -y kernel qubes-kernel-vm-support grub2
[root@fedora-vm ~]# grub2-install /dev/xvda
[root@fedora-vm ~]# grub2-mkconfig -o /boot/grub2/grub.cfg
```

`grub2-probe: error: cannot find a GRUB drive for /dev/mapper/dmroot` during
`grub2-mkconfig` is expected and harmless — `dmroot` is the device-mapper node
the initramfs synthesised, and GRUB has no way to name it.

`qubes-kernel-vm-support` is what makes this work: it ships the dracut modules
that build a Qubes-aware initramfs *inside* the VM, and it appends
`/etc/default/grub.qubes-kernel-vm-support` to `/etc/default/grub`, which sets
`xen_privcmd.unrestricted`, sets `xen_scrub_pages=0` once the initramfs is known
to support it, and turns off BLS. Installing it also rebuilds every existing
`/boot/initramfs-*.img`.

For a hand-built kernel, you own the initramfs and the modules:

```console
[root@fedora-vm ~]# dracut -f /boot/initramfs-6.12.63-qubes-test.img 6.12.63-qubes-test
[root@fedora-vm ~]# dkms autoinstall -k 6.12.63-qubes-test    # if you use DKMS modules
[root@fedora-vm ~]# grub2-mkconfig -o /boot/grub2/grub.cfg
```

Then shut the qube down and, in dom0, hand it the keys. What you set depends on
`virt_mode`:

Pick **one** of the following — they are alternatives, not a sequence.

```console
# virt_mode=hvm -- the qube's own bootloader runs from its own disk.
# Nothing extra is needed in dom0.
[user@dom0 ~]$ qvm-prefs ktest virt_mode hvm
[user@dom0 ~]$ qvm-prefs ktest kernel ''

# virt_mode=pvh (Qubes' default) -- Xen needs a PVH-capable GRUB, from dom0.
[user@dom0 ~]$ sudo qubes-dom0-update pvgrub2-pvh
[user@dom0 ~]$ qvm-prefs ktest virt_mode pvh
[user@dom0 ~]$ qvm-prefs ktest kernel pvgrub2-pvh
```

For PVH, `kernel ''` and `kernel pvgrub2-pvh` end up in the same place —
`kernel_path` in `qubesvm.py` falls back to
`/var/lib/qubes/vm-kernels/pvgrub2-pvh/vmlinuz` when `kernel` is empty and the
mode is `pvh`. Naming it explicitly is clearer, and it is what the GUI does.

Note the package naming: the dom0 package is `grub2-xen-pvh`, but the Qubes
documentation installs it as `qubes-dom0-update pvgrub2-pvh`. Use the latter;
check with `rpm -q grub2-xen-pvh` afterwards.

`pv` works the same way with `pvgrub2`, and is discouraged: PV gives the guest a
much larger slice of the hypervisor's attack surface than PVH.

Depending on the kernel, you may also need to switch off memory ballooning,
because an in-VM kernel does not advertise the hotplug support that dom0-provided
kernels do:

```console
[user@dom0 ~]$ qvm-prefs ktest maxmem 0
[user@dom0 ~]$ qvm-prefs ktest memory 2000
```

Lower `GRUB_TIMEOUT` in `/etc/default/grub` once it works — it is dead time on
every boot. Leave it long enough at first that `qvm-console-dispvm` can catch the
menu.
