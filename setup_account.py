#!/usr/bin/env python3
"""Coordinate existing native helpers; never copy credentials between accounts."""

import argparse
from contextlib import contextmanager
import grp
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time

from profiles_davfs import load_profiles
from status_davfs import probe_daemon
from tree_davfs import join_url, load_basic_secret, request_json

DEFAULT_SCOPES = "offline_access Files.ReadWrite.All User.Read"
FSTAB = Path("/etc/fstab")
DAVFS_CONFIG = Path("/etc/davfs2/davfs2.conf")
MOUNT_HELPER = Path("/usr/bin/mount.davfs")


def identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("IDs must contain 1-64 letters, digits, underscores or hyphens")
    return value


def registry_path():
    return Path.home() / ".config/onedrive-davfs/profiles.json"


def tools_path():
    return Path.home() / ".local/share/onedrive-davfs/tools"


def setup_command(*args):
    return shlex.join(("bash", str(Path(__file__).resolve().with_name("setup.sh")), *args))


def registry():
    path = registry_path()
    if not path.exists():
        return {"version": 1, "accounts": [], "libraries": []}
    document = json.loads(path.read_text())
    if (not isinstance(document, dict) or document.get("version") != 1 or not isinstance(document.get("accounts"), list)
            or not isinstance(document.get("libraries"), list)):
        raise ValueError("Invalid native account/library registry")
    return document


def run_profiles(*args):
    result = subprocess.run(
        [sys.executable, str(tools_path() / "profiles.py"), *args],
        capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stdout.strip() or result.stderr.strip() or "Profile setup failed")
    data = json.loads(result.stdout)
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "Profile setup failed"))
    return data


def checked_json(url, secret):
    data = request_json(url, secret, timeout=60)
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "Backend verification failed"))
    return data


