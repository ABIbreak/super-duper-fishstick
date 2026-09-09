# 5. Troubleshooting

## 5.1 Getting at the evidence

A qube that fails to boot leaves two traces, both readable from dom0.

**Live console** — must be attached while the qube is starting, so run it from a
second dom0 terminal:

```console
[user@dom0 ~]$ qvm-console-dispvm ktest
```

**Console log** — survives the failure, which makes it the more useful of the two:

```console
[user@dom0 ~]$ sudo tail -n 200 /var/log/xen/console/guest-ktest.log
```

**Xen / libvirt errors** — when the qube never even starts:

```console
[user@dom0 ~]$ sudo xl dmesg | tail -40
[user@dom0 ~]$ sudo tail -40 /var/log/libvirt/libxl/libxl-driver.log
```

If you kept `CONFIG_PANIC_TIMEOUT=-1` from the Qubes fragment, a panicking qube
stays up with its message on the console instead of rebooting away from it.

## 5.2 Symptoms

### The qube never starts; error mentions the kernel

```
libxl: error: ... failed to load kernel: No such file or directory
```

`/var/lib/qubes/vm-kernels/<name>/vmlinuz` is missing or unreadable. Check the
name matches exactly what `qvm-prefs <vm> kernel` prints, and that the file is
mode 644 root:root — a `tar x` as a non-root user in dom0 is the usual cause.

### `xc_dom_parse_image failed` / "not a PVH kernel"

The image lacks the PVH entry note. You built without `CONFIG_XEN_PVH=y`, or
you're feeding Xen something that isn't a bzImage. Confirm:

```console
[user@kbuild linux-6.12.63]$ grep -E 'CONFIG_XEN_PVH|CONFIG_XEN_PV=' .config
```

Fix the config, rebuild, re-run `qubes-prepare-vm-kernel`. As a stopgap you can
set `qvm-prefs <vm> virt_mode pv`, but fix the config instead.

### Boot stops at "Waiting for /dev/xvda* devices…"

The block frontend is not in the initramfs. Fedora builds
`CONFIG_XEN_BLKDEV_FRONTEND=m`, so it must be. This is what
`qubes-prepare-vm-kernel` forces in with `-d "xenblk xen-blkfront …"`; if you
hand-rolled a `dracut` command, that's the bug. Rebuild with
`qubes-prepare-vm-kernel` and check:

```console
[user@kbuild ~]$ lsinitrd /var/lib/qubes/vm-kernels/mykernel/initramfs \
                   | grep -E 'blkfront|dm-snapshot|ext4|overlay'
```

### "Qubes: FATAL: cannot create dmroot!"

`dm-snapshot` is missing from the initramfs, or `CONFIG_BLK_DEV_DM` /
`CONFIG_DM_SNAPSHOT` were dropped from the config. The same `lsinitrd` check
applies. Note this only affects qubes with a read-only root — a template may boot
fine while every AppVM on it fails, which is a confusing signal if you test on
the wrong one.

### Root mounts, then everything fails: no modules

```
modprobe: FATAL: Module xen_netfront not found in directory /lib/modules/6.12.63-qubes-test
```

`modules.img` is absent, or it contains a different `uname -r` than the kernel.
The directory inside the image must be named exactly `$(uname -r)`. Check from
dom0:

```console
[user@dom0 ~]$ sudo mkdir -p /mnt/mi && sudo mount -o loop,ro \
                 /var/lib/qubes/vm-kernels/mykernel/modules.img /mnt/mi
[user@dom0 ~]$ ls /mnt/mi                # expect: vmlinuz initramfs <kver>/
[user@dom0 ~]$ sudo umount /mnt/mi
```

A `CONFIG_LOCALVERSION` change between `make modules_install` and
`qubes-prepare-vm-kernel` is the usual cause of a mismatch.

### The qube boots but has no network

`xen-netfront` didn't load. Confirm the module is in `modules.img` and that
`CONFIG_XEN_NETDEV_FRONTEND` survived the config merge. On `sys-net`
specifically, also check `CONFIG_XEN_PCIDEV_FRONTEND` — without it the NIC is
never handed over and `sys-net` comes up with nothing to route.

### The qube boots but has no GUI, clipboard or file copy; qrexec times out

vchan is broken. In the qube:

```console
[user@ktest ~]$ ls /dev/xen/          # need evtchn, gntdev, gntalloc, privcmd
[user@ktest ~]$ cat /proc/cmdline     # need xen_privcmd.unrestricted
```

Missing device nodes mean `CONFIG_XEN_DEV_EVTCHN`, `CONFIG_XEN_GNTDEV`,
`CONFIG_XEN_GRANT_DEV_ALLOC` or `CONFIG_XEN_PRIVCMD` got dropped. A missing
`xen_privcmd.unrestricted` means you overwrote the default command line — it
lives in `default-kernelopts-common.txt`, and `kernelopts` is meant to add to it,
not replace it.

If the GUI specifically is degraded while qrexec works, check
`CONFIG_XEN_GNTDEV_DMABUF` and `CONFIG_XEN_GRANT_DMA_ALLOC` — those are the two
settings Fedora leaves off and Qubes turns on.

### Memory ballooning doesn't work / qube is stuck at its boot allocation

Either `CONFIG_XEN_BALLOON_MEMORY_HOTPLUG` is off, or the
`memory-hotplug-supported` marker file is missing from the kernel directory.
Qubes checks for that file to decide whether a dom0-provided kernel can be
ballooned by hotplug. HVM qubes never get it — that is deliberate, emulated
devices misbehave.

### Build fails: `pahole: command not found` / BTF errors

`sudo dnf install dwarves`. Or, for a quick test kernel,
`./scripts/config --disable CONFIG_DEBUG_INFO_BTF && make olddefconfig`.

### Build fails: `libelf.h: No such file or directory`

`sudo dnf install elfutils-libelf-devel`.

### `make modules_install` fills the disk

A Fedora-derived config installs several GB of modules plus a debuginfo-laden
build tree. Grow the volume (`qvm-volume resize kbuild:root 60g` from dom0) or
disable debug info:

```console
[user@kbuild linux-6.12.63]$ ./scripts/config --enable CONFIG_DEBUG_INFO_NONE \
    --disable CONFIG_DEBUG_INFO --disable CONFIG_DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT
[user@kbuild linux-6.12.63]$ make olddefconfig
```

That mirrors what `kernel.spec.in` does when `with_debuginfo` is 0.

### A config option I set isn't in the built kernel

Its dependencies weren't met, `merge_config.sh` accepted it anyway, and
`alldefconfig` dropped it. Run the verification loop in
[03 §3.5](03-fedora-qubes-config.md#35-applying-the-fragment) — or use
`scripts/fetch_config.py`, which fails the run rather than letting it through.

## 5.3 When all else fails

Set the qube back to a Qubes-packaged kernel and start again:

```console
[user@dom0 ~]$ qvm-shutdown --force ktest
[user@dom0 ~]$ qvm-prefs -D ktest kernel
[user@dom0 ~]$ qvm-prefs ktest kernel
```

This always works, because nothing about the failed kernel is stored inside the
qube. That property — a broken kernel is one `qvm-prefs` away from fixed — is the
main practical argument for the dom0-provided path over an in-VM kernel while
you're still iterating.
