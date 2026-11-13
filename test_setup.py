import argparse
from contextlib import contextmanager, ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
import base64

from install_backend import BUNDLE_DIR, unpack_bundle
import setup_account as setup


class NativeSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, HOME=str(self.home))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        unpack_bundle(BUNDLE_DIR, self.home / ".local")
        self.account = setup.run_profiles(
            "account", "--id", "work", "--client-id", "fixture-client",
            "--tenant", "fixture-tenant", "--scopes", setup.DEFAULT_SCOPES)["account"]
        self.token = Path(self.account["credentialDir"]) / "token.json"
        self.token.write_text(json.dumps({"credential_id": "fixture-credential"}))
        self.token.chmod(0o600)
        settings = self.home / ".config/omarchy/shell.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"bar": {"layout": {"right": [{"id": "onedrive-sync"}]}}}))

    def args(self, **overrides):
        values = dict(account="work", library="documents", client_id=None, tenant=None,
                      sites=False, site_url=None, group_id=None, selector="me/drive",
                      name="Test documents", login="browser", no_activate=True)
        return argparse.Namespace(**dict(values, **overrides))

    @contextmanager
    def source(self, credential="fixture-credential", account=None):
        account = account or self.account
        drive = {
            "id": "fixture-drive", "accountId": "fixture-graph-account",
            "credentialId": credential, "tenantId": account["tenantId"],
            "name": "Fixture documents", "selector": "drives/fixture-drive",
        }

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if not self.path.startswith("/_resolve?"):
                    self.send_error(404)
                    return
                data = json.dumps({"ok": True, "drive": drive}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        env = self.home / "bootstrap.env"
        env.write_text(
            f'ONEDRIVE_CLIENT_ID="{account["clientId"]}"\n'
            f'ONEDRIVE_TENANT_ID="{account["tenantId"]}"\n'
            f'ONEDRIVE_SCOPES="{account["scopes"]}"\n'
            'ONEDRIVE_BASIC_AUTH_SECRET="fixture-secret-not-a-credential"\n')
        env.chmod(0o600)
        try:
            yield f"http://127.0.0.1:{server.server_port}/", env, "fixture-secret-not-a-credential"
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            env.unlink()

    def create_library(self):
        with patch.object(setup, "bootstrap", side_effect=lambda account: self.source()):
            return setup.configure_account(self.args())["profile"]

    def test_existing_account_uses_real_native_helper_without_replacing_login(self):
        before = self.token.read_bytes()
        profile = self.create_library()
        self.assertEqual(self.token.read_bytes(), before)
        self.assertEqual(profile["credentialDir"], self.account["credentialDir"])
        self.assertEqual(profile["selector"], "drives/fixture-drive")
        self.assertFalse(Path(profile["mountPoint"]).exists())
        self.assertEqual(Path(profile["envFile"]).stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.home / ".davfs2").exists())
        with self.assertRaisesRegex(ValueError, "resume with"):
            setup.configure_account(self.args())

    def test_wrong_bootstrap_credential_cannot_save_a_library(self):
        with patch.object(setup, "bootstrap", side_effect=lambda account: self.source("wrong-credential")):
            with self.assertRaisesRegex(RuntimeError, "not using this account"):
                setup.configure_account(self.args())
        self.assertEqual(setup.registry()["libraries"], [])
        self.assertFalse((setup.registry_path().parent / "library-data/documents").exists())

    def test_existing_account_does_not_silently_change_tenant_or_scopes(self):
        for overrides in ({"tenant": "another-tenant"}, {"sites": True}):
            with self.subTest(**overrides), patch.object(setup, "bootstrap") as host:
                with self.assertRaises(ValueError):
                    setup.configure_account(self.args(**overrides))
                host.assert_not_called()
        self.assertEqual(setup.registry()["libraries"], [])

    def test_new_personal_account_logs_in_to_its_own_credential_directory(self):
        real_run = subprocess.run
        logins = []
        original = self.token.read_bytes()

        def run(command, **kwargs):
            if command[-1].endswith("/browser-login.py"):
                environment = kwargs["env"]
                logins.append(environment)
                target = Path(environment["ONEDRIVE_ACCOUNT_DIR"]) / "token.json"
                target.write_text(json.dumps({"credential_id": "fixture-credential"}))
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        with patch.object(setup.subprocess, "run", side_effect=run), \
                patch.object(setup, "bootstrap", side_effect=lambda account: self.source(account=account)):
            profile = setup.configure_account(self.args(
                account="personal", library="personal", client_id="fixture-client", tenant="consumers"))["profile"]
        self.assertEqual(len(logins), 1)
        self.assertEqual(logins[0]["ONEDRIVE_TENANT_ID"], "consumers")
        self.assertEqual(logins[0]["ONEDRIVE_SCOPES"], setup.DEFAULT_SCOPES)
        self.assertEqual(logins[0]["ONEDRIVE_ACCOUNT_DIR"], profile["credentialDir"])
        self.assertNotEqual(profile["credentialDir"], str(self.token.parent))
        self.assertEqual(self.token.read_bytes(), original)

    @unittest.skipUnless(platform.system() == "Linux" and platform.machine() == "x86_64",
                         "the bundled native test host requires Linux x86-64")
    def test_real_bootstrap_host_is_private_and_cleaned_up_without_cloud_requests(self):
        before = self.token.read_bytes()
        with setup.bootstrap(self.account) as (url, env, secret):
            auth = base64.b64encode(("daemon:" + secret).encode()).decode()
            request = urllib.request.Request(url, method="OPTIONS", headers={"Authorization": "Basic " + auth})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=10) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("PROPFIND", response.headers["Allow"])
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        self.assertFalse(env.parent.exists())
        self.assertFalse(setup.probe_daemon(url, timeout=0.5))
        self.assertEqual(self.token.read_bytes(), before)

    def test_discovery_requires_a_valid_explicit_choice(self):
        response = {"ok": True, "libraries": [
            {"name": "First", "webUrl": "https://example.sharepoint.com/one", "selector": "drives/one"},
            {"name": "Second", "webUrl": "https://example.sharepoint.com/two", "selector": "drives/two"},
        ]}
        args = self.args(selector=None, site_url="https://example.sharepoint.com/sites/Test")
        with patch.object(setup, "checked_json", return_value=response) as request:
            with patch("builtins.input", return_value="2"):
                self.assertEqual(setup.select_library("http://127.0.0.1:8790/", "fixture", args), "drives/two")
            self.assertIn("siteUrl=", request.call_args.args[0])
            with patch("builtins.input", return_value=""):
                with self.assertRaisesRegex(ValueError, "No valid library"):
                    setup.select_library("http://127.0.0.1:8790/", "fixture", args)

    @contextmanager
    def activation(self):
        fstab = self.home / "fstab"
        fstab.write_text("# existing mount entries\n")
        davfs = self.home / "davfs.conf"
        davfs.write_text("dav_group fixture-group\n")
        helper = self.home / "mount.davfs"
        helper.write_text("fixture, never executed")
        helper.chmod(0o4755)
        secrets_file = self.home / ".davfs2/secrets"
        secrets_file.parent.mkdir()
        secrets_file.write_text("http://127.0.0.1:8123/ daemon existing-fixture-secret\n")
        mount = self.home / "OneDrive-Libraries/documents"
        profile = setup.registry()["libraries"][0]
        mounted = False
        commands = []
        real_run = subprocess.run

        def run(command, **kwargs):
            nonlocal mounted
            commands.append(command)
            if command[:3] == ["sudo", "cp", "-p"]:
                self.assertEqual(command[-2], str(fstab))
                shutil.copyfile(command[-2], command[-1])
            elif command[:3] == ["sudo", "tee", "-a"]:
                self.assertEqual(command[-1], str(fstab))
                with fstab.open("a") as handle:
                    handle.write(kwargs["input"])
            elif command[:3] == ["sudo", "usermod", "-aG"]:
                pass
            elif command[0] == "systemctl":
                if command[-1] == profile["mountServiceUnit"]:
                    mounted = True
            elif command[0] in ("omarchy", "omarchy-shell"):
                pass
            elif command[0] == sys.executable:
                return real_run(command, **kwargs)
            else:
                self.fail(f"Unexpected activation command: {command}")
            return subprocess.CompletedProcess(command, 0)

        with ExitStack() as stack:
            stack.enter_context(patch.object(setup, "FSTAB", fstab))
            stack.enter_context(patch.object(setup, "DAVFS_CONFIG", davfs))
            stack.enter_context(patch.object(setup, "MOUNT_HELPER", helper))
            stack.enter_context(patch.object(setup.grp, "getgrnam", return_value=SimpleNamespace(gr_gid=os.getgid())))
            stack.enter_context(patch.object(setup.os.path, "ismount", side_effect=lambda path: Path(path) == mount and mounted))
            stack.enter_context(patch.object(setup.subprocess, "run", side_effect=run))
            stack.enter_context(patch.object(setup.subprocess, "check_output", return_value=profile["url"] + "\n"))
            stack.enter_context(patch.object(setup, "probe_daemon", return_value=True))
            stack.enter_context(patch.object(setup, "checked_json", return_value={"ok": True, "accessVerified": True}))
            yield fstab, secrets_file, commands

    def test_activation_preserves_existing_entries_and_can_be_repeated(self):
        self.create_library()
        with self.activation() as (fstab, secret_file, commands), patch("builtins.input", return_value="yes"):
            setup.activate_library("documents")
            first = (fstab.read_bytes(), secret_file.read_bytes())
            setup.activate_library("documents")
            self.assertEqual((fstab.read_bytes(), secret_file.read_bytes()), first)
            self.assertTrue(secret_file.read_text().startswith("http://127.0.0.1:8123/ daemon existing-fixture-secret\n"))
            self.assertEqual(secret_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(sum(cmd[:3] == ["sudo", "tee", "-a"] for cmd in commands), 1)
            self.assertEqual(next(self.home.glob("fstab.onedrive-davfs-*.bak")).read_text(), "# existing mount entries\n")
            self.assertIn(["omarchy", "bar", "set", "onedrive-sync", "backend", "wasm_davfs"], commands)

    def test_cancelled_activation_does_not_modify_mounts_credentials_or_services(self):
        self.create_library()
        with self.activation() as (fstab, secret_file, commands), patch("builtins.input", return_value="no"):
            before = fstab.read_bytes(), secret_file.read_bytes()
            with self.assertRaisesRegex(ValueError, "cancelled"):
                setup.activate_library("documents")
            self.assertEqual((fstab.read_bytes(), secret_file.read_bytes()), before)
            self.assertEqual(commands, [])

    def test_customized_unit_is_not_overwritten(self):
        self.create_library()
        unit = self.home / ".config/systemd/user/onedrive-davfs-documents.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("custom configuration")
        with self.activation() as (_, _, commands):
            with self.assertRaisesRegex(ValueError, "customized service"):
                setup.activate_library("documents")
            self.assertEqual(commands, [])
        self.assertEqual(unit.read_text(), "custom configuration")

    def test_new_mount_group_membership_requires_relogin_before_activation(self):
        self.create_library()
        with self.activation() as (fstab, secret_file, commands), patch("builtins.input", return_value="yes"):
            before = fstab.read_bytes(), secret_file.read_bytes()
            group = max(os.getgroups() + [os.getgid()]) + 1
            with patch.object(setup.grp, "getgrnam", return_value=SimpleNamespace(gr_gid=group)):
                with self.assertRaisesRegex(RuntimeError, "Log out/in"):
                    setup.activate_library("documents")
            self.assertEqual((fstab.read_bytes(), secret_file.read_bytes()), before)
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][:4], ["sudo", "usermod", "-aG", "fixture-group"])

    def test_unverified_access_does_not_mount_or_reconfigure_the_widget(self):
        self.create_library()
        with self.activation() as (_, _, commands), patch("builtins.input", return_value="yes"), \
                patch.object(setup, "checked_json", return_value={"ok": True, "accessVerified": False}):
            with self.assertRaisesRegex(RuntimeError, "not verified cloud access"):
                setup.activate_library("documents")
            self.assertFalse(any(command[0] == "omarchy" or command[-1].endswith("-mount.service")
                                 for command in commands))

    def test_entry_merge_refuses_a_later_conflict_even_after_an_exact_match(self):
        entry = "http://127.0.0.1:8790/ /example davfs noauto,user 0 0\n"
        conflict = entry + "http://127.0.0.1:8790/ /other davfs noauto,user 0 0\n"
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            setup.merged_entry(conflict, entry, (0, 1))

    def test_widget_selection_is_not_guessed_when_missing_or_ambiguous(self):
        settings = self.home / ".config/omarchy/shell.json"
        for count in (0, 2):
            with self.subTest(count=count):
                settings.write_text(json.dumps({"bar": {"layout": {
                    "right": [{"id": "onedrive-sync"}] * count}}}))
                with self.assertRaisesRegex(ValueError, "exactly one"):
                    setup.check_widget()


