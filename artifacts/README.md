# Bundled onedrive-davfs backend

`backend.json` records the source revision, platform, archive checksum, and
per-file hashes/modes. The binary archive includes the native host, Wasm
component, matching helpers, upstream MIT license, and service templates.
`source.json` and `onedrive-davfs-host-source.tar.gz` include the matching host
source and Cargo lockfile for local native builds.

| Platform | Installation |
| --- | --- |
| Linux x86-64, glibc 2.38+ | Bundled native executable; needs `libgcc_s` and `libm`. |
| Linux ARM64 (`aarch64`/`arm64`) | Compile host from bundled source on the target machine. |
| Apple Silicon running Omarchy Linux (`arm64`/`aarch64`) | Same ARM64 native source-build path. |
| Linux x86-64 with older glibc or musl | Compile host from bundled source. |

This installer targets Omarchy Linux only, not macOS or other desktop
distributions. The kernel must already boot and support the hardware; this
installer does not install Omarchy, Asahi Linux, firmware or hardware drivers.
The user-facing command requires `omarchy` on PATH and rejects non-Linux hosts.

Source builds need Rust/cargo, a C/C++ toolchain, CMake, and enough memory/disk
for Wasmtime. Cargo downloads locked dependencies unless already cached. The
Wasm component and Python helpers are shared across architectures; no local
Wasm compilation is needed. 32-bit ARM and macOS are not supported by
this installer.

The installer checks the platform, verifies archives/files, and runs the
staged native host's `--help` before installing. Checksums detect corruption;
they do not replace trusting the repository that supplies archives/manifests.

Install with `python3 install_backend.py` from the repository root.
It writes only bundled files under `~/.local`, not credentials, fstab or user
service configuration. Re-running replaces these backend files, not account
data. It does not restart an already running host. Service templates are
installed under `~/.local/share/onedrive-davfs/systemd/` for reference, not
activated automatically. Generated profile units use the default `~/.local`
paths; a custom `--prefix` requires custom service configuration.

Use `--build-from-source` to exercise the source path on Linux x86-64 too.
CI includes a native Linux ARM64 build/install job; it runs after pushing the
workflow. This checks the backend on ARM64, not Apple-specific kernel/drivers.

## Rebuild the bundle

Check out the revision in `backend.json` in a clean backend checkout. Build
and test both artifacts before packaging:

```bash
cd /path/to/onedrive-davfs
rustup target add wasm32-wasip2
cargo build --locked --target wasm32-wasip2 --release
cargo build --locked --manifest-path host/Cargo.toml --release
cargo test --locked --lib
cargo test --locked --manifest-path host/Cargo.toml
```

From this repository:

```bash
python3 tools/build_backend_bundle.py /path/to/onedrive-davfs
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_install_backend
```

Build on a compatible Linux x86-64 machine. The packaging tool records source
identity, but does not prove that stale build outputs match that source.
If changing the supported platform or minimum glibc, verify the binary's
actual requirements and update the installer and documentation together.
