#!/usr/bin/env python3
import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


TRANSFER_PATTERNS = (
    "copied",
    "moved",
    "renamed",
    "deleted",
    "transferred",
    "uploaded",
    "downloaded",
    "synced",
    "writeback",
)


def command_output(command, timeout=4):
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def normalize_rc_addr(addr):
    value = str(addr or "").strip()
    if value == "":
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value.rstrip("/")
    return "http://" + value.rstrip("/")


def rc_call(addr, endpoint, payload=None):
    base = normalize_rc_addr(addr)
    if base == "":
        return None
    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        base + "/" + endpoint.lstrip("/"),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2.5) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def remote_has_token(remote_name):
    config_path = Path.home() / ".config" / "rclone" / "rclone.conf"
    if not config_path.exists():
        return False
    parser = configparser.RawConfigParser()
    try:
        parser.read(config_path, encoding="utf-8")
    except (configparser.Error, OSError):
        return False
    if not parser.has_section(remote_name):
        return False
    token = parser.get(remote_name, "token", fallback="").strip()
    return token != ""


def service_exists(unit):
    if shutil.which("systemctl") is None:
        return False
    code, output = command_output(["systemctl", "--user", "show", unit, "--property=LoadState", "--value"])
    if code != 0:
        return False
    return output.strip() not in ("", "not-found", "masked")


def service_running(unit):
    if shutil.which("systemctl") is None:
        return False
    code, output = command_output(["systemctl", "--user", "is-active", unit])
    return code == 0 and output.strip() == "active"


def mount_is_ready(path_text):
    expanded = os.path.expanduser(path_text or "")
    return expanded, os.path.ismount(expanded)


def last_sync_ts(unit):
    if shutil.which("journalctl") is None:
        return 0
    code, output = command_output(["journalctl", "--user", "-u", unit, "-n", "200", "--no-pager", "-o", "short-unix"], timeout=5)
    if code != 0 or output == "":
        return 0
    found = 0
    for line in output.splitlines():
        match = re.match(r"^(\d+(?:\.\d+)?)\s+(.*)$", line)
        if not match:
            continue
        lowered = match.group(2).lower()
        if any(token in lowered for token in TRANSFER_PATTERNS):
            try:
                found = int(float(match.group(1)))
            except ValueError:
                continue
    return found


def extract_pending(core_stats, mount_point):
    items = []
    seen = set()
    expanded = os.path.expanduser(mount_point or "")
    for key in ("transferring", "checking"):
        values = core_stats.get(key)
        if not isinstance(values, list):
            continue
        for row in values:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("remote") or row.get("src") or row.get("dst") or "").strip()
            identity = (key, name)
            if identity in seen:
                continue
            seen.add(identity)
            path = os.path.join(expanded, name) if expanded and name else expanded
            items.append({
                "name": name,
                "path": path,
                "stage": key,
                "sizeBytes": int(float(row.get("size") or row.get("bytes") or 0) or 0),
                "speed": float(row.get("speed") or 0) or 0,
            })
    return items


def bytes_queued(core_stats, vfs_stats, pending_files):
    candidates = []
    for source in (core_stats, vfs_stats):
        if isinstance(source, dict):
            for key in ("bytesQueued", "queuedBytes", "uploadsQueuedBytes", "writebackBytes", "renameQueueBytes"):
                value = source.get(key)
                if isinstance(value, (int, float)):
                    candidates.append(int(value))
    if candidates:
        return max(candidates)
    return sum(int(item.get("sizeBytes") or 0) for item in pending_files)


def transferred_bytes(core_stats):
    for key in ("bytes", "totalBytes", "transferredBytes"):
        value = core_stats.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def collect_errors(core_stats):
    errors = []
    last_error = str(core_stats.get("lastError") or "").strip()
    if last_error:
        errors.append(last_error)
    if core_stats.get("fatalError"):
        errors.append("rclone reported a fatal error")
    return errors


def build_status(remote_name, mount_point, service_unit, rc_addr, limit):
    rclone = shutil.which("rclone")
    installed = rclone is not None
    expanded_mount, mounted = mount_is_ready(mount_point)
    authenticated = remote_has_token(remote_name)
    service_ok = service_exists(service_unit)
    running = service_running(service_unit) if service_ok else False

    core_stats = rc_call(rc_addr, "core/stats", {}) if running and installed else None
    vfs_stats = rc_call(rc_addr, "vfs/stats", {}) if running and installed else None

    pending_files = extract_pending(core_stats or {}, expanded_mount)[:limit]
    errors = collect_errors(core_stats or {})
    last_sync = last_sync_ts(service_unit) if running else 0
    pending_count = len(pending_files)
    queued = bytes_queued(core_stats or {}, vfs_stats or {}, pending_files)
    transferred = transferred_bytes(core_stats or {})

    if not installed:
        status_text = "rclone is not installed"
    elif not service_ok:
        status_text = "Service unit not found"
    elif running and mounted:
        status_text = "Mounted"
    elif running and not mounted:
        status_text = "Service active, mount missing"
    elif authenticated:
        status_text = "Stopped"
    else:
        status_text = "Needs configuration"

    return {
        "ok": True,
        "installed": installed,
        "serviceExists": service_ok,
        "running": running,
        "mounted": mounted,
        "authenticated": authenticated,
        "statusText": status_text,
        "remoteName": remote_name,
        "mountPoint": mount_point,
        "mountPointExpanded": expanded_mount,
        "lastSyncTs": last_sync,
        "pendingFiles": pending_files,
        "pendingCount": pending_count,
        "bytesQueued": queued,
        "transferredBytes": transferred,
        "errorCount": len(errors),
        "errors": errors,
        "rcAvailable": core_stats is not None,
    }


def main():
    remote_name = sys.argv[1] if len(sys.argv) > 1 else "onedrive"
    mount_point = sys.argv[2] if len(sys.argv) > 2 else "~/OneDrive"
    service_unit = sys.argv[3] if len(sys.argv) > 3 else "rclone-onedrive.service"
    rc_addr = sys.argv[4] if len(sys.argv) > 4 else "127.0.0.1:5572"
    try:
        limit = max(1, min(100, int(sys.argv[5]))) if len(sys.argv) > 5 else 25
    except ValueError:
        limit = 25
    payload = build_status(remote_name, mount_point, service_unit, rc_addr, limit)
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