@contextmanager
def bootstrap(account):
    with tempfile.TemporaryDirectory(prefix="onedrive-setup-") as directory:
        root = Path(directory)
        state = root / "state"
        state.mkdir(mode=0o700)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        secret = secrets.token_urlsafe(32)
        values = {
            "ONEDRIVE_CLIENT_ID": account["clientId"],
            "ONEDRIVE_TENANT_ID": account["tenantId"],
            "ONEDRIVE_SCOPES": account["scopes"],
            "ONEDRIVE_DRIVE_BASE": "me/drive",
            "ONEDRIVE_BASIC_AUTH_SECRET": secret,
            "ONEDRIVE_INDEX_ENABLED": "1",
        }
        if any(any(c in value for c in "\r\n\x00\"'\\") for value in values.values()):
            raise ValueError("Invalid account environment value")
        env_file = root / "env"
        env_file.write_text("".join(f'{key}="{value}"\n' for key, value in values.items()))
        env_file.chmod(0o600)
        url = f"http://127.0.0.1:{port}/"
        command = [
            str(Path.home() / ".local/bin/onedrive-davfs-host"),
            "--addr", f"127.0.0.1:{port}", "--state-dir", str(state),
            "--account-dir", account["credentialDir"],
            "--component", str(Path.home() / ".local/share/onedrive-davfs/onedrive_davfs.wasm"),
        ]
        with (root / "host.log").open("w+") as log:
            process = subprocess.Popen(command, env=dict(os.environ, **values),
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while not probe_daemon(url, timeout=0.5):
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError("Bootstrap host stopped: " + log.read(4096))
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Bootstrap host did not become ready")
                    time.sleep(0.2)
                yield url, env_file, secret
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def select_library(url, secret, args):
    query = None
    if args.site_url:
        query = {"siteUrl": args.site_url}
    elif args.group_id:
        query = {"groupId": args.group_id}
    if query is None:
        return args.selector or "me/drive"
    libraries = checked_json(join_url(url, "/_libraries", query), secret).get("libraries", [])
    if not libraries:
        raise ValueError("No accessible libraries found; check the site/group and permissions")
    for number, library in enumerate(libraries, 1):
        print(f"{number}. {json.dumps(library['name'], ensure_ascii=True)} "
              f"({json.dumps(library['webUrl'], ensure_ascii=True)})")
    choice = input("Library number (no default): ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(libraries):
        raise ValueError("No valid library selected; no library was saved")
    return libraries[int(choice) - 1]["selector"]


def configure_account(args):
    identifier(args.account)
    identifier(args.library)
    document = registry()
    if any(library["id"] == args.library for library in document["libraries"]):
        raise ValueError(f"Library ID already exists; resume with: {setup_command('activate', '--library', args.library)}")
    account = next((a for a in document["accounts"] if a["id"] == args.account), None)
    if account is None:
        if not args.client_id or not args.tenant:
            raise ValueError("A new account requires --client-id and --tenant")
        scopes = DEFAULT_SCOPES + (" Sites.Read.All" if args.sites or args.site_url else "")
        account = run_profiles("account", "--id", args.account, "--client-id", args.client_id,
                               "--tenant", args.tenant, "--scopes", scopes)["account"]
    else:
        if ((args.client_id and args.client_id != account["clientId"])
                or (args.tenant and args.tenant != account["tenantId"])):
            raise ValueError("Existing account configuration differs; use a separate account ID")
        if (args.sites or args.site_url) and "Sites.Read.All" not in account["scopes"].split():
            raise ValueError("This account lacks Sites.Read.All consent; use a known --selector drives/ID instead")
    credential_dir = Path(account["credentialDir"])
    if not (credential_dir / "token.json").is_file():
        environment = dict(os.environ, ONEDRIVE_ACCOUNT_DIR=str(credential_dir),
                           ONEDRIVE_CLIENT_ID=account["clientId"],
                           ONEDRIVE_TENANT_ID=account["tenantId"],
                           ONEDRIVE_SCOPES=account["scopes"])
        helper = "device-login.py" if args.login == "device" else "browser-login.py"
        subprocess.run([sys.executable, str(tools_path() / helper)], env=environment, check=True)
    with bootstrap(account) as (url, env_file, secret):
        selector = select_library(url, secret, args)
        result = run_profiles(
            "library", "--account", account["id"], "--source-url", url,
            "--source-env", str(env_file), "--selector", selector,
            "--id", args.library, "--name", args.name or args.library)
    print(f"Saved library {args.library}.")
    if not args.no_activate:
        activate_library(args.library)
    else:
        print(f"Not activated. Next: {setup_command('activate', '--library', args.library)}")
    return result


def merged_entry(content, entry, keys):
    expected = shlex.split(entry)
    found = False
    for line in content.splitlines():
        fields = shlex.split(line, comments=True)
        if fields and any(len(fields) > key and fields[key] == expected[key] for key in keys):
            if fields != expected:
                raise ValueError("Conflicting existing mount/credential entry; review it manually")
            found = True
    if found:
        return content
    return content + ("" if not content or content.endswith("\n") else "\n") + entry


def confirm(message):
    if input(message + " Type yes to continue: ").strip() != "yes":
        raise ValueError("Activation cancelled; generated account/library files were preserved")


def check_widget():
    settings = json.loads((Path.home() / ".config/omarchy/shell.json").read_text())
    if not isinstance(settings, dict) or not isinstance(settings.get("bar"), dict):
        raise ValueError("Configure the OneDrive bar widget before activation")
    layout = settings["bar"].get("layout", {})
    if not isinstance(layout, dict) or any(not isinstance(section, list) for section in layout.values()):
        raise ValueError("Invalid bar layout; review the widget placement before activation")
    widgets = [widget for section in layout.values() for widget in section
               if isinstance(widget, dict) and widget.get("id") == "onedrive-sync"]
    if len(widgets) != 1:
        raise ValueError("Automatic setup requires exactly one OneDrive bar widget; review its placement/settings manually")


def activate_library(library_id):
    identifier(library_id)
    check_widget()
    profiles, _ = load_profiles(str(registry_path()))
    profile = next((p for p in profiles if p["id"] == library_id), None)
    if profile is None:
        raise ValueError("Enabled library profile not found")
    folder = registry_path().parent / "library-data" / library_id
    if Path(profile["envFile"]) != folder / "env":
        raise ValueError("Activation requires a library generated by the bundled profiles helper")
    mount = Path(profile["mountPoint"])
    if mount.is_symlink() or (mount.exists() and not os.path.ismount(mount) and any(mount.iterdir())):
        raise ValueError("Refusing to mount over existing files or a symlink")
    if os.path.ismount(mount):
        source = subprocess.check_output(
            ["findmnt", "--noheadings", "--output", "SOURCE", "--mountpoint", str(mount)], text=True).strip()
        if source != profile["url"]:
            raise ValueError("Mountpoint is already used by another filesystem")
    secret, error = load_basic_secret(profile["envFile"])
    if not secret:
        raise ValueError(error)
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,}", secret):
        raise ValueError("Invalid generated WebDAV secret")
    escaped_mount = str(mount).replace("\\", "\\134").replace(" ", "\\040").replace("\t", "\\011")
    entry = f"{profile['url']} {escaped_mount} davfs noauto,user,rw,noexec,nosuid,nodev 0 0\n"
    if (folder / "fstab.entry").read_text() != entry:
        raise ValueError("Generated fstab entry does not match the library")
    fstab = FSTAB
    original_fstab = fstab.read_text()
    updated_fstab = merged_entry(original_fstab, entry, (0, 1))
    davfs_dir = Path.home() / ".davfs2"
    secret_file = davfs_dir / "secrets"
    if davfs_dir.is_symlink() or secret_file.is_symlink():
        raise ValueError("Refusing symlinked davfs credential paths")
    old_secrets = secret_file.read_text() if secret_file.exists() else ""
    secret_entry = f"{profile['url']} daemon {secret}\n"
    if (folder / "davfs-secrets.entry").read_text() != secret_entry:
        raise ValueError("Generated credential entry does not match the library")
    updated_secrets = merged_entry(old_secrets, secret_entry, (0,))
    for line in old_secrets.splitlines():
        fields = shlex.split(line, comments=True)
        if fields and fields[0] == str(mount):
            raise ValueError("An existing mountpoint credential needs manual review")
    units = [profile["daemonServiceUnit"], profile["mountServiceUnit"],
             f"onedrive-davfs-{library_id}-sync.service", f"onedrive-davfs-{library_id}-sync.timer"]
    unit_dir = Path.home() / ".config/systemd/user"
    for unit in units:
        source, target = folder / unit, unit_dir / unit
        if source.is_symlink() or not source.is_file() or target.is_symlink():
            raise ValueError("Invalid generated or installed service path")
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError(f"Refusing to overwrite customized service: {unit}")
    if not MOUNT_HELPER.stat().st_mode & stat.S_ISUID:
        raise ValueError("davfs2 user mounting is not enabled; check the Omarchy davfs2 package configuration")
    confirm(f"Activate {library_id}: merge its fstab/credentials, enable its services and "
            "switch the OneDrive widget to unified libraries? Existing mounts are not migrated.")
    group = "network"
    for line in DAVFS_CONFIG.read_text().splitlines():
        fields = shlex.split(line, comments=True)
        if fields and fields[0] == "dav_group":
            if len(fields) != 2:
                raise ValueError("Invalid system davfs group configuration")
            group = fields[1]
    if grp.getgrnam(group).gr_gid not in {os.getgid(), *os.getgroups()}:
        subprocess.run(["sudo", "usermod", "-aG", group, pwd.getpwuid(os.getuid()).pw_name], check=True)
        raise RuntimeError(f"Added user to {group}. Log out/in, then rerun: {setup_command('activate', '--library', library_id)}")
    if updated_fstab != original_fstab:
        if fstab.read_text() != original_fstab:
            raise ValueError("fstab changed during setup; rerun activation after reviewing it")
        backup = str(fstab.with_name(f"{fstab.name}.onedrive-davfs-{library_id}-{secrets.token_hex(4)}.bak"))
        subprocess.run(["sudo", "cp", "-p", "--", str(fstab), backup], check=True)
        subprocess.run(["sudo", "tee", "-a", str(fstab)],
                       input=updated_fstab[len(original_fstab):], text=True,
                       stdout=subprocess.DEVNULL, check=True)
        print(f"Preserved previous fstab in {backup}")
    davfs_dir.mkdir(mode=0o700, exist_ok=True)
    davfs_dir.chmod(0o700)
    if (secret_file.read_text() if secret_file.exists() else "") != old_secrets:
        raise ValueError("davfs credentials changed during setup; rerun activation after reviewing them")
    fd, temporary = tempfile.mkstemp(prefix=".secrets-", dir=davfs_dir)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(updated_secrets)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, secret_file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    mount.mkdir(parents=True, exist_ok=True)
    unit_dir.mkdir(parents=True, exist_ok=True)
    for unit in units:
        shutil.copyfile(folder / unit, unit_dir / unit)
        (unit_dir / unit).chmod(0o644)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", profile["daemonServiceUnit"]], check=True)
    deadline = time.monotonic() + 30
    while not probe_daemon(profile["url"], timeout=0.5):
        if time.monotonic() >= deadline:
            raise RuntimeError("Library host did not become ready; inspect its user service journal")
        time.sleep(0.2)
    subprocess.run(["systemctl", "--user", "enable", "--now", units[3]], check=True)
    subprocess.run(["systemctl", "--user", "start", units[2]], check=True, timeout=120)
    status = checked_json(join_url(profile["url"], "/_status"), secret)
    if not status.get("accessVerified") or status.get("lastSyncError"):
        raise RuntimeError(status.get("lastSyncError") or "Backend has not verified cloud access")
    subprocess.run(["systemctl", "--user", "enable", "--now", profile["mountServiceUnit"]], check=True)
    if not os.path.ismount(mount):
        raise RuntimeError("Mount service started but the library is not mounted")
    subprocess.run([sys.executable, "-c", "import os,sys; os.listdir(sys.argv[1])", str(mount)],
                   check=True, timeout=30)
    for key, value in (("backend", "wasm_davfs"), ("profilesFile", str(registry_path())),
                       ("profileSetupCommand", str(tools_path() / "profiles.py"))):
        subprocess.run(["omarchy", "bar", "set", "onedrive-sync", key, value], check=True)
    subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=True)
    print(f"Verified cloud access and readable mount: {mount}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    account = commands.add_parser("account", help="Register/sign in and configure a library")
    account.add_argument("--account", required=True, help="Account ID; reused for additional libraries")
    account.add_argument("--library", required=True, help="New unique library ID")
    account.add_argument("--client-id", help="Approved public-client application ID; required for a new account")
    account.add_argument("--tenant", help="consumers for personal; tenant ID for Microsoft 365")
    account.add_argument("--name", help="Library display name")
    account.add_argument("--sites", action="store_true", help="Request optional Sites.Read.All consent for a new account")
    scope = account.add_mutually_exclusive_group()
    scope.add_argument("--selector", help="me/drive (default) or drives/ID")
    scope.add_argument("--site-url", help="Discover libraries in a specific SharePoint site")
    scope.add_argument("--group-id", help="Discover libraries for a specific Microsoft 365 group")
    account.add_argument("--login", choices=("browser", "device"), default="browser")
    account.add_argument("--no-activate", action="store_true", help="Only generate configuration")
    activate = commands.add_parser("activate", help="Resume activation of a generated library")
    activate.add_argument("--library", required=True)
    args = parser.parse_args(argv)
    try:
        if os.geteuid() == 0 or sys.platform != "linux" or shutil.which("omarchy") is None:
            raise ValueError("Run as a normal user on Omarchy Linux")
        os.umask(0o077)
        if not (tools_path() / "profiles.py").is_file():
            raise ValueError(f"Install the backend first: {setup_command('install')}")
        if args.command == "account":
            configure_account(args)
        else:
            activate_library(args.library)
    except (OSError, ValueError, RuntimeError, EOFError, KeyError, subprocess.SubprocessError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
