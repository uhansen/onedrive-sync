# Install the plugin and configure your accounts

Already installed? Skip the installation section and follow only the account
path you need: sign in, choose libraries, activate their mounts, and point the
widget at them.

**Installing the plugin alone does not install a backend or configure an
account.** The plugin controls an external rclone or native backend; install
one of them before running its account commands.

| What already works? | What to do next |
| --- | --- |
| Account signed in and folder mounted | Skip login/activation; apply the relevant widget settings and section 6 checks. |
| Backend available, account not configured | Follow the appropriate account path below, including one-time activation. |
| One native library works; you want more | Use unified profiles in section 4, then add libraries/accounts in section 5. |

## Installation (skip if already installed)

These commands target Omarchy/Arch. Run them in your normal user terminal,
not a root shell. They install software but do not grant access to Microsoft
accounts.

### Install the plugin

```bash
omarchy pkg add git python curl openssl xdg-utils
omarchy plugin add https://github.com/uhansen/onedrive-sync.git --enable
omarchy plugin list
```

The plugin normally lives in `~/.config/omarchy/plugins/onedrive-sync/`.
If it is already installed, do not add another copy; use
`omarchy plugin update onedrive-sync` when you intend to update it.
A sign-in or missing-service message is expected until the backend/account
is configured.

### Option A: install rclone

```bash
omarchy pkg add rclone fuse3
rclone version
```

