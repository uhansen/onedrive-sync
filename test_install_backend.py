import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from install_backend import BUNDLE_DIR, build_host, check_platform, install, main, unpack_bundle
from tools.build_backend_bundle import source_snapshot


class BackendInstallerTests(unittest.TestCase):
    def test_source_identity_covers_uncommitted_inputs_and_excludes_python_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src/lib.rs").write_text("original")
            (root / "src/upload.rs").write_text("new untracked source")
            paths = "src/upload.rs\ntools/__pycache__/ignored.pyc\nsrc/lib.rs\n"
            with patch("tools.build_backend_bundle.subprocess.check_output", return_value=paths):
                files, before = source_snapshot(root)
                self.assertEqual(set(files), {"src/lib.rs", "src/upload.rs"})
                (root / "src/upload.rs").write_text("modified untracked source")
                _, after = source_snapshot(root)
                self.assertNotEqual(before, after)
                with patch("tools.build_backend_bundle.subprocess.check_output",
                           return_value="src/lib.rs\nsrc/upload.rs\n"):
                    self.assertEqual(source_snapshot(root)[1], after)

    def test_tuning_renders_only_requested_values_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "performance with spaces"
            args = ["bash", str(Path(__file__).with_name("tune_backend.sh")),
                    "--output", str(output), "--library", "personal", "--mount", str(root / "mount"),
                    "--poll-seconds", "10", "--cache-mib", "512", "--upload-delay", "1",
                    "--dir-refresh", "10", "--max-upload-mib", "1024", "--perf-log", "--cached-dav-reads"]
            subprocess.run(args, check=True, capture_output=True, text=True)
            self.assertIn("ONEDRIVE_MAX_UPLOAD_BYTES=1073741824", (output / "performance.env").read_text())
            self.assertIn('EnvironmentFile="', next(output.glob("systemd-user/*.service.d/*.conf")).read_text())
            self.assertIn("OnUnitActiveSec=\nOnBootSec=15s\nOnUnitActiveSec=10s", next(output.glob("systemd-user/*.timer.d/*.conf")).read_text())
            self.assertIn("delay_upload 1", (output / "davfs2.conf.snippet").read_text())
            self.assertTrue((output / "davfs2.conf.snippet").read_text().startswith(f'"[{root / "mount"}]"\n'))
            self.assertEqual((output / "performance.env").stat().st_mode & 0o777, 0o600)
            before = (output / "performance.env").read_bytes()
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)
            self.assertEqual((output / "performance.env").read_bytes(), before)

    def test_tuning_rejects_invalid_values_without_creating_output(self):
        for options in [[], ["--poll-seconds", "0"], ["--cache-mib", "512"],
                        ["--max-upload-mib", "256001"], ["--library", "../escape", "--perf-log"]]:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "not-created"
                result = subprocess.run(["bash", str(Path(__file__).with_name("tune_backend.sh")),
                                         "--output", str(output), *options], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())

    def test_bash_entrypoint_forwards_arguments_and_failure_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugin checkout"
            plugin.mkdir()
            script = plugin / "install_backend.sh"
            shutil.copyfile(Path(__file__).with_name("install_backend.sh"), script)
            (plugin / "install_backend.py").write_text(
                "import json, sys\nprint(json.dumps(sys.argv[1:]))\nraise SystemExit(17)\n")
            args = ["--prefix", str(root / "custom prefix"), "--build-from-source"]
            result = subprocess.run(["bash", str(script), *args], cwd=root,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertEqual(json.loads(result.stdout), args)

    def test_bash_entrypoint_reports_missing_python(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(__file__).with_name("install_backend.sh").resolve()
            result = subprocess.run(
                [shutil.which("bash"), str(script)],
                env=dict(os.environ, PATH=directory),
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn("requires Python 3", result.stderr)
            self.assertIn("omarchy pkg add python", result.stderr)

    def test_cli_rejects_non_omarchy_before_writing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "not-installed"
            with patch("sys.argv", ["install_backend.py", "--prefix", str(prefix)]), \
                    patch("install_backend.os.geteuid", return_value=1000), \
                    patch("install_backend.shutil.which", return_value=None), \
                    patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(main(), 1)
            self.assertIn("requires an existing Omarchy", stderr.getvalue())
            self.assertFalse(prefix.exists())

    def test_platform_selects_native_build_or_prebuilt_and_rejects_unsupported(self):
        for system, machine, libc, expected in (
                ("Linux", "x86_64", ("glibc", "2.38"), "binary"),
                ("Linux", "aarch64", ("glibc", "2.38"), "source"),
                ("Linux", "x86_64", ("glibc", "2.37"), "source"),
                ("Linux", "x86_64", ("musl", "1.2"), "source")):
            with self.subTest(system=system, machine=machine, libc=libc):
                with patch("install_backend.platform.system", return_value=system), \
                        patch("install_backend.platform.machine", return_value=machine), \
                        patch("install_backend.platform.libc_ver", return_value=libc):
                    self.assertEqual(check_platform(), expected)
        for system, machine, libc in (
                ("Darwin", "x86_64", ("glibc", "2.38")),
                ("Darwin", "arm64", ("", "")),
                ("Linux", "armv7l", ("glibc", "2.38")),
                ("Windows", "ARM64", ("", ""))):
            with self.subTest(system=system, machine=machine, libc=libc):
                with patch("install_backend.platform.system", return_value=system), \
                        patch("install_backend.platform.machine", return_value=machine), \
                        patch("install_backend.platform.libc_ver", return_value=libc):
                    with self.assertRaises(ValueError):
                        check_platform()

    def test_arm_linux_installs_the_built_host_not_the_x86_binary(self):
        for machine in ("aarch64", "arm64"):
            with self.subTest(machine=machine), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)

                def build(staged, bundle_dir, manifest):
                    (staged / "bin/onedrive-davfs-host").write_bytes(b"native fixture")

                with patch("install_backend.platform.system", return_value="Linux"), \
                        patch("install_backend.platform.machine", return_value=machine), \
                        patch("install_backend.build_host", side_effect=build) as builder, \
                        patch("install_backend.subprocess.run"):
                    install(root / "installed")
                builder.assert_called_once()
                self.assertEqual((root / "installed/bin/onedrive-davfs-host").read_bytes(), b"native fixture")
                self.assertTrue((root / "installed/share/onedrive-davfs/systemd").exists())

    def test_source_bundle_verification_and_missing_cargo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = unpack_bundle(BUNDLE_DIR, root)
            source = unpack_bundle(BUNDLE_DIR, root, source=True)
            self.assertEqual(manifest["revision"], source["revision"])
            self.assertTrue((root / "source/host/Cargo.lock").is_file())
            with patch("install_backend.shutil.which", return_value=None):
                with self.assertRaisesRegex(ValueError, "Rust/cargo"):
                    build_host(root, BUNDLE_DIR, manifest)

    def test_native_build_rejects_mismatched_source_snapshot_before_compiling(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("install_backend.shutil.which", return_value="/fixture/cargo"), \
                    patch("install_backend.unpack_bundle", return_value={
                        "revision": "same", "source_tree_sha256": "different",
                    }), patch("install_backend.subprocess.run") as compiler:
                with self.assertRaisesRegex(ValueError, "different source snapshots"):
                    build_host(Path(directory), BUNDLE_DIR, {
                        "revision": "same", "source_tree_sha256": "expected",
                    })
                compiler.assert_not_called()

    def test_source_manifest_identity_must_match_its_archived_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(BUNDLE_DIR / "onedrive-davfs-host-source.tar.gz",
                            root / "onedrive-davfs-host-source.tar.gz")
            manifest = json.loads((BUNDLE_DIR / "source.json").read_text())
            manifest["source_tree_sha256"] = "0" * 64
            (root / "source.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "source snapshot checksum"):
                unpack_bundle(root, root / "staged", source=True)

    @unittest.skipUnless(platform.system() == "Linux" and platform.machine() == "x86_64",
                         "bundled native host requires Linux x86-64")
    def test_real_bundle_installs_and_reinstalls_without_touching_account_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = root / ".local"
            account = root / ".config/onedrive-davfs/token.json"
            account.parent.mkdir(parents=True)
            account.write_bytes(b"private fixture, not a credential")
            for _ in range(2):
                manifest = install(prefix)
                for name, metadata in manifest["files"].items():
                    target = prefix / name
                    self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), metadata["sha256"])
                    self.assertEqual(target.stat().st_mode & 0o777, metadata["mode"])
            self.assertEqual(account.read_bytes(), b"private fixture, not a credential")
            self.assertFalse((root / ".config/systemd").exists())

    def test_corrupt_archive_fails_before_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle"
            bundle.mkdir()
            shutil.copyfile(BUNDLE_DIR / "backend.json", bundle / "backend.json")
            (bundle / "onedrive-davfs-linux-x86_64.tar.gz").write_bytes(b"corrupt")
            prefix = root / "installed"
            with patch("install_backend.check_platform"):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    install(prefix, bundle)
            self.assertFalse(prefix.exists())

    def test_symlink_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = root / "installed"
            (prefix / "bin").mkdir(parents=True)
            existing = root / "keep"
            existing.write_bytes(b"keep")
            (prefix / "bin/onedrive-davfs-host").symlink_to(existing)
            with patch("install_backend.check_platform"), patch("install_backend.subprocess.run"):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    install(prefix)
            self.assertEqual(existing.read_bytes(), b"keep")
            self.assertFalse((prefix / "share").exists())

    def test_traversal_and_links_are_rejected_even_with_matching_archive_hash(self):
        for name, kind in (("../escape", tarfile.REGTYPE),
                           ("bin/onedrive-davfs-host", tarfile.SYMTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = root / "onedrive-davfs-linux-x86_64.tar.gz"
                with tarfile.open(archive, "w:gz") as bundle:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    entry.linkname = "/tmp/not-installed"
                    entry.size = 0
                    bundle.addfile(entry, io.BytesIO())
                (root / "backend.json").write_text(json.dumps({
                    "format": 1, "platform": "linux-x86_64",
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "files": {name: {"size": 0, "sha256": hashlib.sha256(b"").hexdigest(), "mode": 0o755}},
                }))
                with self.assertRaises(ValueError):
                    unpack_bundle(root, root / "staged")
                self.assertFalse((root / "escape").exists())


if __name__ == "__main__":
    unittest.main()
