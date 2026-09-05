#!/usr/bin/env python3
"""Read-only status helper for the onedrive-davfs (Wasm WebDAV) backend.

Mirrors status.py's contract and JSON shape so Model.js/Service.qml/Panel.qml
can stay mostly backend-agnostic. This script never reads OAuth token
contents -- only the non-secret `expires_at` timestamp from token.json -- and
never sends credentials anywhere. The reachability probe is a bare HTTP
request with no Authorization header; any response (even 401/403) counts as
"reachable", only a connection failure/timeout counts as unreachable.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def command_output(command, timeout=4):
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def service_exists(unit):
    if not unit or shutil.which("systemctl") is None:
        return False
    code, output = command_output(["systemctl", "--user", "show", unit, "--property=LoadState", "--value"])
    if code != 0:
        return False
    return output.strip() not in ("", "not-found", "masked")


def service_running(unit):
    if not unit or shutil.which("systemctl") is None:
        return False
    code, output = command_output(["systemctl", "--user", "is-active", unit])
    return code == 0 and output.strip() == "active"


def mount_is_ready(path_text):
    expanded = os.path.expanduser(path_text or "")
    return expanded, (expanded != "" and os.path.ismount(expanded))


def read_token_expiry(state_dir):
    """Returns (token_present, expires_at) reading only the non-secret
    expiry timestamp; refresh_token/access_token values are never touched."""
    token_path = Path(os.path.expanduser(state_dir or "")) / "token.json"
    if not token_path.exists():
        return False, 0
    try:
        with open(token_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return False, 0
    if not isinstance(data, dict) or "refresh_token" not in data:
        return False, 0
    try:
        expires_at = int(data.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    return True, expires_at


def probe_daemon(url, timeout=1.5):
    """Bare reachability probe -- no Authorization header, no credentials.
    Any HTTP response (including 401/403) means the daemon is reachable;
    a connection error/timeout means it is not."""
    if not url:
        return False
    request = urllib.request.Request(url, method="GET")
    try:
        urllib.request.urlopen(request, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        # Server responded (even with an error status) -- still reachable.
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def build_status(mount_point, daemon_unit, mount_unit, state_dir, davfs_url):
    davfs2_installed = shutil.which("mount.davfs") is not None
    expanded_mount, mounted = mount_is_ready(mount_point)

    daemon_exists = service_exists(daemon_unit)
    daemon_running = service_running(daemon_unit) if daemon_exists else False
    mount_service_exists = service_exists(mount_unit) if mount_unit else False
    mount_service_running = service_running(mount_unit) if mount_service_exists else False

    token_present, expires_at = read_token_expiry(state_dir)
    now = int(time.time())
    token_expires_in_sec = max(0, expires_at - now) if token_present and expires_at > 0 else 0
    authenticated = token_present and (expires_at == 0 or expires_at > now)

    daemon_reachable = probe_daemon(davfs_url) if daemon_running else False

    errors = []
    if daemon_exists and not daemon_running:
        errors.append("onedrive-davfs service is not running")
    if not token_present:
        errors.append("No token.json found; run the reconnect command")
    elif not authenticated:
        errors.append("OneDrive token has expired; run the reconnect command")
    if daemon_running and not daemon_reachable:
        errors.append("onedrive-davfs is running but not responding")

    if not daemon_exists:
        status_text = "onedrive-davfs service not found"
    elif not daemon_running:
        status_text = "Daemon stopped"
    elif not token_present:
        status_text = "Needs authentication"
    elif not authenticated:
        status_text = "Token expired"
    elif not mounted:
        status_text = "Daemon active, mount missing"
    elif not daemon_reachable:
        status_text = "Daemon active, not responding"
    else:
        status_text = "Mounted"

    return {
        "ok": True,
        "backend": "wasm_davfs",
        "installed": davfs2_installed,
        "serviceExists": daemon_exists,
        "running": daemon_running,
        "mountServiceExists": mount_service_exists,
        "mountServiceRunning": mount_service_running,
        "mounted": mounted,
        "authenticated": authenticated,
        "statusText": status_text,
        "remoteName": "",
        "mountPoint": mount_point,
        "mountPointExpanded": expanded_mount,
        "lastSyncTs": 0,
        "pendingFiles": [],
        "pendingCount": 0,
        "bytesQueued": 0,
        "transferredBytes": 0,
        "errorCount": len(errors),
        "errors": errors,
        "rcAvailable": False,
        "tokenExpiresInSec": token_expires_in_sec,
        "daemonReachable": daemon_reachable,
    }


def main():
    mount_point = sys.argv[1] if len(sys.argv) > 1 else "~/OneDrive"
    daemon_unit = sys.argv[2] if len(sys.argv) > 2 else "onedrive-davfs.service"
    mount_unit = sys.argv[3] if len(sys.argv) > 3 else "onedrive-davfs-mount.service"
    state_dir = sys.argv[4] if len(sys.argv) > 4 else "~/.local/state/onedrive-davfs"
    davfs_url = sys.argv[5] if len(sys.argv) > 5 else "http://127.0.0.1:8765/"
    payload = build_status(mount_point, daemon_unit, mount_unit, state_dir, davfs_url)
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