Continue with section 2 to sign in and configure a mount/service using
[the README template](README.md#example-systemd-user-unit). Installing rclone
does not create that service automatically.

### Option B: install the native backend

Install `davfs2` and the native build prerequisites:

```bash
omarchy pkg add davfs2 base-devel cmake pkgconf
```

If a package is unavailable in your enabled repositories, check the current
Arch package instructions before continuing. Use an existing working Rust
toolchain, or install one using the [official rustup instructions](https://rustup.rs/)
and reopen your terminal.

The unified account workflow requires matching host, Wasm component, and
helpers. These examples pin the compatible M365 implementation at `7f3076a`;
older releases/backend master may not include `profiles.py`, `/_resolve`, or
`--account-dir`. Do not mix artifacts from different revisions.

Use a new source directory; if you already have this checkout, preserve its
local changes rather than running these clone/switch commands blindly.

```bash
mkdir -p ~/source
git clone https://github.com/uhansen/onedrive-davfs.git ~/source/onedrive-davfs
cd ~/source/onedrive-davfs
git switch --detach 7f3076a
rustup target add wasm32-wasip2
cargo build --locked --target wasm32-wasip2 --release
cargo build --locked --manifest-path host/Cargo.toml --release
```

Continue only when both builds succeed. Install their outputs and the matching
helpers:

```bash
install -d ~/.local/bin ~/.local/share/onedrive-davfs/tools
install -m 755 host/target/release/onedrive-davfs-host ~/.local/bin/
install -m 644 target/wasm32-wasip2/release/onedrive_davfs.wasm \
  ~/.local/share/onedrive-davfs/
install -m 755 tools/auth_common.py tools/browser-login.py tools/device-login.py \
  tools/device-code-login.sh tools/profiles.py tools/profile-sync.py \
  tools/sync-tick.sh ~/.local/share/onedrive-davfs/tools/
"$HOME/.local/bin/onedrive-davfs-host" --help
python3 "$HOME/.local/share/onedrive-davfs/tools/profiles.py" --help
```

Keep the helpers together because they import shared modules. The native host
replaces `wasmtime serve`; do not run both on the same endpoint.
For the plugin's optional copy-destination picker, system Python also needs
`python-gobject` and a working desktop file-chooser portal.

**Next:** for a new native account, go to section 4, which generates its
per-library configuration and service units. Section 3 is only for an
already-configured single-library service/mount. To create that legacy layout
instead, follow the
[backend installation guide](https://github.com/uhansen/onedrive-davfs/blob/7f3076a/INSTALL.md)
for its environment file, daemon/timer units and davfs mount. Do not start
services before their credentials/configuration exist.

## 1. Choose what to connect

An **account** is your Microsoft login. A **library** is one collection of files
belonging to that account or accessible through it. One account can access
several libraries.

| Your files | What to select |
| --- | --- |
| Personal OneDrive | Your personal account's OneDrive. |
| Work/school OneDrive | Your work account's own OneDrive, not the team's documents. |
| SharePoint | The specific site's document library; a site can have several. |
| Teams standard channel | The parent team's SharePoint library, then the channel folder. |
| Teams private/shared channel | The channel's own SharePoint site and library. |

For Teams, use **Open in SharePoint** from the channel's files/shared tab to
find the backing site. A sharing link is not a library ID. Chat attachments
are not automatically a separate Teams library.

Choose the section for your installed backend:

- **[rclone](#2-rclone-accounts):** a remote and widget per account/library.
- **[Native, single library](#3-native-existing-single-library):** keep an
  existing simple mount.
- **[Native, unified libraries](#4-native-unified-accounts-and-libraries):**
  one widget for several accounts/libraries, with indexed browsing/search.

Examples use Bash. Replace `YOUR_CLIENT_ID`, `YOUR_TENANT_ID`, and
`YOUR_DRIVE_ID` with your own values. Do not copy tokens or secrets into
support messages. Work/school accounts may require administrator approval;
none of these steps bypasses permissions or device policies.

The `omarchy bar set` examples assume **one** OneDrive widget. If you have
several, edit the intended object in `~/.config/omarchy/shell.json`, or use
the instance placement selectors described by `omarchy bar --help`.
Settings go directly on the widget object, not inside a `"settings"` wrapper.

## 2. rclone accounts

### Sign in and choose a library

1. Run `rclone config`.
2. Choose **New remote**, give it a name such as `personal` or `work`, and
   choose storage type **Microsoft OneDrive** (`onedrive`).
3. Use rclone's default client registration unless your organization requires
   its own. Complete browser sign-in with the intended Microsoft account.
4. Choose **OneDrive Personal or Business** for your own drive. For SharePoint
   or Teams files, choose the backing SharePoint site/library or its known
   site/drive ID. Select by menu labels, not fixed menu numbers.
5. Save the remote and check it:

```bash
rclone lsd personal:
```

Replace `personal` with the remote you created. Compare the folders with the
same library in your browser. Fix login or access errors before configuring
the plugin.

For organization-specific registration, consent, and tenant settings, follow
[rclone's OneDrive account instructions](https://rclone.org/onedrive/).
Do not use the native backend's public-client registration recipe for rclone.

### Activate and select it in the plugin

Your rclone user service must mount that remote and enable RC on its configured
loopback address. If you need a service template, see
[the README example](README.md#example-systemd-user-unit).
Adjust its remote, mountpoint, service name and RC port consistently.
Create an empty mount directory before starting the service.

For example, with remote `personal`, mount `~/OneDrive-Personal`, and an
already configured `rclone-personal.service`:

```bash
systemctl --user daemon-reload
systemctl --user enable --now rclone-personal.service
findmnt --mountpoint "$HOME/OneDrive-Personal"
ls "$HOME/OneDrive-Personal"

omarchy bar set onedrive-sync backend rclone_mount
omarchy bar set onedrive-sync profileLabel Personal
omarchy bar set onedrive-sync remoteName personal
omarchy bar set onedrive-sync mountPoint "$HOME/OneDrive-Personal"
omarchy bar set onedrive-sync serviceUnit rclone-personal.service
omarchy bar set onedrive-sync rcAddr 127.0.0.1:5572
```

**For another account/library**, repeat with a separate remote, mount, service,
RC port, and widget instance:

| Remote | Mount | Service | RC address |
| --- | --- | --- | --- |
| `personal` | `~/OneDrive-Personal` | `rclone-personal.service` | `127.0.0.1:5572` |
| `work` | `~/OneDrive-Work` | `rclone-work.service` | `127.0.0.1:5573` |
| `engineering` | `~/SharePoint-Engineering` | `rclone-engineering.service` | `127.0.0.1:5574` |

The plugin expects the normal `~/.config/rclone/rclone.conf` and does not
supply RC authentication credentials. Keep RC loopback-only; do not disable
authentication protections to make controls work. On untrusted multi-user
machines, consider [RC's security implications](https://rclone.org/rc/#security).
The native unified library picker is not available in rclone mode.

## 3. Native: existing single library

Use this section when an existing native service and mount already point at
the library you want. To add isolated accounts/libraries, use section 4 instead.

### Check the account configuration and sign in

Privately edit your existing `~/.config/onedrive-davfs/env`:

```dotenv
ONEDRIVE_CLIENT_ID="YOUR_CLIENT_ID"
ONEDRIVE_TENANT_ID="common"
ONEDRIVE_SCOPES="offline_access Files.ReadWrite.All User.Read"
ONEDRIVE_DRIVE_BASE="me/drive"
ONEDRIVE_BASIC_AUTH_SECRET="KEEP_YOUR_EXISTING_LOCAL_SECRET"
```

Use your work tenant ID for a work account; personal accounts can use
`consumers` or a deliberately chosen `common` authority. `me/drive` selects
your own OneDrive; `drives/YOUR_DRIVE_ID` selects a known accessible library.
Keep the existing local WebDAV secret matching davfs credentials, and keep
the file mode `600`. Do not repurpose a live mount across different accounts.

The native backend needs an approved **public-client** app registration:
delegated `Files.ReadWrite.All`, `User.Read`, `offline_access`, and optionally
`Sites.Read.All` for site discovery. Browser login uses a registered
`http://localhost/callback` redirect with PKCE; no client secret is needed.
See the linked backend guide for registration details.

In a dedicated terminal, source only your trusted private file and sign in:

```bash
set -a
. "$HOME/.config/onedrive-davfs/env"
set +a
ONEDRIVE_STATE_DIR="$HOME/.local/state/onedrive-davfs" \
  python3 "$HOME/.local/share/onedrive-davfs/tools/browser-login.py"
```

For device-code login, use the same environment and state directory but run
`bash ~/.local/share/onedrive-davfs/tools/device-code-login.sh` instead.
Close the terminal afterward. Do not print the token file.

### Activate and connect the existing mount

Close files before restarting services. These commands assume the existing
mount/fstab/credentials are already configured:

```bash
systemctl --user restart onedrive-davfs.service
systemctl --user enable --now onedrive-davfs-sync.timer
systemctl --user start onedrive-davfs-sync.service
systemctl --user start onedrive-davfs-mount.service

omarchy bar set onedrive-sync backend wasm_davfs
omarchy bar set onedrive-sync profilesFile ''
omarchy bar set onedrive-sync mountPoint "$HOME/OneDrive"
omarchy bar set onedrive-sync davfsUrl http://127.0.0.1:8765/
omarchy bar set onedrive-sync daemonServiceUnit onedrive-davfs.service
omarchy bar set onedrive-sync mountServiceUnit onedrive-davfs-mount.service
omarchy bar set onedrive-sync stateDir "$HOME/.local/state/onedrive-davfs"
omarchy bar set onedrive-sync envFile "$HOME/.config/onedrive-davfs/env"
omarchy bar set onedrive-sync reconnectCommand \
  'set -a; . "$HOME/.config/onedrive-davfs/env" && set +a && ONEDRIVE_STATE_DIR="$HOME/.local/state/onedrive-davfs" python3 "$HOME/.local/share/onedrive-davfs/tools/browser-login.py"'
```

Substitute your actual service names and paths. **Add library is hidden** while
`profilesFile` is blank; that is expected in single-library mode.

## 4. Native: unified accounts and libraries

Each account gets an isolated login; its libraries share that login but have
separate mounts and services. The first library requires a temporary
**bootstrap host** so the setup tool can verify access before saving it.

### Register and sign in to an account

Example work account named `work`:

```bash
python3 ~/.local/share/onedrive-davfs/tools/profiles.py account \
  --id work --client-id YOUR_CLIENT_ID --tenant YOUR_TENANT_ID \
  --scopes 'offline_access Files.ReadWrite.All User.Read Sites.Read.All'

ONEDRIVE_ACCOUNT_DIR="$HOME/.config/onedrive-davfs/account-data/work" \
ONEDRIVE_CLIENT_ID="YOUR_CLIENT_ID" \
ONEDRIVE_TENANT_ID="YOUR_TENANT_ID" \
ONEDRIVE_SCOPES="offline_access Files.ReadWrite.All User.Read Sites.Read.All" \
python3 ~/.local/share/onedrive-davfs/tools/browser-login.py
```

Run account registration once per account ID. For personal OneDrive, choose
an ID such as `personal` and authority `consumers` (or deliberately `common`).
Use a compatible app registration as described in section 3.
Omit `Sites.Read.All` everywhere if it is not needed/approved. Client, tenant
and scopes must match throughout the account's registration, login and backend.

### Bootstrap the first library

Create a new private `~/.config/onedrive-davfs/work-bootstrap.env` using your
editor; do not overwrite an existing file:

```dotenv
ONEDRIVE_CLIENT_ID="YOUR_CLIENT_ID"
ONEDRIVE_TENANT_ID="YOUR_TENANT_ID"
ONEDRIVE_SCOPES="offline_access Files.ReadWrite.All User.Read Sites.Read.All"
ONEDRIVE_DRIVE_BASE="me/drive"
ONEDRIVE_BASIC_AUTH_SECRET="YOUR_NEW_RANDOM_LOCAL_SECRET"
```

Generate the secret with `openssl rand -base64 32` and make the file private:

```bash
chmod 600 ~/.config/onedrive-davfs/work-bootstrap.env
ss -ltn 'sport = :8790'
```

Port 8790 must be unused. If occupied, choose another port consistently.
In a dedicated terminal:

```bash
mkdir -p ~/.local/state/onedrive-davfs/bootstrap-work
set -a
. "$HOME/.config/onedrive-davfs/work-bootstrap.env"
set +a
"$HOME/.local/bin/onedrive-davfs-host" --addr 127.0.0.1:8790 \
  --state-dir "$HOME/.local/state/onedrive-davfs/bootstrap-work" \
  --account-dir "$HOME/.config/onedrive-davfs/account-data/work" \
  --component "$HOME/.local/share/onedrive-davfs/onedrive_davfs.wasm"
```

Leave it running; do not mount this temporary endpoint. In another terminal,
verify and save the first library:

```bash
python3 ~/.local/share/onedrive-davfs/tools/profiles.py library \
  --account work --source-url http://127.0.0.1:8790/ \
  --source-env ~/.config/onedrive-davfs/work-bootstrap.env \
  --selector me/drive --name "Work OneDrive" --id workdocs
```

For a known SharePoint library, substitute `drives/YOUR_DRIVE_ID`. If the
account has no primary OneDrive, also use that selector in the bootstrap env.
For discovering IDs, see section 5.
Do **not** pre-create `~/OneDrive-Libraries/workdocs`: the setup tool requires
a new mountpoint. It generates a profile in `profiles.json` and files under
`~/.config/onedrive-davfs/library-data/workdocs/`.

### One-time activation of the generated library

**Save library does not start a working mount.** For `workdocs`:

These are per-library account configuration steps, not software installation.
Skip them if that exact profile is already activated and its mount works.

1. Review its generated `fstab.entry` and add it **once** using
   `sudoedit /etc/fstab`. Preserve all existing entries.
2. Merge its `davfs-secrets.entry` into your private `~/.davfs2/secrets`
   **once**, preserving other credentials; keep mode `600`. Never share this
   file or the generated secret snippet.
3. Create the generated mountpoint and activate its units:

```bash
PROFILE="$HOME/.config/onedrive-davfs/library-data/workdocs"
mkdir -p "$HOME/OneDrive-Libraries/workdocs" "$HOME/.config/systemd/user"
install -m 644 "$PROFILE/onedrive-davfs-workdocs.service" \
  "$PROFILE/onedrive-davfs-workdocs-mount.service" \
  "$PROFILE/onedrive-davfs-workdocs-sync.service" \
  "$PROFILE/onedrive-davfs-workdocs-sync.timer" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now onedrive-davfs-workdocs.service
systemctl --user enable --now onedrive-davfs-workdocs-sync.timer
systemctl --user start onedrive-davfs-workdocs-sync.service
systemctl --user enable --now onedrive-davfs-workdocs-mount.service
findmnt --mountpoint "$HOME/OneDrive-Libraries/workdocs"
ls "$HOME/OneDrive-Libraries/workdocs"
```

Use the exact generated mountpoint if you chose a custom one. If the mount
fails, check daemon readiness, davfs user-mount permissions and the generated
fstab entry; do not add conflicting `mount.davfs -o` options.
Once the real library works, stop the bootstrap host with **Ctrl+C in its
terminal**. Do not delete the account credential directory.

### Enable the unified widget

```bash
omarchy bar set onedrive-sync backend wasm_davfs
omarchy bar set onedrive-sync profilesFile "$HOME/.config/onedrive-davfs/profiles.json"
omarchy bar set onedrive-sync profileSetupCommand "$HOME/.local/share/onedrive-davfs/tools/profiles.py"
omarchy-shell shell rescanPlugins
```

Open **Browse folders**: the library selector and **Add library** should now
appear. Installing the plugin/backend does not set these options automatically.

## 5. Add SharePoint, Teams, or another account

### Choose the library

For native unified mode, select an existing working library belonging to the
right account, then **Add library -> Discover**:

| Discovery scope | What it lists |
| --- | --- |
| Blank | The signed-in user's drives, not all sites in the tenant. |
| `group:YOUR_GROUP_ID` | A particular Microsoft 365 group's drives. |
| `site:YOUR_SITE_ID` | A particular site's libraries. |
| `siteUrl:https://example.sharepoint.com/sites/Engineering` | Libraries of that specific SharePoint site. |

Use the site root, not a sharing link or `Forms/AllItems.aspx` URL. For private
or shared Teams channels, use **that channel's own site**, not just the parent
team's group. You still need membership and approved permissions.

Before the first profile exists, discover through the running bootstrap host:

```bash
python3 ~/.config/omarchy/plugins/onedrive-sync/tree_davfs.py libraries \
  ~/.config/onedrive-davfs/work-bootstrap.env http://127.0.0.1:8790/ \
  siteUrl:https://example.sharepoint.com/sites/Engineering
```

Use the intended result's `drives/ID` selector in the first-library command.

### Save and activate an additional library

Choose the discovered library and **Save library**. Inspect `profiles.json`
for its generated ID, then repeat section 4's activation steps using that ID
and its exact generated paths. The display name is not necessarily the ID.

Or, for a known library belonging to the **same account**:

```bash
python3 ~/.local/share/onedrive-davfs/tools/profiles.py library \
  --source workdocs --selector drives/YOUR_DRIVE_ID \
  --name "Engineering documents" --id engineering
```

Activate `engineering` as above. Do not register another account just to add
one of its libraries.

For a **different account**, repeat section 4 with a new account ID, isolated
login, bootstrap directory/env file and unused port. Do not bootstrap it
through another account's library or copy tokens between directories.
Generated reconnect commands already target the owning account.

For **rclone**, use section 2 instead: create another remote for the backing
site/library and its own mount/service/widget. Native profile commands do not
configure rclone accounts.

## 6. Check your configuration

1. Compare a known folder with the same account/library in your browser.
   For Teams, compare the location reached by **Open in SharePoint**.
2. Confirm `findmnt` and an actual `ls` work on the intended mount.
3. Open it from the correct widget. In native unified mode, confirm each
   library has its own source path and the selector is visible.
4. Allow the native metadata index to progress before judging search results.
   Search needs two characters. Indexing names does not download all files.

Native unified status:

```bash
python3 ~/.config/omarchy/plugins/onedrive-sync/profiles_davfs.py status \
  ~/.config/onedrive-davfs/profiles.json
```

For the existing single-library example:

```bash
python3 ~/.config/omarchy/plugins/onedrive-sync/tree_davfs.py status \
  ~/.config/onedrive-davfs/env http://127.0.0.1:8765/
```

Look for successful responses and backend `accessVerified` after a successful
metadata tick. Token-file presence and a running service alone do not prove
current cloud access. Status responses can contain private paths/names;
redact them before sharing.

| Problem | Check |
| --- | --- |
| Wrong files | Actual login identity and selected drive/library, not just its display label. |
| Needs admin approval / access denied | App registration, delegated scopes, tenant policy and library membership. |
| No library selector / Add library | Native mode, nonblank `profilesFile`, registry with activated profiles. Never available for rclone. |
| Library saved but mount missing | Generated fstab/secret entries and service activation are still required. |
| Bootstrap identity mismatch | Matching account directory, client ID, tenant and scopes throughout. |
| Local HTTP 401 | Local WebDAV secret must match; this is separate from Microsoft login. |
| Search misses files | Index progress and per-library errors; results are capped. |
| Old UI after changing configuration | Validate the installed plugin; if rescan is insufficient, run `omarchy restart shell`. |

These are real cloud mounts, not backups. Read-only checks are sufficient to
verify configuration; do not delete or overwrite documents as a setup test.
