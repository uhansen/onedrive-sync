import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import tune_backend as tuning


class TuningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix=".test-tuning-", dir=Path(__file__).parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).absolute()
        self.addCleanup(patch.stopall)
        patch.object(tuning.Path, "home", return_value=self.root).start()

    def args(self, *extra):
        return tuning.parse_args(["--output", str(self.root / "render"),
                                  "--mount", str(self.root / "OneDrive"), *extra])

    def quiet(self, callback, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return callback(*args)

    def fake_machine(self, args):
        target = tuning.target_for(args)
        daemon, mount, sync, timer = tuning.units(target)
        self.active = {daemon: True, mount: True, sync: False, timer: True}
        self.mounted = True
        self.commands = []
        self.fail_start = None
        self.busy = False
        patch.object(tuning, "check_platform").start()
        patch.object(tuning.os.path, "ismount", side_effect=lambda path: self.mounted).start()
        patch.object(tuning, "status", return_value={
            "ok": True, "capabilities": {"persistedGraphCooldown": True},
            "accessVerified": True, "lastSyncError": None,
        }).start()

        def systemctl(*command, **kwargs):
            self.commands.append(command)
            operation = command[0]
            output = ""
            if operation == "show":
                output = "loaded" if "LoadState" in command[2] else (
                    "active" if self.active[command[1]] else "inactive")
            elif operation in ("start", "stop"):
                unit = command[1]
                if operation == "start" and self.fail_start == unit:
                    self.fail_start = None
                    raise RuntimeError("Injected service failure")
                self.active[unit] = operation == "start" and unit != sync
                if unit == mount and operation == "start":
                    self.mounted = True
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

        def run(command, **kwargs):
            self.commands.append(tuple(command))
            if command[0] == "/usr/bin/umount":
                if self.busy:
                    raise subprocess.CalledProcessError(32, command)
                self.mounted = False
            output = target["url"] if command[0] == "findmnt" else ""
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

        patch.object(tuning, "systemctl", side_effect=systemctl).start()
        patch.object(tuning.subprocess, "run", side_effect=run).start()
        return target

    def test_preset_is_offline_render_only_and_resets_timer_triggers(self):
        args = self.args("--preset", "low-latency")
        with patch.object(tuning, "systemctl") as service, patch.object(tuning, "status") as status:
            self.assertEqual(self.quiet(tuning.main, [
                "--preset", "low-latency", "--mount", str(args.mount), "--output", str(args.output)]), 0)
        service.assert_not_called()
        status.assert_not_called()
        timer = next(args.output.glob("systemd-user/*.timer.d/*.conf")).read_text()
        for directive in ("OnActiveSec=", "OnBootSec=", "OnStartupSec=", "OnUnitActiveSec=",
                          "OnUnitInactiveSec=", "OnCalendar="):
            self.assertIn(directive + "\n", timer)
        self.assertIn("OnActiveSec=1s\nOnUnitInactiveSec=1s\n", timer)
        self.assertIn("AccuracySec=100ms\n", timer)
        env = (args.output / "performance.env").read_text()
        self.assertEqual(env, "ONEDRIVE_PERF_LOG=1\nONEDRIVE_CACHED_DAV_READS=0\n")
        self.assertNotIn("MAX_UPLOAD", env)
        davfs = (args.output / "davfs2.conf.snippet").read_text()
        for value in ("cache_size 512", "delay_upload 0", "dir_refresh 1", "file_refresh 0"):
            self.assertIn(value, davfs)
        self.assertFalse((self.root / ".config").exists())

    def test_preset_rejects_conflicting_options_and_restore_target_options(self):
        for extra in (["--cached-dav-reads"], ["--max-upload-mib", "1024"],
                      ["--poll-seconds", "2"], ["--cache-mib", "1024"]):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.args("--preset", "low-latency", *extra)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tuning.parse_args(["--restore", str(self.root / "backup"), "--library", "personal"])

    def test_environment_path_escaping_and_wrapper_from_other_directory(self):
        value = tuning.environment_line(Path('/home/a space/"quote"/percent%/slash\\name/$literal'))
        self.assertIn('a space/\\"quote\\"/percent%%/slash\\\\name/$literal', value)
        output = self.root / "spaces % tuning"
        result = subprocess.run(
            ["bash", str(Path(__file__).with_name("tune_backend.sh").absolute()),
             "--output", str(output), "--perf-log"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("spaces %% tuning", next(output.glob("systemd-user/*/*.conf")).read_text())

    def test_merge_preserves_globals_custom_options_and_unrelated_sections(self):
        mount = self.root / "OneDrive"
        original = (f'# global\ncache_size 50\n"[{mount}]" # selected\n'
                    '  delay_upload 10 # old\nuse_locks 0\nfile_refresh 30\n'
                    'delay_upload 20\n[/other]\ncache_size 99\n# retained\n')
        merged = tuning.merge_davfs(original, mount, {"delay_upload": 0, "file_refresh": 0, "cache_size": 512})
        self.assertTrue(merged.startswith('# global\ncache_size 50\n'))
        self.assertIn("use_locks 0\n", merged)
        self.assertEqual(merged.count("delay_upload"), 1)
        self.assertIn('[/other]\ncache_size 99\n# retained\n', merged)
        self.assertIn("file_refresh 0\ncache_size 512\n", merged)
        self.assertEqual(tuning.merge_davfs(merged, mount, {"delay_upload": 0, "file_refresh": 0, "cache_size": 512}), merged)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            tuning.merge_davfs(f'"[{mount}]"\n"[{mount}]"\n', mount, {"cache_size": 512})

    def test_davfs_section_quotes_include_brackets_as_required_by_davfs2(self):
        # davfs2.conf(5), GENERAL SYNTAX RULES: "[/home/otto/with space]".
        for name in ("OneDrive", "OneDrive with spaces", "Owner's OneDrive"):
            with self.subTest(name=name):
                args = self.args("--preset", "low-latency")
                args.mount = self.root / name
                snippet = tuning.render_files(args, args.output / "performance.env")["davfs2.conf.snippet"]
                expected_header = f'"[{args.mount}]"\n'
                self.assertTrue(snippet.startswith(expected_header))
                self.assertTrue(tuning.merge_davfs("", args.mount, {"cache_size": 512}).startswith(expected_header))
                for header in (f'"[{args.mount}]"', "[" + str(args.mount).replace(" ", "\\ ") + "]"):
                    original = f"{header} # selected\ncache_size 50\n[/other]\ncache_size 73\n"
                    merged = tuning.merge_davfs(original, args.mount, {"cache_size": 512})
                    self.assertEqual(merged, f"{header} # selected\ncache_size 512\n[/other]\ncache_size 73\n")
                with self.assertRaisesRegex(ValueError, "Invalid davfs section"):
                    tuning.merge_davfs(f'["{args.mount}"]\ncache_size 50\n', args.mount, {"cache_size": 512})

    def test_capability_gate_precedes_service_changes_and_backup(self):
        args = self.args("--preset", "low-latency", "--apply")
        self.fake_machine(args)
        tuning.render(args)
        with patch.object(tuning, "status", return_value={"ok": True, "accessVerified": True}):
            with self.assertRaisesRegex(ValueError, "persistedGraphCooldown"):
                tuning.apply(args)
        self.assertEqual(self.commands, [])
        self.assertFalse((args.output / "backup").exists())

    def test_authenticated_readiness_and_cloud_access_are_distinct(self):
        target = tuning.target_for(self.args("--preset", "low-latency"))
        with patch.object(tuning, "load_basic_secret", return_value=("private", None)), \
                patch.object(tuning, "request_json", return_value={"ok": True}) as request:
            self.assertEqual(tuning.status(target), {"ok": True})
            self.assertEqual(request.call_args.args, (target["url"].rstrip("/") + "/_status", "private"))
        with patch.object(tuning, "status", return_value={
            "ok": True, "capabilities": {"persistedGraphCooldown": True}, "accessVerified": False,
        }), patch.object(tuning.time, "monotonic", side_effect=[0, 31]):
            with self.assertRaisesRegex(RuntimeError, "cloud-access"):
                tuning.wait_ready(target, verified=True)

    def test_apply_and_restore_exact_files_modes_services_with_private_backup(self):
        args = self.args("--preset", "low-latency", "--apply")
        target = self.fake_machine(args)
        original_states = dict(self.active)
        # An inactive timer must not accidentally become enabled or stay active on restore.
        original_states[tuning.units(target)[3]] = False
        self.active.update(original_states)
        davfs = self.root / ".davfs2/davfs2.conf"
        davfs.parent.mkdir()
        original = f'# custom\n"[{args.mount}]"\ndelay_upload 7\nuse_locks 0\n[/other]\ncache_size 73\n'.encode()
        davfs.write_bytes(original)
        davfs.chmod(0o640)
        tuning.render(args)
        self.quiet(tuning.apply, args)
        self.assertIn("delay_upload 0", davfs.read_text())
        self.assertIn("use_locks 0", davfs.read_text())
        backup = args.output / "backup"
        metadata = json.loads((backup / "metadata.json").read_text())
        for path in backup.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        env, manifest = tuning.owned_paths(target)
        self.assertTrue(env.is_file())
        self.assertTrue(manifest.is_file())
        self.assertFalse(any("enable" in command for command in self.commands))
        self.quiet(tuning.restore, backup)
        self.assertEqual(davfs.read_bytes(), original)
        self.assertEqual(davfs.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.active, original_states)
        self.assertFalse(env.exists())
        self.assertFalse(manifest.exists())
        self.assertTrue((backup / "metadata.json").exists())
        for entry in metadata["files"]:
            if entry["before"] is None:
                self.assertFalse(Path(entry["path"]).exists())

    def test_busy_mount_recovers_timer_without_writing_configs_or_stopping_daemon(self):
        args = self.args("--preset", "low-latency", "--apply")
        target = self.fake_machine(args)
        self.busy = True
        before = dict(self.active)
        tuning.render(args)
        with self.assertRaisesRegex(RuntimeError, "previous files/services restored"):
            self.quiet(tuning.apply, args)
        self.assertEqual(self.active, before)
        self.assertTrue(self.mounted)
        self.assertNotIn(("stop", tuning.units(target)[0]), self.commands)
        self.assertFalse(tuning.owned_paths(target)[0].exists())
        unmount = next(command for command in self.commands if command[0] == "/usr/bin/umount")
        self.assertEqual(unmount, ("/usr/bin/umount", "--", target["mount"]))

    def test_failed_apply_rolls_back_exact_files_and_active_states(self):
        args = self.args("--preset", "low-latency", "--apply")
        target = self.fake_machine(args)
        before = dict(self.active)
        config = self.root / ".davfs2/davfs2.conf"
        config.parent.mkdir()
        config.write_bytes(b"# preserve exact bytes without newline")
        config.chmod(0o644)
        self.fail_start = tuning.units(target)[1]
        tuning.render(args)
        with self.assertRaisesRegex(RuntimeError, "previous files/services restored"):
            self.quiet(tuning.apply, args)
        self.assertEqual(config.read_bytes(), b"# preserve exact bytes without newline")
        self.assertEqual(config.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.active, before)
        self.assertTrue(self.mounted)
        self.assertFalse(tuning.owned_paths(target)[0].exists())
        self.assertTrue((args.output / "backup/metadata.json").is_file())

    def test_owned_file_conflict_and_post_apply_changes_are_not_overwritten(self):
        args = self.args("--preset", "low-latency", "--apply")
        target = self.fake_machine(args)
        env, _ = tuning.owned_paths(target)
        env.parent.mkdir(parents=True)
        env.write_bytes(b"custom file\n")
        with self.assertRaisesRegex(ValueError, "customized owned"):
            tuning.plan(args, target)
        env.unlink()
        tuning.render(args)
        self.quiet(tuning.apply, args)
        env.write_bytes(b"changed after apply\n")
        commands = len(self.commands)
        with self.assertRaisesRegex(ValueError, "changed since apply"):
            tuning.restore(args.output / "backup")
        self.assertEqual(len(self.commands), commands)
        self.assertEqual(env.read_bytes(), b"changed after apply\n")

    def test_known_prior_render_can_be_retuned_without_overwriting_other_settings(self):
        args = self.args("--perf-log", "--poll-seconds", "10", "--max-upload-mib", "128")
        target = tuning.target_for(args)
        proposed = tuning.plan(args, target)
        for path, data in proposed.items():
            tuning.atomic_write(path, data)
        second = self.args("--preset", "low-latency")
        revised = tuning.plan(second, tuning.target_for(second))
        self.assertIn(b"ONEDRIVE_CACHED_DAV_READS=0", revised[tuning.owned_paths(target)[0]])
        self.assertIn(b"ONEDRIVE_MAX_UPLOAD_BYTES=134217728", revised[tuning.owned_paths(target)[0]])
        timer = next(path for path in revised if path.name == "90-performance.conf" and ".timer.d" in str(path))
        self.assertIn(b"OnUnitInactiveSec=1s", revised[timer])

    def test_failed_restore_undoes_itself_and_keeps_both_backups(self):
        args = self.args("--preset", "low-latency", "--apply")
        target = self.fake_machine(args)
        tuning.render(args)
        self.quiet(tuning.apply, args)
        env, _ = tuning.owned_paths(target)
        applied = env.read_bytes()
        self.fail_start = tuning.units(target)[1]
        with self.assertRaisesRegex(RuntimeError, "Injected service failure"):
            self.quiet(tuning.restore, args.output / "backup")
        self.assertEqual(env.read_bytes(), applied)
        self.assertTrue(self.mounted)
        self.assertTrue(self.active[tuning.units(target)[0]])
        self.assertEqual(len(list((args.output / "backup").glob("restore-undo-*"))), 1)

    def test_restore_will_not_unmount_a_replacement_filesystem(self):
        args = self.args("--preset", "low-latency", "--apply")
        target = self.fake_machine(args)
        tuning.render(args)
        self.quiet(tuning.apply, args)
        env, _ = tuning.owned_paths(target)
        applied = env.read_bytes()
        before = len(self.commands)
        with patch.object(tuning, "verify_mount", side_effect=ValueError("different source")):
            with self.assertRaisesRegex(ValueError, "different source"):
                self.quiet(tuning.restore, args.output / "backup")
        self.assertFalse(any(command[0] == "/usr/bin/umount" for command in self.commands[before:]))
        self.assertEqual(env.read_bytes(), applied)
        self.assertTrue(self.mounted)

    def test_busy_sync_is_waited_for_without_stopping_or_killing_it(self):
        args = self.args("--preset", "low-latency")
        target = tuning.target_for(args)
        values = [subprocess.CompletedProcess([], 0, stdout=value) for value in ("activating", "active", "inactive")]
        with patch.object(tuning, "systemctl", side_effect=values) as command, \
                patch.object(tuning.time, "sleep"):
            tuning.wait_sync(target)
        self.assertTrue(all(call.args[0] == "show" for call in command.call_args_list))
        with patch.object(tuning, "systemctl", return_value=subprocess.CompletedProcess([], 0, stdout="active")), \
                patch.object(tuning.time, "monotonic", side_effect=[0, 181]):
            with self.assertRaisesRegex(RuntimeError, "not forcibly stopped"):
                tuning.wait_sync(target)

    def test_detects_configuration_changed_between_plan_and_backup(self):
        args = self.args("--preset", "low-latency")
        target = tuning.target_for(args)
        originals = {}
        proposed = tuning.plan(args, target, originals)
        env, _ = tuning.owned_paths(target)
        tuning.atomic_write(env, b"concurrent edit\n")
        with self.assertRaisesRegex(ValueError, "changed while planning"):
            tuning.make_backup(self.root / "backup", target, {}, proposed, originals)
        self.assertEqual(env.read_bytes(), b"concurrent edit\n")

    def test_explicit_library_only_and_mount_must_match_registry(self):
        args = self.args("--library", "personal", "--preset", "low-latency")
        profile = {"id": "personal", "mountPoint": str(args.mount), "url": "http://127.0.0.1:8767/",
                   "envFile": str(self.root / "personal.env"), "daemonServiceUnit": "onedrive-davfs-personal.service",
                   "mountServiceUnit": "onedrive-davfs-personal-mount.service"}
        with patch.object(tuning, "load_profiles", return_value=([profile], "revision")):
            target = tuning.target_for(args)
            self.assertEqual(target["url"], profile["url"])
            self.assertEqual(target["unit"], "onedrive-davfs-personal")
            args.mount = self.root / "wrong"
            with self.assertRaisesRegex(ValueError, "registered mountpoint"):
                tuning.target_for(args)
        legacy = tuning.target_for(self.args("--perf-log"))
        self.assertEqual(legacy["unit"], "onedrive-davfs")

    def test_symlinked_config_and_backup_path_escape_are_refused(self):
        args = self.args("--preset", "low-latency", "--apply")
        target = self.fake_machine(args)
        env, _ = tuning.owned_paths(target)
        env.parent.mkdir(parents=True)
        victim = self.root / "victim"
        victim.write_bytes(b"do not touch")
        env.symlink_to(victim)
        with self.assertRaisesRegex(ValueError, "symlinked"):
            tuning.plan(args, target)
        self.assertEqual(victim.read_bytes(), b"do not touch")
        env.unlink()
        tuning.render(args)
        self.quiet(tuning.apply, args)
        metadata_path = args.output / "backup/metadata.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["files"][0]["path"] = str(victim)
        metadata_path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "unexpected"):
            tuning.restore(metadata_path.parent)
        self.assertEqual(victim.read_bytes(), b"do not touch")

    def test_platform_requires_normal_user_omarchy_linux(self):
        for system, uid, omarchy in (("Darwin", 1000, "/bin/omarchy"), ("Linux", 0, "/bin/omarchy"),
                                     ("Linux", 1000, None)):
            with self.subTest(system=system, uid=uid, omarchy=omarchy), \
                    patch.object(tuning.platform, "system", return_value=system), \
                    patch.object(tuning.os, "getuid", return_value=uid), \
                    patch.object(tuning.shutil, "which", return_value=omarchy):
                with self.assertRaisesRegex(ValueError, "normal user"):
                    tuning.check_platform()


if __name__ == "__main__":
    unittest.main()
