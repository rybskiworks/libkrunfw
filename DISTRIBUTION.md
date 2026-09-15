# Firmware distribution contract

The Linux kernel and kernel patches remain GPL-2.0-only. Library code remains
LGPL-2.1-only. Existing upstream copyright and attribution notices are retained.
The helper added for this contract is Copyright (c) 2026 Georg Rybski and is
licensed LGPL-2.1-only. No upstream code is reassigned to the fork maintainer.

The generic x86_64 Nix package installs `share/libkrunfw/compliance/` containing
both license texts, this document, an exact corresponding-source archive, and
`manifest.json`. The manifest binds those bytes to the installed firmware binary.
Copy this directory with the binary. A distributor of a portable archive must
include actual files, not dangling store symlinks. A public binary cache must
retain and serve the source-bearing closure while offering the binaries.

The archive contains the exact upstream kernel tarball, patches, original library
source/build scripts, committed Nix inputs, and actual built kernel configuration
and release identifier. It is generated using the same pinned source snapshot
and kernel archive as the build. Hashes alone are not a source offer. Build tools
and their system libraries are not included in this component's source archive;
they need their own treatment when they are themselves redistributed.

## Rebuilding the generic variant

Unpack `corresponding-source.tar.gz`. Install the Linux generic build prerequisites
listed in `library/README.md`, including Python pyelftools. Copy
`build/kernel.config` to `library/config-libkrunfw_x86_64`, enter `library/`, and run
`make`. The matching upstream kernel tarball is already in `library/tarballs/`.
The original Makefile applies the included patches. The committed flake files are
also included for Nix/Lix builds; evaluating their toolchain inputs can require
network/cache access. No bit-identical-output guarantee is made by this archive.

## Scope and release qualification

This contract covers the generic x86_64 Linux Nix output. It does not certify TEE,
EFI, macOS or Windows variants, qboot, or the pre-existing `initrd/initrd.gz` blob.
Those outputs require separately verified complete source and attribution before
publication. In particular, do not call a source archive containing an unexplained
prebuilt initrd a complete source bundle. No historical objects are removed here.

Run `python3 scripts/licensing/source_bundle.py verify --bundle DIR --binary FILE`
on the assembled distribution before publishing. Use the full versioned binary
filename, not a SONAME symlink. Keep the manifest with any copied artifact. The
manifest is integrity evidence, not an independent signature or legal opinion.

No historical violation is presumed or automatically cured by this change.
Inventory old releases, cache exports, CI artifacts and images. Where an old binary
was distributed, supply matching material for that exact build, not the newest
kernel source. Retain existing grants and notices; do not rewrite Git history as
a general-purpose remedy. Record unresolved ownership or source gaps explicitly.

References:
- https://www.gnu.org/licenses/old-licenses/gpl-2.0.html
- https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- README.md, License section
