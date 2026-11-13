# Bundled onedrive-davfs backend

`backend.json` records the source revision, platform, archive checksum, and
per-file hashes/modes. The binary archive includes the native host, Wasm
component, matching helpers, upstream MIT license, and service templates.
`source.json` and `onedrive-davfs-host-source.tar.gz` include the matching host
source and Cargo lockfile for local native builds, plus the component sources,
helpers and tests so uncommitted source snapshots remain inspectable.

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

For installation, follow the
[Bash installer instructions](../SETUP.md#2-install-the-backend-via-bash).
Checksums detect corruption; they do not replace trusting the repository that
supplies archives/manifests.

CI includes a native Linux ARM64 build/install job; it runs after pushing the
workflow. This checks the backend on ARM64, not Apple-specific kernel/drivers.

## Rebuild the bundle

Check out `base_revision` (or `revision` for older bundles) in a clean backend checkout. Build
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

For explicitly approved local changes that have not been committed, use
`--allow-dirty` after rebuilding/testing. Such bundles are marked
`source_dirty: true`, retain `base_revision`, record `source_tree_sha256`, and
use `BASE+source.HASH` as their revision; they do not pretend to be that clean
Git commit. The matching complete source snapshot is included in the source
archive. Rebuild that snapshot, not just the base commit, to reproduce changes.
The installer rejects mismatched binary/component and native-source identities.
