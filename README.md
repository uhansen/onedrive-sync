# onedrive-sync

`onedrive-sync` is an Omarchy shell plugin that adds a OneDrive status icon,
details panel, and a few safe control actions to the bar.

It is intentionally a **thin UI layer** over external daemons:

- **rclone** performs OAuth, token storage, network I/O, and file transfer.
- **systemd --user** owns the long-running mount lifecycle.
- **The plugin** only polls status, opens the browser for re-auth, and issues
  one-shot control commands.

No OAuth tokens or network code live in QML.

## Features

- Bar icon showing idle / syncing / paused / error states
- Panel with remote, mount path, last sync time, pending count, and queued bytes
- `Sync now` action using rclone's local RC endpoint
- `Open folder` action
- `Reconnect` action that shells out to `rclone config reconnect ...`
- Graceful fallback states when `rclone`, the service unit, or the mount are missing

## Prerequisites

This plugin is **observe-only**. It assumes you have already created:

1. An `rclone` remote called `onedrive`
2. A mount point at `~/OneDrive`
3. A user service called `rclone-onedrive.service`
4. rclone RC enabled locally (default in this plugin: `127.0.0.1:5572`)

Initial OAuth setup should be completed outside the plugin with `rclone config`.
The in-plugin **Reconnect** button is for re-authorization, not first-time setup.

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
- `remoteName`
- `mountPoint`
- `serviceUnit`
- `rcAddr`

## Development

Useful checks while iterating:

```bash
omarchy plugin validate .
python3 status.py onedrive ~/OneDrive rclone-onedrive.service 127.0.0.1:5572 25
```


## License

MIT
