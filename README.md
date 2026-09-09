# Building a Linux kernel for Qubes OS on Fedora

A complete, working path from upstream kernel source to a running qube on that
kernel — written for Qubes OS R4.2/R4.3 with Fedora templates and a Fedora dom0.

Three questions, three answers:

| Question | Where |
| --- | --- |
| How does a qube get a kernel at all? | [docs/01-concepts.md](docs/01-concepts.md) |
| How do I build a kernel? | [docs/02-building.md](docs/02-building.md) |
| What must change for Fedora + Qubes? | [docs/03-fedora-qubes-config.md](docs/03-fedora-qubes-config.md) |
| How do I make a qube boot it? | [docs/04-running-a-qube.md](docs/04-running-a-qube.md) |
| It didn't boot. | [docs/05-troubleshooting.md](docs/05-troubleshooting.md) |

## The short version

A qube does not normally boot its own kernel. Xen loads a `vmlinuz` and an
`initramfs` that live **in dom0**, under
`/var/lib/qubes/vm-kernels/<name>/`, and hands the guest's modules to it as a
separate ext3 image (`modules.img`) attached as `xvdd`. So "make a qube run my
kernel" means: build the kernel somewhere safe, turn it into that three-file
directory, drop the directory into dom0, and point the qube at it with
`qvm-prefs`.

```console
# in a build qube (never dom0):
$ ./scripts/build_deps.py                      # toolchain
$ ./scripts/fetch_config.py 6.12.63            # source + Fedora config + Qubes fragment
$ ./scripts/build.py linux-6.12.63             # make -j, modules_install, install
$ ./scripts/package_vm_kernel.py 6.12.63-qubes-test mykernel

# in dom0:
$ ./scripts/dom0_install_vm_kernel.py kbuild mykernel ktest
$ qvm-start ktest
```

Everything below explains why each of those steps exists, and what to do when
one of them doesn't work.

The helper scripts are Python 3, stdlib only —
see [scripts/README.md](scripts/README.md), which also records where shell is
still invoked and why.

## Scope and safety

* **Never build in dom0.** dom0 has no network by design and is the trusted
  computing base of the whole system. Build in a StandaloneVM or a template-based
  AppVM with plenty of disk and RAM; move only the finished artifacts into dom0.
* **Never change the kernel of `sys-net`, `sys-firewall`, or your only template
  first.** Test on a throwaway clone. A qube that cannot boot cannot be fixed
  from the inside.
* **Keep a known-good kernel installed.** `qubes-prefs default-kernel` should
  keep pointing at a Qubes-packaged kernel until yours has proven itself.

## Provenance

The mechanics documented here were read out of the Qubes OS sources rather than
recalled: [`qubes-linux-kernel`](https://github.com/QubesOS/qubes-linux-kernel)
(`config-qubes`, `gen-config`, `kernel.spec.in`),
[`qubes-linux-utils`](https://github.com/QubesOS/qubes-linux-utils)
(`qubes-prepare-vm-kernel`, the `qubes-vm-simple` dracut module),
[`qubes-core-admin`](https://github.com/QubesOS/qubes-core-admin) (`qubesvm.py`),
and [`qubes-doc`](https://github.com/QubesOS/qubes-doc)
(`managing-vm-kernels`). Where a detail is version-sensitive, the text says so.
