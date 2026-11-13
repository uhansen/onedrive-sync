#!/usr/bin/env python3
"""Package already-built, matching onedrive-davfs artifacts for the installer."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile


def source_snapshot(source):
    paths = subprocess.check_output(
        ["git", "-C", str(source), "ls-files", "--cached", "--others", "--exclude-standard",
         "LICENSE", "Cargo.toml", "Cargo.lock", "src", "wit", "host/Cargo.toml",
         "host/Cargo.lock", "host/src", "tools", "systemd"], text=True).splitlines()
    files = {}
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        if "__pycache__" in Path(path).parts:
            continue
        original = source / path
        if original.is_symlink() or not original.is_file():
            raise SystemExit(f"Source input must be a regular file: {path}")
        data = original.read_bytes()
        files[path] = data
        digest.update(path.encode() + b"\0" + hashlib.sha256(data).digest())
    return files, digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Clean backend checkout with release builds")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "artifacts")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="Bundle an uncommitted source snapshot with its own content identity")
    args = parser.parse_args()
    source = args.source.resolve()
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    inputs, source_hash = source_snapshot(source)
    dirty = bool(subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"]))
    tracked = set(subprocess.check_output(
        ["git", "-C", str(source), "ls-files"], text=True).splitlines())
    dirty = dirty or bool(set(inputs) - tracked)
    if dirty and not args.allow_dirty:
        raise SystemExit("Backend tracked files must be clean before packaging.")
    base_revision = revision
    if dirty:
        revision += "+source." + source_hash[:16]
    paths = {
        "bin/onedrive-davfs-host": ("host/target/release/onedrive-davfs-host", 0o755),
        "share/onedrive-davfs/onedrive_davfs.wasm": ("target/wasm32-wasip2/release/onedrive_davfs.wasm", 0o644),
        "share/onedrive-davfs/LICENSE": ("LICENSE", 0o644),
    }
    for helper in ("auth_common.py", "browser-login.py", "device-login.py",
                   "device-code-login.sh", "profiles.py", "profile-sync.py", "sync-tick.sh"):
        paths["share/onedrive-davfs/tools/" + helper] = ("tools/" + helper, 0o755)
    for helper in ("auth_common.py", "device-login.py", "device-code-login.sh", "sync-tick.sh"):
        paths["share/onedrive-davfs/" + helper] = ("tools/" + helper, 0o755)
    for unit in ("onedrive-davfs.service", "onedrive-davfs-mount.service",
                 "onedrive-davfs-sync.service", "onedrive-davfs-sync.timer"):
        paths["share/onedrive-davfs/systemd/" + unit] = ("systemd/" + unit, 0o644)
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / "onedrive-davfs-linux-x86_64.tar.gz"
    files = {}
    with archive.open("wb") as handle, gzip.GzipFile(fileobj=handle, mode="wb", mtime=0, filename="") as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as bundle:
            for name, (original, mode) in sorted(paths.items()):
                data = (source / original).read_bytes()
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = mode
                bundle.addfile(member, io.BytesIO(data))
                files[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mode": mode}
    manifest = {
        "format": 1, "platform": "linux-x86_64", "minimum_glibc": "2.38",
        "source": "https://github.com/uhansen/onedrive-davfs",
        "revision": revision, "license": "MIT",
        "base_revision": base_revision, "source_dirty": dirty, "source_tree_sha256": source_hash,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "files": files,
    }
    (args.output / "backend.json").write_text(json.dumps(manifest, indent=2) + "\n")
    source_archive = args.output / "onedrive-davfs-host-source.tar.gz"
    source_files = {}
    with source_archive.open("wb") as handle, gzip.GzipFile(fileobj=handle, mode="wb", mtime=0, filename="") as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as bundle:
            for original, data in sorted(inputs.items()):
                name = "source/" + original
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = 0o644
                bundle.addfile(member, io.BytesIO(data))
                source_files[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mode": 0o644}
    source_manifest = dict(manifest, platform="source", files=source_files,
                           sha256=hashlib.sha256(source_archive.read_bytes()).hexdigest())
    source_manifest.pop("minimum_glibc")
    (args.output / "source.json").write_text(json.dumps(source_manifest, indent=2) + "\n")
    if source_snapshot(source)[1] != source_hash:
        raise SystemExit("Backend sources changed during packaging; discard the generated bundle and retry.")
    print(f"Packaged {revision}: {archive}")


if __name__ == "__main__":
    main()
