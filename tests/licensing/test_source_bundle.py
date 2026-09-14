# SPDX-FileCopyrightText: 2026 Georg Rybski
# SPDX-License-Identifier: LGPL-2.1-only
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/licensing/source_bundle.py"
spec = importlib.util.spec_from_file_location("source_bundle", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SourceBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.kernel = self.root / "kernel.tar.gz"
        self.kernel.write_bytes(b"synthetic kernel archive, not a real kernel")
        for name in m.REQUIRED:
            (self.source / name).write_text("synthetic source fixture\n")
        (self.source / "Makefile").write_text(
            "KERNEL_VERSION = linux-1.2.3\nKERNEL_SHA256 = " + m.digest(self.kernel) + "\n")
        for directory in m.DIRECTORIES:
            (self.source / directory).mkdir()
        (self.source / "patches/0001-test.patch").write_text("synthetic patch\n")
        self.config = self.root / "config"
        self.config.write_text("CONFIG_TEST=y\n")
        self.release = self.root / "release"
        self.release.write_text("1.2.3-test\n")
        self.binary = self.root / "libkrunfw.so.5.6.1"
        self.binary.write_bytes(b"synthetic binary")
        self.output = self.root / "bundle"

    def build(self, output=None):
        m.build(self.source, self.kernel, self.config, self.release, self.binary, output or self.output)

    def test_round_trip(self):
        self.build()
        result = m.verify(self.output, self.binary)
        self.assertEqual(result["profile"], "generic-x86_64")
        with tarfile.open(self.output / m.ARCHIVE) as archive:
            names = archive.getnames()
            self.assertIn("libkrunfw-source/library/tarballs/linux-1.2.3.tar.gz", names)
            self.assertIn("libkrunfw-source/build/kernel.config", names)
            self.assertTrue(all(x.uid == 0 and x.mtime == 0 for x in archive.getmembers()))

    def test_deterministic_archive(self):
        self.build()
        second = self.root / "second"
        self.build(second)
        self.assertEqual(m.digest(self.output / m.ARCHIVE), m.digest(second / m.ARCHIVE))

    def test_wrong_kernel_is_rejected(self):
        self.kernel.write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "source pin"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_wrong_binary_is_rejected(self):
        self.build()
        self.binary.write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "different binary"):
            m.verify(self.output, self.binary)

    def test_missing_license_is_rejected(self):
        (self.source / m.LICENSES[0]).unlink()
        with self.assertRaises(ValueError):
            self.build()

    def test_tampered_archive_is_rejected(self):
        self.build()
        (self.output / m.ARCHIVE).write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "checksum"):
            m.verify(self.output, self.binary)

    def test_symlink_source_is_rejected(self):
        (self.source / "scripts/secret").symlink_to(self.binary)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.build()

    def test_missing_patches_are_rejected(self):
        (self.source / "patches/0001-test.patch").unlink()
        with self.assertRaisesRegex(ValueError, "patches"):
            self.build()

    def test_no_overwrite(self):
        self.build()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self.build()

    def test_path_traversal_is_rejected(self):
        for path in ("../outside", "/etc/passwd", "a/../../outside", "a\\b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                m.safe_relative(path)

    def test_extra_distribution_file_is_rejected(self):
        self.build()
        (self.output / "unreviewed").write_text("extra")
        with self.assertRaisesRegex(ValueError, "unmanifested"):
            m.verify(self.output, self.binary)


if __name__ == "__main__":
    unittest.main()
