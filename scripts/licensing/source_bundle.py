#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Georg Rybski
# SPDX-License-Identifier: LGPL-2.1-only
"""Package source/legal evidence for the generic x86_64 firmware, without fetching.

This deliberately does not certify TEE, EFI, macOS, or Windows distributions.
The source argument must be a clean, immutable source snapshot, not the build tree.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile

LICENSES = ("LICENSE-GPL-2.0-only", "LICENSE-LGPL-2.1-only")
REQUIRED = (*LICENSES, "Makefile", "bin2cbundle.py", "config-libkrunfw_x86_64",
            "flake.nix", "flake.lock", "README.md", "DISTRIBUTION.md")
DIRECTORIES = ("patches", "scripts", "tests")
ARCHIVE = "corresponding-source.tar.gz"
PROFILE = "generic-x86_64"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_relative(value: str) -> Path:
    p = PurePosixPath(value)
    if not value or p.is_absolute() or ".." in p.parts or "\\" in value:
        raise ValueError(f"unsafe relative path: {value!r}")
    return Path(*p.parts)


def regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected a regular file: {path}")
    return path


def selected_files(source: Path) -> list[Path]:
    files = [regular(source / name) for name in REQUIRED]
    for name in DIRECTORIES:
        directory = source / name
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f"missing source directory: {name}")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"symlink in source snapshot: {path}")
            if path.is_file():
                if "__pycache__" in path.parts or path.suffix == ".pyc":
                    raise ValueError("source snapshot contains Python build state")
                files.append(path)
    if not any(p.parent == source / "patches" and p.suffix == ".patch" for p in files):
        raise ValueError("kernel patches are missing")
    return sorted(set(files), key=lambda p: p.relative_to(source).as_posix())


def add_bytes(archive: tarfile.TarFile, name: str, data: bytes, executable: bool = False) -> None:
    info = tarfile.TarInfo("libkrunfw-source/" + name)
    info.size = len(data)
    info.mode = 0o755 if executable else 0o644
    info.uid = info.gid = info.mtime = 0
    info.uname = info.gname = ""
    archive.addfile(info, io.BytesIO(data))


def add_file(archive: tarfile.TarFile, name: str, path: Path) -> None:
    info = tarfile.TarInfo("libkrunfw-source/" + name)
    info.size = path.stat().st_size
    info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
    info.uid = info.gid = info.mtime = 0
    info.uname = info.gname = ""
    with path.open("rb") as stream:
        archive.addfile(info, stream)


def build(source: Path, kernel: Path, config: Path, release: Path, binary: Path, output: Path) -> None:
    source = source.resolve(strict=True)
    files = selected_files(source)
    makefile = (source / "Makefile").read_text()
    version = re.search(r"^KERNEL_VERSION\s*=\s*(linux-[0-9.]+)\s*$", makefile, re.M)
    checksum = re.search(r"^KERNEL_SHA256\s*=\s*([a-f0-9]{64})\s*$", makefile, re.M)
    if not version or not checksum:
        raise ValueError("cannot identify immutable kernel source from Makefile")
    for path in (kernel, config, release, binary):
        regular(path)
    if digest(kernel) != checksum[1]:
        raise ValueError("kernel archive does not match the build's source pin")
    if not config.stat().st_size or not release.read_text().strip():
        raise ValueError("actual built kernel configuration/release are required")
    if output.exists() or output.is_symlink():
        raise ValueError("refusing to overwrite an existing distribution bundle")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        staging = Path(tmp) / "bundle"
        staging.mkdir()
        with (staging / ARCHIVE).open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for path in files:
                        add_file(archive, "library/" + path.relative_to(source).as_posix(), path)
                    add_file(archive, "library/tarballs/" + version[1] + ".tar.gz", kernel)
                    add_file(archive, "build/kernel.config", config)
                    add_file(archive, "build/kernel.release", release)
                    add_bytes(archive, "REBUILD.txt", (
                        "Scope: generic x86_64 Linux firmware only.\n"
                        "The library/ directory contains the original build scripts, patches,\n"
                        "license texts, and the exact upstream kernel archive under tarballs/.\n"
                        "Read library/DISTRIBUTION.md. On an x86_64 Linux build host with the\n"
                        "documented prerequisites, copy build/kernel.config over\n"
                        "library/config-libkrunfw_x86_64, cd library, then run make.\n"
                        "The build uses the bundled kernel archive. Nix builds additionally use\n"
                        "the committed flake inputs; general-purpose build tools are not bundled.\n"
                        "This is corresponding-source evidence, not a bit-reproducibility claim.\n"
                    ).encode())
        for name in LICENSES:
            shutil.copyfile(source / name, staging / name)
        shutil.copyfile(source / "DISTRIBUTION.md", staging / "DISTRIBUTION.md")
        manifest = {
            "schema": 1, "profile": PROFILE,
            "kernel": {"version": version[1], "sha256": checksum[1],
                       "release": release.read_text().strip(), "config_sha256": digest(config)},
            "binary": {"name": binary.name, "sha256": digest(binary)},
            "source_files": {p.relative_to(source).as_posix(): digest(p) for p in files},
            "files": {p.name: digest(p) for p in sorted(staging.iterdir())},
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        verify(staging, binary)
        staging.rename(output)


def verify(bundle: Path, binary: Path) -> dict:
    manifest = json.loads(regular(bundle / "manifest.json").read_text())
    if manifest.get("schema") != 1 or manifest.get("profile") != PROFILE:
        raise ValueError("unsupported or missing firmware distribution profile")
    expected = manifest.get("files", {})
    if not {ARCHIVE, *LICENSES, "DISTRIBUTION.md"} <= expected.keys():
        raise ValueError("source archive or required legal texts missing from manifest")
    actual = {p.name for p in bundle.iterdir()}
    if actual != set(expected) | {"manifest.json"}:
        raise ValueError("unmanifested or missing distribution files")
    for name, sha in expected.items():
        path = regular(bundle / safe_relative(name))
        if digest(path) != sha:
            raise ValueError(f"distribution checksum mismatch: {name}")
    if binary.name != manifest["binary"]["name"] or digest(regular(binary)) != manifest["binary"]["sha256"]:
        raise ValueError("source/legal bundle belongs to a different binary")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("build")
    for flag in ("source", "kernel", "config", "release", "binary", "output"):
        create.add_argument("--" + flag, type=Path, required=True)
    check = sub.add_parser("verify")
    check.add_argument("--bundle", type=Path, required=True)
    check.add_argument("--binary", type=Path, required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    try:
        (build if command == "build" else verify)(**args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"firmware licensing: {error}\n")


if __name__ == "__main__":
    main()
