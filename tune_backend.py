#!/usr/bin/env python3
"""Render opt-in tuning, or explicitly apply/restore one user's selected library."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import time

from profiles_davfs import load_profiles
from tree_davfs import join_url, load_basic_secret, request_json


def digest(data):
    return hashlib.sha256(data).hexdigest()


def single_path(value):
    path = Path(value).expanduser().absolute()
    if any(c in str(path) for c in "\x00\r\n"):
        raise ValueError("Paths must be single lines")
    return path


def safe_path(path):
    """Do not follow symlinks, including symlinked parent directories."""
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise ValueError(f"Refusing symlinked configuration path: {candidate}")
    if path.exists() and (not path.is_file() or path.stat().st_uid != os.getuid()):
        raise ValueError(f"Configuration is not a user-owned regular file: {path}")


def atomic_write(path, data, mode=0o600):
    safe_path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = path.with_name("." + path.name + "-" + secrets.token_hex(8))
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_file(path):
    safe_path(path)
    return path.read_bytes() if path.exists() else None


def environment_line(path):
    value = str(path).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'[Service]\nEnvironmentFile="{value}"\n'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=single_path, help="NEW permanent directory for render and backup")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--apply", action="store_true", help="Render, back up and apply to this user's units")
    actions.add_argument("--restore", type=single_path, metavar="BACKUP", help="Restore an apply backup")
    parser.add_argument("--preset", choices=("low-latency",))
    parser.add_argument("--library", help="Explicit library ID; omit for legacy units only")
    parser.add_argument("--mount", type=single_path, help="Exact davfs mountpoint")
    for flag in ("poll-seconds", "cache-mib", "upload-delay", "dir-refresh", "max-upload-mib"):
        parser.add_argument("--" + flag, type=int)
    parser.add_argument("--perf-log", action="store_true")
    parser.add_argument("--cached-dav-reads", action="store_true")
    args = parser.parse_args(argv)
    if args.restore:
        if any(value not in (None, False) for key, value in vars(args).items() if key != "restore"):
            parser.error("--restore takes no tuning, output or target options")
        return args
    if args.output is None:
        parser.error("--output is required")
    if args.library is not None and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", args.library):
        parser.error("invalid library ID")
    for name, lower, upper in [
        ("poll_seconds", 1, 3600), ("cache_mib", 50, 1048576),
        ("upload_delay", 0, 3600), ("dir_refresh", 1, 3600), ("max_upload_mib", 1, 256000),
    ]:
        value = getattr(args, name)
        if value is not None and not lower <= value <= upper:
            parser.error(f"--{name.replace('_', '-')} must be between {lower} and {upper}")
    if args.preset:
        for key, expected in (("poll_seconds", 1), ("cache_mib", 512), ("upload_delay", 0), ("dir_refresh", 1)):
            if getattr(args, key) not in (None, expected):
                parser.error("--preset low-latency cannot be combined with conflicting tuning values")
            setattr(args, key, expected)
        if args.max_upload_mib is not None or args.cached_dav_reads:
            parser.error("--preset low-latency does not change upload limits or enable cached DAV reads")
        args.perf_log = True
    if any(getattr(args, key) is not None for key in ("cache_mib", "upload_delay", "dir_refresh")) and not args.mount:
        parser.error("--mount is required for davfs settings")
    if args.mount and any(c in str(args.mount) for c in '\t[]"\\#'):
        parser.error("mountpoint contains unsupported davfs syntax")
    if not any((args.poll_seconds is not None, args.cache_mib is not None, args.upload_delay is not None,
                args.dir_refresh is not None, args.max_upload_mib is not None, args.perf_log, args.cached_dav_reads)):
        parser.error("select at least one tuning option")
    return args


def unit_name(args):
    return "onedrive-davfs" + ("-" + args.library if args.library else "")


def davfs_options(args):
    result = {key: value for key, value in {
        "cache_size": args.cache_mib, "delay_upload": args.upload_delay, "dir_refresh": args.dir_refresh,
    }.items() if value is not None}
    if args.preset:
        result["file_refresh"] = 0
    return result


def render_files(args, env_path):
    unit = unit_name(args)
    environment = []
    if args.max_upload_mib is not None:
        environment.append(f"ONEDRIVE_MAX_UPLOAD_BYTES={args.max_upload_mib * 1024 * 1024}")
    if args.perf_log:
        environment.append("ONEDRIVE_PERF_LOG=1")
    if args.cached_dav_reads or args.preset:
        environment.append(f"ONEDRIVE_CACHED_DAV_READS={int(args.cached_dav_reads)}")
    files = {}
    if environment:
        files["performance.env"] = "\n".join(environment) + "\n"
        files[f"systemd-user/{unit}.service.d/90-performance.conf"] = environment_line(env_path)
    if args.poll_seconds is not None:
        if args.preset:
            timer = ("[Timer]\nOnActiveSec=\nOnBootSec=\nOnStartupSec=\nOnUnitActiveSec=\n"
                     "OnUnitInactiveSec=\nOnCalendar=\nOnActiveSec=1s\nOnUnitInactiveSec=1s\n"
                     "OnClockChange=false\nOnTimezoneChange=false\n"
                     "AccuracySec=100ms\nRandomizedDelaySec=0\nPersistent=false\n")
        else:
            timer = ("[Timer]\nOnActiveSec=\nOnStartupSec=\nOnUnitInactiveSec=\nOnCalendar=\nOnBootSec=\n"
                     f"OnUnitActiveSec=\nOnBootSec=15s\nOnUnitActiveSec={args.poll_seconds}s\nAccuracySec=1s\n")
        files[f"systemd-user/{unit}-sync.timer.d/90-performance.conf"] = timer
    options = davfs_options(args)
    if options:
        files["davfs2.conf.snippet"] = f'"[{args.mount}]"\n' + "".join(f"{key} {value}\n" for key, value in options.items())
    return files


def render(args):
    files = render_files(args, args.output / "performance.env")
    safe_path(args.output)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for relative, content in files.items():
        atomic_write(args.output / relative, content.encode())
    return files


def merge_davfs(content, mount, options):
    lines = content.splitlines(keepends=True)
    start = end = None
    for index, line in enumerate(lines):
        text = line.strip()
        if not text.startswith(("[", '"[')):
            continue
        # davfs2 quotes the entire section token, brackets included. Unlike
        # shell syntax, it rejects quotes embedded in an unquoted token.
        token = r'(?:"(?:[^"\\]|\\.)*"|(?:[^ \t"\\#]|\\[ \t"\\#])+)'
        if not re.fullmatch(token + r"\s*(?:#.*)?", text):
            raise ValueError("Invalid davfs section; review davfs2.conf manually")
        lexer = shlex.shlex(text, posix=True)
        lexer.whitespace_split = True
        lexer.quotes = '"'
        fields = list(lexer)
        if len(fields) != 1 or not fields[0].startswith("[") or not fields[0].endswith("]"):
            raise ValueError("Invalid davfs mount section")
        if start is not None and end is None:
            end = index
        if fields[0][1:-1] == str(mount):
            if start is not None:
                raise ValueError("Duplicate davfs mount section; review it manually")
            start = index + 1
            end = None
    if start is None:
        return content + ("" if not content or content.endswith("\n") else "\n") + (
            f'"[{mount}]"\n' + "".join(f"{key} {value}\n" for key, value in options.items()))
    end = len(lines) if end is None else end
    result, seen = [], set()
    for line in lines[start:end]:
        fields = line.lstrip().split(maxsplit=1)
        if fields and fields[0] in options:
            key = fields[0]
            if key not in seen:
                result.append(f"{key} {options[key]}\n")
                seen.add(key)
        else:
            result.append(line)
    if result and not result[-1].endswith("\n"):
        result[-1] += "\n"
    result.extend(f"{key} {value}\n" for key, value in options.items() if key not in seen)
    return "".join(lines[:start] + result + lines[end:])


def check_platform():
    if platform.system() != "Linux" or os.getuid() == 0 or shutil.which("omarchy") is None:
        raise ValueError("Apply/restore requires Omarchy Linux as a normal user (no sudo)")


def systemctl(*args, check=True, timeout=180):
    result = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"systemctl {' '.join(args)} failed; inspect the user service journal")
    return result


def target_for(args):
    home, unit = Path.home(), unit_name(args)
    target = {
        "unit": unit, "url": "http://127.0.0.1:8765/",
        "env": str(home / ".config/onedrive-davfs/env"),
        "mount": str(args.mount or home / "OneDrive"), "preset": args.preset,
    }
    if args.library:
        profiles, _ = load_profiles(str(home / ".config/onedrive-davfs/profiles.json"))
        profile = next((p for p in profiles if p["id"] == args.library), None)
        if (profile is None or profile.get("daemonServiceUnit") != unit + ".service"
                or profile.get("mountServiceUnit") != unit + "-mount.service"):
            raise ValueError("Select an enabled library with the standard explicit library units")
        if args.mount and str(args.mount) != profile["mountPoint"]:
            raise ValueError("--mount must match the selected library's registered mountpoint")
        target.update(url=profile["url"], env=profile["envFile"], mount=profile["mountPoint"])
    return target


def units(target):
    name = target["unit"]
    return [name + ".service", name + "-mount.service", name + "-sync.service", name + "-sync.timer"]


def state(target):
    result = {}
    for unit in units(target):
        loaded = systemctl("show", unit, "--property=LoadState", "--value").stdout.strip()
        active = systemctl("show", unit, "--property=ActiveState", "--value").stdout.strip()
        sync_running = unit == units(target)[2] and active in ("active", "activating")
        if loaded != "loaded" or (active not in ("active", "inactive") and not sync_running):
            raise ValueError(f"Unit must be loaded and settled before tuning: {unit}")
        result[unit] = active == "active" and not sync_running
    return result


def wait_sync(target, timeout=180):
    deadline = time.monotonic() + timeout
    while True:
        value = systemctl("show", units(target)[2], "--property=ActiveState", "--value").stdout.strip()
        if value == "inactive":
            return
        if value not in ("active", "activating", "deactivating", "reloading"):
            raise RuntimeError("Sync service failed; inspect the journal before tuning")
        if time.monotonic() >= deadline:
            raise RuntimeError("Sync is still busy; services were not forcibly stopped")
        time.sleep(0.25)


def status(target):
    secret, error = load_basic_secret(target["env"])
    if not secret:
        raise ValueError(error or "Missing backend authentication")
    return request_json(join_url(target["url"], "/_status"), secret, timeout=4)


def require_capability(document, target):
    capabilities = document.get("capabilities") or {}
    if target.get("preset") and (
            not isinstance(capabilities, dict) or capabilities.get("persistedGraphCooldown") is not True):
        raise ValueError("low-latency requires a backend advertising capabilities.persistedGraphCooldown=true")


def wait_ready(target, verified=False, timeout=30):
    deadline = time.monotonic() + timeout
    while True:
        document = status(target)
        if document.get("ok") is True:
            require_capability(document, target)
            if not verified or (document.get("accessVerified") is True and not document.get("lastSyncError")):
                return document
        if time.monotonic() >= deadline:
            raise RuntimeError("Backend did not become authenticated/cloud-access verified")
        time.sleep(0.25)


def verify_mount(target, readable=False):
    mount = target["mount"]
    if not os.path.ismount(mount):
        raise RuntimeError("Selected library is not mounted")
    result = subprocess.run(
        ["findmnt", "--noheadings", "--output", "SOURCE", "--mountpoint", mount],
        capture_output=True, text=True, check=True, timeout=10)
    if result.stdout.strip().rstrip("/") != target["url"].rstrip("/"):
        raise ValueError("Mountpoint belongs to a different source")
    if readable:
        subprocess.run([sys.executable, "-c", "import os,sys; os.listdir(sys.argv[1])", mount],
                       check=True, capture_output=True, timeout=30)


def quiesce(target):
    daemon, mount, sync, timer = units(target)
    systemctl("stop", timer)
    wait_sync(target)
    if os.path.ismount(target["mount"]):
        verify_mount(target)
        # Unmount directly first: a failing ExecStop must never make systemd kill
        # davfs or applications on a busy mount. No force/lazy unmount is used.
        subprocess.run(["/usr/bin/umount", "--", target["mount"]], check=True, capture_output=True, timeout=120)
        if os.path.ismount(target["mount"]):
            raise RuntimeError("Mount is still busy; leaving daemon and mount service running")
    systemctl("stop", mount, check=False)
    systemctl("reset-failed", mount, check=False)
    systemctl("stop", sync)
    systemctl("stop", daemon)


def restore_services(target, previous):
    daemon, mount, sync, timer = units(target)
    if previous[daemon]:
        systemctl("start", daemon)
        wait_ready(dict(target, preset=None))
    if previous[mount] and not os.path.ismount(target["mount"]):
        systemctl("reset-failed", mount, check=False)
        systemctl("start", mount)
        verify_mount(target)
    if previous[timer]:
        systemctl("start", timer)
    # Sync is allowed to finish before snapshots; no transient job is replayed.


def owned_paths(target):
    home, unit = Path.home(), target["unit"]
    root = home / ".config/onedrive-davfs/tuning" / unit
    return root / "performance.env", root / "owned.json"


def plan(args, target, originals=None):
    env, manifest = owned_paths(target)
    files = render_files(args, env)
    proposed = {}
    for relative, content in files.items():
        if relative == "performance.env":
            proposed[env] = content.encode()
        elif relative.startswith("systemd-user/"):
            proposed[Path.home() / ".config/systemd/user" / relative.removeprefix("systemd-user/")] = content.encode()
    recorded = read_file(manifest)
    known = json.loads(recorded) if recorded is not None else {}
    if not isinstance(known, dict):
        raise ValueError("Invalid tuning ownership manifest")
    for path, data in proposed.items():
        existing = read_file(path)
        if originals is not None:
            originals[path] = existing
        if existing is not None and existing != data and known.get(str(path)) != digest(existing):
            raise ValueError(f"Refusing customized owned file: {path}")
        if path == env and existing is not None:
            updates = dict(line.split("=", 1) for line in data.decode().splitlines())
            merged = []
            for line in existing.decode().splitlines():
                key = line.split("=", 1)[0]
                merged.append(key + "=" + updates.pop(key) if key in updates else line)
            merged.extend(key + "=" + value for key, value in updates.items())
            proposed[path] = ("\n".join(merged) + "\n").encode()
    # Retain hashes for unchanged owned files from earlier partial tuning.
    known.update({str(path): digest(data) for path, data in proposed.items()})
    proposed[manifest] = (json.dumps(known, indent=2) + "\n").encode()
    if originals is not None:
        originals[manifest] = recorded
    options = davfs_options(args)
    if options:
        path = Path.home() / ".davfs2/davfs2.conf"
        original = read_file(path)
        if originals is not None:
            originals[path] = original
        proposed[path] = merge_davfs((original or b"").decode(), target["mount"], options).encode()
    return proposed


def make_backup(directory, target, previous, proposed, originals=None):
    directory.mkdir(mode=0o700)
    entries = []
    for number, (path, data) in enumerate(proposed.items()):
        before = read_file(path)
        if originals is not None and before != originals[path]:
            raise ValueError(f"Configuration changed while planning; refusing to overwrite: {path}")
        entry = {"path": str(path), "before": None, "after": digest(data), "mode": None}
        if before is not None:
            entry.update(before=f"{number}.before", mode=stat.S_IMODE(path.stat().st_mode))
            atomic_write(directory / entry["before"], before)
            entry["beforeSha256"] = digest(before)
        entries.append(entry)
    document = {"version": 1, "uid": os.getuid(), "home": str(Path.home()), "target": target,
                "services": previous, "files": entries}
    atomic_write(directory / "metadata.json", (json.dumps(document, indent=2) + "\n").encode())
    return document


def restore_files(directory, document):
    for entry in reversed(document["files"]):
        path = Path(entry["path"])
        if entry["before"] is None:
            safe_path(path)
            path.unlink(missing_ok=True)
        else:
            data = (directory / entry["before"]).read_bytes()
            if digest(data) != entry["beforeSha256"]:
                raise ValueError("Backup file checksum mismatch")
            atomic_write(path, data, entry["mode"])


def apply(args):
    check_platform()
    target = target_for(args)
    wait_ready(target, verified=True)
    verify_mount(target, readable=True)
    originals = {}
    proposed = plan(args, target, originals)
    # Stop only the selected timer; allow an in-progress tick to complete.
    previous = state(target)
    if not previous[units(target)[0]] or not previous[units(target)[1]]:
        raise ValueError("Apply requires the selected daemon and mount service to be active")
    backup = args.output / "backup"
    document = make_backup(backup, target, previous, proposed, originals)
    print(f"Backup: {backup}", flush=True)
    changed = False
    try:
        quiesce(target)
        for entry in document["files"]:
            current = read_file(Path(entry["path"]))
            expected = entry.get("beforeSha256")
            if (digest(current) if current is not None else None) != expected:
                raise ValueError("Configuration changed during apply; refusing to overwrite it")
        changed = True
        for path, data in proposed.items():
            atomic_write(path, data)
        systemctl("daemon-reload")
        daemon, mount, sync, timer = units(target)
        systemctl("start", daemon)
        wait_ready(target)
        systemctl("start", sync)
        wait_ready(target, verified=True)
        systemctl("start", mount)
        verify_mount(target, readable=True)
        systemctl("start", timer)
    except BaseException as error:
        try:
            if changed:
                quiesce(target)
                restore_files(backup, document)
                systemctl("daemon-reload")
            restore_services(target, previous)
        except BaseException as recovery:
            raise RuntimeError(f"Apply failed ({error}); recovery needs attention ({recovery}). Backup: {backup}") from error
        raise RuntimeError(f"Apply failed; previous files/services restored. Backup: {backup}. {error}") from error
    print(f"Applied and verified {target['unit']}. Restore: bash tune_backend.sh --restore {shlex.quote(str(backup))}")


def allowed_restore_paths(target):
    if not re.fullmatch(r"onedrive-davfs(?:-[a-z0-9][a-z0-9_-]{0,63})?", target["unit"]):
        raise ValueError("Invalid backup unit")
    env, manifest = owned_paths(target)
    root = Path.home() / ".config/systemd/user"
    return {env, manifest, Path.home() / ".davfs2/davfs2.conf",
            root / (target["unit"] + ".service.d/90-performance.conf"),
            root / (target["unit"] + "-sync.timer.d/90-performance.conf")}


def restore(directory):
    check_platform()
    safe_path(directory / "metadata.json")
    document = json.loads((directory / "metadata.json").read_bytes())
    if document.get("version") != 1 or document.get("uid") != os.getuid() or document.get("home") != str(Path.home()):
        raise ValueError("Backup belongs to a different user/home or unsupported format")
    target = document["target"]
    allowed = allowed_restore_paths(target)
    if (set(document["services"]) != set(units(target))
            or any(type(value) is not bool for value in document["services"].values())):
        raise ValueError("Invalid backup service states")
    seen = set()
    for entry in document["files"]:
        path = Path(entry["path"])
        if path not in allowed or path in seen:
            raise ValueError("Backup contains an unexpected/duplicate configuration path")
        seen.add(path)
        current = read_file(path)
        before = entry["before"]
        if before is not None:
            if not re.fullmatch(r"[0-9]+\.before", before):
                raise ValueError("Invalid backup data path")
            safe_path(directory / before)
            if digest((directory / before).read_bytes()) != entry["beforeSha256"]:
                raise ValueError("Backup checksum mismatch")
        if current is None or digest(current) != entry["after"]:
            raise ValueError(f"Configuration changed since apply; refusing restore: {path}")
    # A failed restore gets its own undo snapshot; original backups are retained.
    current_services = state(target)
    proposed = {Path(entry["path"]): read_file(Path(entry["path"])) for entry in document["files"]}
    undo = directory / ("restore-undo-" + secrets.token_hex(6))
    undo_document = make_backup(undo, target, current_services, proposed)
    changed = False
    try:
        quiesce(target)
        for path, expected in proposed.items():
            if read_file(path) != expected:
                raise ValueError("Configuration changed during restore; refusing to overwrite it")
        changed = True
        restore_files(directory, document)
        systemctl("daemon-reload")
        restore_services(target, document["services"])
        if document["services"][units(target)[0]]:
            systemctl("start", units(target)[2])
            wait_ready(dict(target, preset=None), verified=True)
        if document["services"][units(target)[1]]:
            verify_mount(target, readable=True)
    except BaseException:
        if changed:
            quiesce(target)
            restore_files(undo, undo_document)
            systemctl("daemon-reload")
        restore_services(target, current_services)
        raise
    print(f"Restored previous files/services. Backup retained: {directory}")


@contextmanager
def transaction_lock():
    path = Path.home() / ".config/onedrive-davfs/tuning.lock"
    safe_path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another tuning apply/restore is already running") from None
        yield
    finally:
        os.close(fd)


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.apply or args.restore:
            check_platform()
        if args.restore:
            with transaction_lock():
                restore(args.restore)
        else:
            render(args)
            if args.apply:
                with transaction_lock():
                    apply(args)
            else:
                print(f"Rendered tuning in {args.output}. Nothing applied; see SETUP.md optional tuning.")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Tuning failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
