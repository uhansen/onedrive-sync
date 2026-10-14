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
and issues one-shot control commands** -- it never touches OAuth tokens
or Graph. For `wasm_davfs`, `tree_davfs.py` reads the local WebDAV
Basic-auth secret from `envFile` (same user/trust boundary as the daemon
timer) to call `/_status` and `/_tree`. That secret is not an OAuth token
and is never shown in QML.

## Features

- Bar icon showing idle / syncing / paused / error states
- Panel with Browse folders at the top, refresh and reconnect controls beside
  the mount toggle, and an expandable statistics section at the bottom
  (collapsed by default)
- For `wasm_davfs`: metadata-index progress (items indexed, last `/delta`
  tick rate), the current bound Microsoft 365 library identity, a folder tree,
  and indexed search across files and folders
- Searched folders provide separate actions to open a terminal, open the file
  explorer, copy the whole folder, or copy only its contents; destination
  selection uses the native desktop folder picker and never overwrites files
- The Browse folders header provides those same actions for the OneDrive root
- Browse folders is keyboard-operable: Up/Down moves between root and result
  rows, Left/Right selects inline actions, Enter runs the selected action, and
  T/F/C/X/M provide terminal, open, copy, copy-contents, and mail shortcuts
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

This plugin assumes the backend and account login are already set up. Its
optional library picker saves native configuration but does not install or
start services.

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
   via either:
   - an `/etc/fstab` entry, or
   - an `onedrive-davfs-mount.service` user unit
3. If you use both an `/etc/fstab` entry and a user mount unit for the same
   mount point, do **not** duplicate davfs options in the unit's
   `ExecStart=mount.davfs ... -o ...` line. Invoke `mount %h/OneDrive`
   (or your chosen mount point) instead so the unit reuses the authoritative
   options from `/etc/fstab` and avoids davfs errors like
   `different dir_mode in /etc/fstab`.
4. In this plugin's settings, set:
   - `backend` = `wasm_davfs`
   - `mountPoint` to match your davfs2 mount point
   - `daemonServiceUnit` / `mountServiceUnit` to match the unit names you used
   - `stateDir` to the directory containing `onedrive-davfs`'s `token.json`
   - `envFile` to the chmod-600 daemon env file (used only to read the
     local WebDAV Basic-auth secret for `/_status` and `/_tree`; OAuth
     tokens are never read)
   - `reconnectCommand` to the exact command that re-runs
     `onedrive-davfs` sign-in, e.g. either:
     - `ONEDRIVE_CLIENT_ID=<your-app-id> /path/to/onedrive-davfs/tools/device-code-login.sh`
     - `ONEDRIVE_CLIENT_ID=<your-app-id> python3 /path/to/onedrive-davfs/tools/browser-login.py`

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

## Unified Microsoft 365 libraries

Set `backend=wasm_davfs`, `profilesFile=~/.config/onedrive-davfs/profiles.json`,
and `profileSetupCommand=~/.local/share/onedrive-davfs/tools/profiles.py`.
Use the backend's multi-account installation guide to register accounts, sign
in, bootstrap the first library and install its generated user units.
Leave `profilesFile` blank to retain the existing single-library settings.

The version-1 registry has `accounts` and `libraries` arrays. Native setup owns
it; it contains profile IDs, labels, selectors, mount/state/env paths, loopback
URLs and service names, **not OAuth tokens or WebDAV secrets**. Each library
is associated with its account and generated account-specific reconnect
command. The frontend never opens OAuth token files or calls Graph.

All enabled libraries remain available as independent `/@<profile-id>` roots.
Search requires two characters, returns at most 100 entries/library and 500
overall, and preserves the source library label/path even for identical names.
Ordering is stable; truncation and per-library failures are explicit. A failed
library does not hide healthy results. At most 32 profiles are supported, with
four concurrent authenticated local requests. Endpoints must be loopback HTTP
roots with distinct ports and nonoverlapping mount/state directories.

Select a profile to control/reconnect **only that library**. File actions resolve
the original result's mountpoint, not the current control selection. In-flight
responses are discarded after a binding/registry change, and a pending copy
picker is canceled rather than transferring its source to a different profile.
Copies never overwrite existing files or write into configured cloud mounts;
mail uses `xdg-email --attach` to compose in the default client, never to send.

**Add library** supports blank scope (the signed-in user's drives), `group:<id>`,
`site:<id>`, or `siteUrl:https://tenant.sharepoint.com/sites/...`. Loading can be
canceled. Private/shared Teams channels may require their explicit backing
site; group discovery is not tenant-wide/channel-wide enumeration.
**Save library** verifies through the existing account's authenticated backend
and stages new configuration atomically. Install the generated fstab/secret
snippets and user units manually before starting the new mount.

Token-file presence is only a local setup hint. The panel reports backend
**last-verified access**, reindexing and unavailable-library states separately.
Admin consent, site permissions and conditional-access/device policies still
apply; browser/PKCE is not a bypass. Commercial-cloud support is fixture-tested,
not certified against an organizational account. Government/China clouds,
cross-library MOVE, Office coauthoring and full offline sync are out of scope.

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
- `profileLabel`
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
- `envFile`
- `profilesFile` (optional unified registry)
- `profileSetupCommand` (optional native library setup script)

## Development

Useful checks while iterating:

```bash
omarchy plugin validate .
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -p 'test_*.py'
node test_model.cjs
python3 status.py onedrive ~/OneDrive rclone-onedrive.service 127.0.0.1:5572 25
python3 status_davfs.py ~/OneDrive onedrive-davfs.service onedrive-davfs-mount.service ~/.local/state/onedrive-davfs http://127.0.0.1:8765/
python3 tree_davfs.py libraries ~/.config/onedrive-davfs/env http://127.0.0.1:8765/ siteUrl:https://tenant.sharepoint.com/sites/Engineering
```


## License

MIT
