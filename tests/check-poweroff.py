#!/usr/bin/env python3
"""Apply the driver patch and test its exact C code without host port I/O."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile


HEADERS = {
    "linux/init.h": "#define __init\n#define device_initcall(fn)\n",
    "linux/io.h": "void outb(unsigned char value, unsigned short port);\n",
    "linux/reboot.h": "int register_platform_power_off(void (*callback)(void));\n",
    "asm/irqflags.h": "void native_irq_disable(void);\nvoid native_halt(void);\n",
}

HARNESS = r"""
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include "libkrun-poweroff.c"

static void (*registered)(void);
static int registration_status, registrations, writes, disabled, halts;
static unsigned char last_value;
static unsigned short last_port;
static jmp_buf halted;

int register_platform_power_off(void (*callback)(void))
{
    registrations++;
    if (!registration_status)
        registered = callback;
    return registration_status;
}

void native_irq_disable(void) { disabled++; }

void outb(unsigned char value, unsigned short port)
{
    assert(disabled == 1);
    writes++;
    last_value = value;
    last_port = port;
}

void native_halt(void)
{
    assert(writes == 1);
    /* Return once to test that the driver remains in its halt loop. */
    if (++halts == 2)
        longjmp(halted, 1);
}

int main(void)
{
    assert(libkrun_power_off_init() == 0);
    assert(registrations == 1 && registered == libkrun_power_off);
    assert(writes == 0 && disabled == 0 && halts == 0);

    /* A platform registration conflict must be returned, not overwritten. */
    registration_status = -16;
    assert(libkrun_power_off_init() == -16);
    assert(registrations == 2 && registered == libkrun_power_off);
    assert(writes == 0 && disabled == 0 && halts == 0);

    if (setjmp(halted) == 0) {
        registered();
        assert(!"power-off callback returned");
    }
    assert(writes == 1 && disabled == 1 && halts == 2);
    assert(last_value == 0xfe && last_port == 0x64);
    puts("PASS: registration, registration failure, exact exit I/O, nonreturning halt");
}
"""


def check_added_whitespace(text):
    """Check actual additions, including payload that itself starts with ++."""
    old = new = 0
    for number, line in enumerate(text.splitlines(), 1):
        if not (old or new):
            match = re.match(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
            if match:
                old = int(match.group(1) or 1)
                new = int(match.group(2) or 1)
            continue
        if line.startswith("\\"):
            continue
        if line.startswith("+"):
            payload = line[1:]
            if payload.rstrip(" \t") != payload or re.match(r"^ +\t", payload):
                raise ValueError(f"added payload whitespace at line {number}")
            new -= 1
        elif line.startswith("-"):
            old -= 1
        elif line.startswith(" "):
            old -= 1
            new -= 1
        else:
            raise ValueError(f"invalid hunk line {number}")
        if min(old, new) < 0:
            raise ValueError(f"invalid hunk counts at line {number}")
    if old or new:
        raise ValueError("incomplete patch hunk")


def test_added_whitespace():
    # A blank/context-tab prefix is required patch data, not added indentation.
    check_added_whitespace("@@ -1,2 +1,3 @@\n \n \tcontext\n+\taddition\n")
    check_added_whitespace("@@ -0,0 +1 @@\n+++payload\n")
    for addition in ["+bad ", "+bad\t", "+ \tbad", "+++payload "]:
        try:
            check_added_whitespace("@@ -0,0 +1 @@\n" + addition + "\n")
        except ValueError:
            continue
        raise AssertionError(f"whitespace negative accepted: {addition!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-source", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--patch-directory", type=Path, required=True)
    args = parser.parse_args()
    test_added_whitespace()
    patches = sorted(args.patch_directory.glob("*.patch"))
    assert patches and args.patch.resolve() in [path.resolve() for path in patches]
    for patch in patches:
        try:
            check_added_whitespace(patch.read_text())
        except ValueError as error:
            raise ValueError(f"{patch.name}: {error}") from error
    print(f"PASS: added-payload whitespace in {len(patches)} patches and negative controls")
    config = args.config.read_text().splitlines()
    assert config.count("CONFIG_POWER_RESET=y") == 1
    assert config.count("CONFIG_POWER_RESET_LIBKRUN=y") == 1

    with tempfile.TemporaryDirectory(prefix="libkrun-poweroff-test-") as tmp:
        root = Path(tmp)
        wanted = {"drivers/power/reset/Kconfig", "drivers/power/reset/Makefile"}
        # Copy only these bounded regular files, never archive-owned paths.
        with tarfile.open(args.kernel_source, "r|gz") as archive:
            for member in archive:
                relative = member.name.partition("/")[2]
                if relative not in wanted:
                    continue
                assert member.isfile() and 0 < member.size < 1024 * 1024
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source:
                    target.write_bytes(source.read(member.size))
                wanted.remove(relative)
                if not wanted:
                    break
        assert not wanted, wanted
        subprocess.run(
            ["patch", "--batch", "--fuzz=0", "-p1", "-i", str(args.patch.resolve())],
            cwd=root, check=True, timeout=20,
        )
        kconfig = (root / "drivers/power/reset/Kconfig").read_text()
        section = kconfig.split("config POWER_RESET_LIBKRUN\n", 1)[1].split("\nconfig ", 1)[0]
        assert "depends on X86_64" in section and "default y" not in section
        assert "obj-$(CONFIG_POWER_RESET_LIBKRUN) += libkrun-poweroff.o" in (
            root / "drivers/power/reset/Makefile"
        ).read_text().splitlines()
        for name, text in HEADERS.items():
            target = root / "include" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        (root / "test.c").write_text(HARNESS)
        executable = root / "test-poweroff"
        subprocess.run(
            [os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-I", str(root / "include"), "-I", str(root / "drivers/power/reset"),
             str(root / "test.c"), "-o", str(executable)],
            check=True, timeout=20,
        )
        subprocess.run([str(executable)], check=True, timeout=5)
    print("PASS: exact kernel patch application and opt-in configuration wiring")


if __name__ == "__main__":
    main()
