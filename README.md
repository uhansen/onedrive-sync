# onedrive-sync

`onedrive-sync` is an Omarchy shell plugin that adds a OneDrive status icon,
details panel, and a few safe control actions to the bar.

It is intentionally a **thin UI layer** over external daemons -- it supports
two interchangeable backends, selected with the `backend` setting:

- **`rclone_mount`** (default) -- rclone performs OAuth, token storage,
  network I/O, and file transfer; `systemd --user` owns the mount lifecycle.
- **`wasm_davfs`** -- the [`onedrive-davfs`](https://github.com/uhansen/onedrive-davfs)
  Wasm WebDAV daemon performs OAuth and Graph API calls inside a
  capability-sandboxed `wasm32-wasip2` component; `davfs2` mounts the
  resulting WebDAV endpoint.

In both cases, **the plugin only polls status, launches a sign-in helper,
and issues one-shot control commands** -- it never touches OAuth tokens,
client secrets, or network I/O directly. No OAuth tokens or network code
live in QML.

## Features

- Bar icon showing idle / syncing / paused / error states
- Panel with remote/unit, mount path, auth state, and (backend-dependent)
  last sync time, pending count, and queued bytes
- `Sync now` action using rclone's local RC endpoint (`rclone_mount` only --
  WebDAV/davfs2 has no equivalent discrete sync job, so this action is
  hidden for `wasm_davfs`)
- `Open folder` action
- `Reconnect` action:
  - `rclone_mount`: shells out to `rclone config reconnect ...`
  - `wasm_davfs`: opens a floating terminal (via Omarchy's own
    `omarchy-launch-floating-terminal-with-presentation` helper) running the
    user-configured `reconnectCommand`
- Graceful fallback states when the backend tooling, service unit, or mount
  are missing

## Prerequisites

This plugin is **observe-only**. It assumes the backend is already set up.

### Backend: `rclone_mount` (default)

1. An `rclone` remote called `onedrive`
2. A mount point at `~/OneDrive`
3. A user service called `rclone-onedrive.service`
4. rclone RC enabled locally (default in this plugin: `127.0.0.1:5572`)

Initial OAuth setup should be completed outside the plugin with `rclone config`.
The in-plugin **Reconnect** button is for re-authorization, not first-time setup.

### Backend: `wasm_davfs`

1. Build and run [`onedrive-davfs`](https://github.com/uhansen/onedrive-davfs)
   per its own README -- registering an Azure AD app, running its
   `tools/device-code-login.sh` once, and enabling its systemd units
   (`onedrive-davfs.service` and, optionally, `onedrive-davfs-mount.service`)
2. Mount the daemon's WebDAV endpoint at your chosen mount point with `davfs2`
3. In this plugin's settings, set:
   - `backend` = `wasm_davfs`
   - `mountPoint` to match your davfs2 mount point
   - `daemonServiceUnit` / `mountServiceUnit` to match the unit names you used
   - `stateDir` to the directory containing `onedrive-davfs`'s `token.json`
   - `reconnectCommand` to the exact command that re-runs
     `onedrive-davfs`'s device-code sign-in, e.g.:
     `ONEDRIVE_CLIENT_ID=<your-app-id> /path/to/onedrive-davfs/tools/device-code-login.sh`

See the `onedrive-davfs` repo for full setup details (Azure app registration,
device-code flow, systemd units, davfs2 mount) -- this plugin does not
duplicate those instructions.

## Example systemd user unit

Save as `~/.config/systemd/user/rclone-onedrive.service`:

```ini
[Unit]
Description=Rclone OneDrive mount
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/rclone mount onedrive: %h/OneDrive \
  --vfs-cache-mode writes \
  --dir-cache-time 10m \
  --poll-interval 30s \
  --rc \
  --rc-addr 127.0.0.1:5572
ExecStop=/usr/bin/fusermount3 -u %h/OneDrive
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now rclone-onedrive.service
```

## Install locally

Validate first:

```bash
omarchy plugin validate /path/to/onedrive-sync
```

Install into Omarchy's user plugin directory:

```bash
mkdir -p ~/.config/omarchy/plugins/onedrive-sync
cp -a /path/to/onedrive-sync/. ~/.config/omarchy/plugins/onedrive-sync/
omarchy-shell shell rescanPlugins
omarchy plugin enable onedrive-sync
```

## Settings

The plugin exposes these configurable settings through Omarchy:

- `refreshIntervalSec`
- `backend` (`rclone_mount` or `wasm_davfs`)
- `mountPoint`

`rclone_mount`-specific:

- `remoteName`
- `serviceUnit`
- `rcAddr`

`wasm_davfs`-specific:

- `davfsUrl`
- `daemonServiceUnit`
- `mountServiceUnit`
- `stateDir`
- `reconnectCommand`

## Development

Useful checks while iterating:

```bash
omarchy plugin validate .
python3 status.py onedrive ~/OneDrive rclone-onedrive.service 127.0.0.1:5572 25
python3 status_davfs.py ~/OneDrive onedrive-davfs.service onedrive-davfs-mount.service ~/.local/state/onedrive-davfs http://127.0.0.1:8765/
```


## License

MIT
