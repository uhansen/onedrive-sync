#!/usr/bin/env bash
# Render opt-in settings; never edit running services, credentials or mounts.
set -euo pipefail
command -v python3 >/dev/null || { echo "Requires Python 3: omarchy pkg add python" >&2; exit 1; }
exec python3 - "$@" <<'PY'
import argparse
from pathlib import Path
import re
import sys

parser = argparse.ArgumentParser(description="Render optional Omarchy OneDrive tuning into a NEW directory; nothing is applied.")
parser.add_argument("--output", type=Path, required=True, help="New permanent directory for generated files")
parser.add_argument("--library", help="Unified library ID; omit for the legacy single-library service")
parser.add_argument("--mount", type=Path, help="Exact davfs mountpoint (required for davfs options)")
parser.add_argument("--poll-seconds", type=int)
parser.add_argument("--cache-mib", type=int)
parser.add_argument("--upload-delay", type=int)
parser.add_argument("--dir-refresh", type=int)
parser.add_argument("--max-upload-mib", type=int)
parser.add_argument("--perf-log", action="store_true")
parser.add_argument("--cached-dav-reads", action="store_true")
args = parser.parse_args()
if args.library is not None and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", args.library):
    parser.error("invalid library ID")
for name, lower, upper in [
    ("poll_seconds", 1, 3600), ("cache_mib", 50, 1048576),
    ("upload_delay", 0, 3600), ("dir_refresh", 1, 3600), ("max_upload_mib", 1, 256000),
]:
    value = getattr(args, name)
    if value is not None and not lower <= value <= upper:
        parser.error(f"--{name.replace('_', '-')} must be between {lower} and {upper}")
davfs = {key: value for key, value in {
    "cache_size": args.cache_mib, "delay_upload": args.upload_delay, "dir_refresh": args.dir_refresh,
}.items() if value is not None}
if davfs and not args.mount:
    parser.error("--mount is required for davfs settings")
mount = str(args.mount.expanduser().absolute()) if args.mount else ""
if any(char in mount for char in '\n\r[]"\\#'):
    parser.error("mountpoint contains unsupported davfs syntax")
output = args.output.expanduser().absolute()
if any(char in str(output) for char in '\n\r'):
    parser.error("output path must be a single line")
unit = "onedrive-davfs" + ("-" + args.library if args.library else "")
environment = []
if args.max_upload_mib is not None:
    environment.append(f"ONEDRIVE_MAX_UPLOAD_BYTES={args.max_upload_mib * 1024 * 1024}")
if args.perf_log:
    environment.append("ONEDRIVE_PERF_LOG=1")
if args.cached_dav_reads:
    environment.append("ONEDRIVE_CACHED_DAV_READS=1")
files = {}
if environment:
    files["performance.env"] = "\n".join(environment) + "\n"
    quoted = str(output / "performance.env").replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    files[f"systemd-user/{unit}.service.d/90-performance.conf"] = f'[Service]\nEnvironmentFile="{quoted}"\n'
if args.poll_seconds is not None:
    files[f"systemd-user/{unit}-sync.timer.d/90-performance.conf"] = (
        "[Timer]\nOnUnitActiveSec=\nOnBootSec=15s\n"
        f"OnUnitActiveSec={args.poll_seconds}s\nAccuracySec=1s\n")
if davfs:
    files["davfs2.conf.snippet"] = f'["{mount}"]\n' + "".join(f"{key} {value}\n" for key, value in davfs.items())
if not files:
    parser.error("select at least one tuning option")
try:
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for relative, content in files.items():
        target = output / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("x") as handle:
            handle.write(content)
        target.chmod(0o600)
except OSError as error:
    print(f"Cannot render tuning: {error}. No running settings were changed.", file=sys.stderr)
    raise SystemExit(1)
print(f"Rendered {len(files)} files in {output}. Nothing applied; see SETUP.md optional tuning.")
PY