@unittest.skipIf(os.geteuid() == 0, "setup must run as a normal user")
class BashSetupTests(unittest.TestCase):
    def test_install_orders_plugin_packages_and_backend_and_refuses_active_units(self):
        script = Path(__file__).with_name("setup.sh")
        bash = shutil.which("bash")
        for mode in ("binary", "source", "active"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                commands = root / "commands"
                scripts = root / "scripts"
                scripts.mkdir()
                shutil.copyfile(script, scripts / "setup.sh")
                (scripts / "install_backend.py").write_text(f"def check_platform(): return {mode!r}\n")
                (scripts / "install_backend.sh").write_text('printf "backend\\n" >> "$COMMAND_LOG"\n')
                commands.mkdir()
                for name, body in {
                    "omarchy": 'printf "omarchy %s\\n" "$*" >> "$COMMAND_LOG"\n',
                    "systemctl": 'if [[ "$SETUP_TEST_MODE" == active ]]; then echo "onedrive-davfs-sync.timer loaded active waiting"; fi\n',
                }.items():
                    target = commands / name
                    target.write_text("#!/bin/bash\n" + body)
                    target.chmod(0o755)
                (commands / "python3").symlink_to(sys.executable)
                log = root / "commands.log"
                env = dict(os.environ, HOME=str(root / "home"), PATH=f"{commands}:/usr/bin:/bin",
                           COMMAND_LOG=str(log), SETUP_TEST_MODE=mode)
                result = subprocess.run([bash, str(scripts / "setup.sh"), "install"],
                                        env=env, capture_output=True, text=True, timeout=15)
                if mode == "active":
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("nothing was changed", result.stderr)
                    self.assertFalse(log.exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    calls = log.read_text().splitlines()
                    plugin = "omarchy plugin add https://github.com/uhansen/onedrive-sync.git --enable"
                    runtime = "omarchy pkg add python curl openssl xdg-utils davfs2 python-gobject"
                    self.assertLess(calls.index(plugin), calls.index(runtime))
                    self.assertLess(calls.index(runtime), calls.index("backend"))
                    self.assertEqual("omarchy pkg add base-devel cmake pkgconf" in calls, mode == "source")


if __name__ == "__main__":
    unittest.main()
