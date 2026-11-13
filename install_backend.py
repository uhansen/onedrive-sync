#!/usr/bin/env python3
"""Install the bundled onedrive-davfs backend without changing account configuration."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

BUNDLE_DIR = Path(__file__).resolve().parent / "artifacts"
MAX_FILE_SIZE = 128 * 1024 * 1024
MAX_TOTAL_SIZE = 200 * 1024 * 1024


def check_platform():
    system, machine = platform.system(), platform.machine().lower()
    if system == "Linux" and machine in ("arm64", "aarch64"):
        return "source"
    if system != "Linux" or machine not in ("x86_64", "amd64"):
        raise ValueError("This installer targets Omarchy Linux on x86-64 or ARM64, including Apple Silicon running Linux. macOS is not supported.")
    libc, version = platform.libc_ver()
    if libc != "glibc" or tuple(int(part) for part in version.split(".")[:2]) < (2, 38):
        return "source"
    return "binary"


def safe_path(name, source=False):
    path = PurePosixPath(name)
    allowed = (name == "source/LICENSE" or name.startswith("source/host/")) if source else (
        name == "bin/onedrive-davfs-host" or name.startswith("share/onedrive-davfs/"))
    if (str(path) != name or path.is_absolute() or ".." in path.parts
            or not allowed):
        raise ValueError(f"Invalid bundle path: {name}")
    return Path(*path.parts)


def unpack_bundle(bundle_dir, destination, source=False):
    manifest = json.loads((bundle_dir / ("source.json" if source else "backend.json")).read_text())
    if manifest.get("format") != 1 or manifest.get("platform") != ("source" if source else "linux-x86_64"):
        raise ValueError("Unsupported backend bundle manifest.")
    archive = bundle_dir / ("onedrive-davfs-host-source.tar.gz" if source else "onedrive-davfs-linux-x86_64.tar.gz")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("Backend archive checksum mismatch; no files installed.")
    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise ValueError("Backend bundle has no files.")
    seen = set()
    total = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            relative = safe_path(member.name, source)
            if not member.isfile() or member.name in seen or member.name not in files:
                raise ValueError(f"Unexpected bundle entry: {member.name}")
            total += member.size
            if member.size > MAX_FILE_SIZE or total > MAX_TOTAL_SIZE:
                raise ValueError("Backend bundle exceeds its size limit.")
            data = bundle.extractfile(member).read()
            expected = files[member.name]
            if (len(data) != expected["size"]
                    or hashlib.sha256(data).hexdigest() != expected["sha256"]
                    or expected["mode"] not in (0o644, 0o755)):
                raise ValueError(f"Backend file verification failed: {member.name}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(expected["mode"])
            seen.add(member.name)
    required = "source/host/Cargo.toml" if source else "bin/onedrive-davfs-host"
    if seen != set(files) or required not in seen:
        raise ValueError("Backend bundle is incomplete.")
    return manifest


def build_host(staged, bundle_dir, manifest):
    if shutil.which("cargo") is None:
        raise ValueError("This platform requires Rust/cargo and native build tools. See SETUP.md.")
    source = unpack_bundle(bundle_dir, staged, source=True)
    if source["revision"] != manifest["revision"]:
        raise ValueError("Host source and portable backend artifacts have different revisions.")
    build_directory = staged / "build"
    print("Building the bundled native host for this machine (Cargo may download dependencies)...", flush=True)
    subprocess.run(["cargo", "build", "--locked", "--release",
                    "--manifest-path", str(staged / "source/host/Cargo.toml"),
                    "--target-dir", str(build_directory)], check=True)
    target = staged / "bin/onedrive-davfs-host"
    shutil.copyfile(build_directory / "release/onedrive-davfs-host", target)
    target.chmod(0o755)
    manifest["files"]["bin/onedrive-davfs-host"] = {
        "size": target.stat().st_size,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "mode": 0o755,
    }


def check_destination(target):
    for path in (target, *target.parents):
        if path.is_symlink():
            raise ValueError(f"Refusing to overwrite or follow a symlink: {path}")
    if target.exists() and not target.is_file():
        raise ValueError(f"Installation target is not a regular file: {target}")
    for parent in target.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"Installation parent is not a directory: {parent}")


def install(prefix, bundle_dir=BUNDLE_DIR, build_from_source=False):
    mode = check_platform()
    with tempfile.TemporaryDirectory(prefix="onedrive-backend-") as directory:
        staged = Path(directory)
        manifest = unpack_bundle(bundle_dir, staged)
        if mode == "source" or build_from_source:
            build_host(staged, bundle_dir, manifest)
        subprocess.run([str(staged / "bin/onedrive-davfs-host"), "--help"],
                       check=True, capture_output=True, text=True, timeout=30)
        targets = [(name, prefix / safe_path(name)) for name in manifest["files"]]
        for _, target in targets:
            check_destination(target)
        for name, target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".backend-", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as handle, (staged / name).open("rb") as source:
                    shutil.copyfileobj(source, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                    os.fchmod(handle.fileno(), manifest["files"][name]["mode"])
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local",
                        help="Installation prefix (default: ~/.local; generated profile units require this default)")
    parser.add_argument("--build-from-source", action="store_true",
                        help="Build the host from bundled source (automatic on ARM64 Linux)")
    args = parser.parse_args()
    try:
        if os.geteuid() == 0:
            raise ValueError("Run as your normal user, without sudo.")
        if shutil.which("omarchy") is None:
            raise ValueError("This installer requires an existing Omarchy installation (omarchy must be on PATH).")
        prefix = args.prefix.expanduser().absolute()
        manifest = install(prefix, build_from_source=args.build_from_source)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError,
            subprocess.SubprocessError) as error:
        print(f"Backend installation failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        return 1
    print(f"Installed onedrive-davfs {manifest['revision']} to {prefix}")
    print("Credentials, account settings, mounts and services were not changed.")
    print("Existing processes were not restarted. Configure accounts using SETUP.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
