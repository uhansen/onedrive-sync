# Your little OneDrive setup book

A step-by-step guide for Omarchy: personal OneDrive, work or school OneDrive,
SharePoint, and files in Microsoft Teams.

You do not need to understand WebAssembly or Microsoft Graph before starting.
You do need permission to access your files and, for some work accounts, help
from your Microsoft 365 administrator.

**Nothing in this book bypasses your organization's access rules.**
Start with reading and listing files. Do not test by deleting or overwriting
real documents.

## Contents

- [1. Meet the three pieces](#1-meet-the-three-pieces)
- [2. Choose your route](#2-choose-your-route)
- [3. Prepare Omarchy and install the plugin](#3-prepare-omarchy-and-install-the-plugin)
- [4. Route A: rclone](#4-route-a-rclone)
- [5. Route B: native onedrive-davfs](#5-route-b-native-onedrive-davfs)
- [6. Native unified accounts and libraries](#6-native-unified-accounts-and-libraries)
- [7. SharePoint and Teams recipes](#7-sharepoint-and-teams-recipes)
- [8. Everyday use](#8-everyday-use)
- [9. Updates, migration, and removal](#9-updates-migration-and-removal)
- [10. When something does not work](#10-when-something-does-not-work)
- [11. Final checklist and references](#11-final-checklist-and-references)

## 1. Meet the three pieces

Imagine a bookshop:

```text
Microsoft cloud              Your computer                         Your bar
----------------             ----------------                     --------
OneDrive or SharePoint <--->  backend + mounted folder  <-------->  plugin
The books                    The delivery service                 The sign
```

The **plugin is the sign**, not the delivery service. Installing it alone
does not sign you in, create mounts, or download your files.

| Word | Meaning |
| --- | --- |
| Account | The Microsoft identity you sign in with. |
| Tenant | A work/school organization's Microsoft 365 directory. |
| Library / drive | One collection of files: your OneDrive or a SharePoint document library. |
| Site | A SharePoint website that can contain several document libraries. |
| Remote | rclone's saved connection to one cloud file collection. |
| Mountpoint | A local folder, such as `~/OneDrive`, through which you access cloud files. |
| Service | A background program managed by `systemd --user`. |
| Profile registry | The native backend's list of accounts and libraries. It enables the unified UI. |
| Metadata index | A catalog of names and folders, not a local copy of every document. |

**A mount is not a full offline sync or a backup.** Opening files may need the
network. Deleting a file through a writable mount can delete the cloud file.
Do not point two backends at the same local mountpoint.

## 2. Choose your route

Both routes can expose personal, work/school, SharePoint, and Teams-backed
document libraries, subject to your permissions.

| Question | Route A: rclone | Route B: native onedrive-davfs |
| --- | --- | --- |
| Where do I start? | `rclone config`, often using rclone's existing app registration. | Build the host/component and register a public-client app. |
| How are files mounted? | rclone's FUSE mount. | Local WebDAV server plus davfs2. |
| Plugin experience | Mount controls, RC statistics, pending items, open folder. | Mount controls, metadata progress, folder browser and indexed search. |
| Several libraries | Separate remotes, services, ports, mounts, and widget instances. | Optional unified registry, browser, and search across libraries. |
| Add library in the panel | Not available. | Available after unified profiles are configured. |
| First-time setup difficulty | Usually fewer steps. | More moving parts; useful for the unified library workflow. |

For a first personal OneDrive, Route A is usually the simpler starting point.
For one unified browser across multiple accounts/libraries, use Route B and
chapter 6.

This book covers the plugin's **two implemented backend modes**, not every
Microsoft cloud product. The native implementation targets the commercial
Microsoft cloud; government/China clouds, Office coauthoring, cross-library
MOVE, and full offline synchronization are outside its supported scope.
Its organizational compatibility is fixture-tested, not certified against
every enterprise tenant.

The native backend currently buffers downloads, limits PUT uploads to **64 MiB**,
and implements no-op WebDAV locks rather than real collaborative locking.
Do not treat it as an Office desktop coauthoring filesystem or assume that
large uploads supported by rclone are also supported by this backend.

### A note about versions

The frontend's M365 changes are on `onedrive-sync` master. The matching backend
used for this guide is `onedrive-davfs` commit `7f3076a` on `topic/m365`.
Backend master and old release artifacts are **not interchangeable** with
that implementation. In particular, unified setup needs `--account-dir`,
`/_resolve`, and the matching native helpers.

The source-build instructions below select that revision explicitly. No
working prebuilt release containing those features was verified for this
guide. Do not substitute an old `.wasm` download simply because its filename
matches. Keep host, component, and helper scripts from the same revision.

## 3. Prepare Omarchy and install the plugin

Examples assume a fresh Omarchy/Arch system, a normal user terminal, and Bash.
Use `sudo` only for package installation and system-owned configuration.
Run cloud services as **your user**, not root.

Words such as `YOUR_CLIENT_ID`, `YOUR_TENANT_ID`, and `YOUR_DRIVE_ID` are
placeholders: replace them. They are not commands to run unchanged.
Example names `personal`, `work`, and `engineering` are local labels you choose.

### 3.1 Check prerequisites

Common tools:

```bash
omarchy pkg add git python curl openssl xdg-utils
```

For Route A:

```bash
omarchy pkg add rclone fuse3
```

For Route B, you also need `davfs2`, a working Rust toolchain with `rustup`,
and native build tools:

```bash
omarchy pkg add davfs2 base-devel cmake pkgconf
```

If a package is unavailable in your enabled Arch repositories, stop and check
the current Arch/Omarchy package instructions; do not install an unrelated
similarly named package. Use your existing Rust installation if present.
Otherwise install Rust using its [official rustup instructions](https://rustup.rs/),
then open a new terminal.

The native destination picker needs system Python's PyGObject and a working
desktop file-chooser portal. Omarchy normally supplies the portal; if Python's
`gi` import is missing, install `python-gobject`. This is separate from the
backend's standard-library-only Python helpers.

### 3.2 Install the widget

```bash
omarchy plugin add https://github.com/uhansen/onedrive-sync.git --enable
omarchy plugin list
```

If already installed, do not add another copy. Use the update instructions in
chapter 9. Installation normally goes under:

```text
~/.config/omarchy/plugins/onedrive-sync/
```

**Checkpoint:** the plugin is listed and enabled. A missing-service or
sign-in message is normal at this point.

### 3.3 Know where settings live

The commands in this book use Omarchy's widget settings interface:

```bash
omarchy bar set onedrive-sync refreshIntervalSec 30 --json
```

Widget instances are also stored in `~/.config/omarchy/shell.json`, as objects
inside `bar.layout` sections. Settings belong directly on each widget object,
not inside a new `"settings"` wrapper.

Before any manual change:

```bash
cp -p ~/.config/omarchy/shell.json ~/.config/omarchy/shell.json.before-onedrive
```

Choose a different backup filename if that backup already exists. Never
replace your whole shell configuration with a small example from this book.
Change or add only the relevant widget object.

## 4. Route A: rclone

### 4.1 Connect one account or library

Run:

```bash
rclone config
```

Choose **New remote**, give it a name, and choose storage type **Microsoft
OneDrive** (`onedrive`). Prefer names over menu numbers: numbers change between
rclone versions.

For the simplest setup, use rclone's default client ID and leave its client
secret blank when prompted. Use automatic browser authentication on your
Omarchy desktop. Check which Microsoft account the browser actually selects.

| What you want | Remote name example | Selection after login |
| --- | --- | --- |
| Personal OneDrive | `personal` | OneDrive Personal or Business, then your personal drive. |
| Work/school OneDrive | `work` | OneDrive Personal or Business, then your business drive. |
| SharePoint document library | `engineering` | SharePoint site/search, or a known site/drive ID, then the correct library. |
| Teams channel files | `teamfiles` | The backing SharePoint site/library; see chapter 7. |

Keep the completed remote. Then test **without mounting**:

```bash
rclone lsd personal:
```

Substitute your remote name. Seeing the expected directories is the first
real success check. An empty drive can legitimately return no directories;
compare it with the same account/library in your browser.

Do not run `rclone config show` or paste `rclone.conf` into a support request:
it can expose OAuth credentials. The plugin expects the normal
`~/.config/rclone/rclone.conf` and checks for a token in the chosen remote.
Custom/encrypted config handling is not configured by a plugin setting.

### 4.2 If your organization requires its own app

Do not reuse the native backend's app-registration instructions blindly.
rclone's custom-client flow has its own redirect/client-secret requirements.

Follow the [official rclone OneDrive app instructions](https://rclone.org/onedrive/#getting-your-own-client-id-and-key).
For a work tenant, ask the administrator whether a single-tenant registration,
publisher approval, delegated permissions, or admin consent is required.
Configure the resulting client details in `rclone config`, not in the plugin.
For tenant-specific authentication, rclone documents advanced `auth_url` and
`token_url` values pointing at that tenant.

If site search is forbidden or unavailable, use an administrator-provided
drive/site ID and the documented corresponding rclone selection. A known ID
does not grant access you do not already have.

**Checkpoint:** `rclone lsd REMOTE:` works before continuing. Neither the
plugin nor a mount will fix a failed cloud login.

### 4.3 Create an empty mountpoint

We will mount `personal:` at `~/OneDrive-Personal`:

```bash
mkdir -p ~/OneDrive-Personal ~/.config/systemd/user
```

Check that the folder contains no files and is not already mounted. Mounting
over an existing directory can hide its local contents until unmounted.

Create `~/.config/systemd/user/rclone-personal.service` with this content:

```ini
[Unit]
Description=Personal OneDrive via rclone
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/rclone mount personal: %h/OneDrive-Personal \
    --vfs-cache-mode writes \
    --dir-cache-time 10m \
    --poll-interval 30s \
    --rc \
    --rc-addr 127.0.0.1:5572
ExecStop=/usr/bin/fusermount3 -u %h/OneDrive-Personal
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Use your editor to create the file. `~` is not expanded in systemd
`ExecStart`; `%h` is the home-directory specifier.

**RC safety:** the plugin does not supply RC authentication credentials.
This example follows the repository's loopback RC setup. Do not add
`--rc-no-auth`, expose RC on `0.0.0.0`, or forward the port.
Loopback is reachable by other local users/processes; RC is powerful and is
not a per-endpoint, least-privilege API. On an untrusted multi-user machine,
prefer an authenticated backend design rather than weakening RC to make
controls work. See the [RC security documentation](https://rclone.org/rc/#security).
An authenticated RC server may require managing rclone outside this plugin.

### 4.4 Start it and check the folder

```bash
systemctl --user daemon-reload
systemctl --user enable --now rclone-personal.service
systemctl --user status rclone-personal.service --no-pager
findmnt --mountpoint "$HOME/OneDrive-Personal"
ls "$HOME/OneDrive-Personal"
rclone rc --rc-addr 127.0.0.1:5572 core/stats
```

Expected: active service, a mounted filesystem, expected files, and RC
statistics. An idle account may have no transfers or pending items.
If an RC call is denied, keep authentication protections intact and consult
the RC documentation; do not assume the cloud account is broken.

### 4.5 Point the plugin at that service

For a single widget:

```bash
omarchy bar set onedrive-sync backend rclone_mount
omarchy bar set onedrive-sync profileLabel Personal
omarchy bar set onedrive-sync remoteName personal
omarchy bar set onedrive-sync mountPoint "$HOME/OneDrive-Personal"
omarchy bar set onedrive-sync serviceUnit rclone-personal.service
omarchy bar set onedrive-sync rcAddr 127.0.0.1:5572
```

Click the OneDrive icon. **Open folder** should open the mount. This backend
does not supply the native backend's indexed browser or unified library picker.
**Sync now** requests a VFS directory refresh; it does not create an offline
replica or run a two-way synchronization job.

### 4.6 Work, SharePoint, and Teams: repeat with separate names

Complete `rclone config` for each desired library, then repeat sections
4.3-4.5 with a unique set:

| Remote | Mountpoint | Service | RC address |
| --- | --- | --- | --- |
| `personal` | `~/OneDrive-Personal` | `rclone-personal.service` | `127.0.0.1:5572` |
| `work` | `~/OneDrive-Work` | `rclone-work.service` | `127.0.0.1:5573` |
| `engineering` | `~/SharePoint-Engineering` | `rclone-engineering.service` | `127.0.0.1:5574` |
| `teamfiles` | `~/Teams-Project` | `rclone-teamfiles.service` | `127.0.0.1:5575` |

Change **all four** values in each unit/settings pair. Do not reuse the same
RC port. Do not mount different accounts over the same folder.

For multiple widgets, preserve your existing `shell.json` and add a separate
object for each instance in the desired layout section. These are **two array
entries**, not a whole configuration file:

```json
[
  {
    "id": "onedrive-sync",
    "backend": "rclone_mount",
    "profileLabel": "Personal",
    "remoteName": "personal",
    "mountPoint": "~/OneDrive-Personal",
    "serviceUnit": "rclone-personal.service",
    "rcAddr": "127.0.0.1:5572"
  },
  {
    "id": "onedrive-sync",
    "backend": "rclone_mount",
    "profileLabel": "Work",
    "remoteName": "work",
    "mountPoint": "~/OneDrive-Work",
    "serviceUnit": "rclone-work.service",
    "rcAddr": "127.0.0.1:5573"
  }
]
```

Do not run unqualified `omarchy bar set onedrive-sync ...` commands expecting
them to target a particular duplicate widget. Use explicit placement selectors
documented by `omarchy bar --help`, or edit the intended object directly.
Use each widget's own controls; do not assume the shared plugin IPC name
uniquely identifies one instance.

## 5. Route B: native onedrive-davfs

This route builds three matching pieces: the native host, the Wasm component,
and Python setup/login helpers. You do not need a separate `wasmtime serve`
process when using the native host.

### 5.1 Build the compatible version

Choose a new source directory. If already cloned, inspect local changes
before switching revisions.

```bash
mkdir -p ~/source
git clone https://github.com/uhansen/onedrive-davfs.git ~/source/onedrive-davfs
cd ~/source/onedrive-davfs
git switch --detach 7f3076a
rustup target add wasm32-wasip2
cargo build --locked --target wasm32-wasip2 --release
cargo build --locked --manifest-path host/Cargo.toml --release
cargo test --locked --lib
cargo test --locked --manifest-path host/Cargo.toml
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools -p 'test_*.py'
```

Cargo downloads and compiles dependencies. Compilation needs disk space,
memory, and a Rust version compatible with the manifests. A failed build is
not a usable installation; do not continue by copying stale artifacts.

Install the artifacts and helpers:

```bash
install -d ~/.local/bin ~/.local/share/onedrive-davfs/tools
install -m 755 host/target/release/onedrive-davfs-host ~/.local/bin/
install -m 644 target/wasm32-wasip2/release/onedrive_davfs.wasm \
  ~/.local/share/onedrive-davfs/
install -m 755 tools/auth_common.py tools/browser-login.py \
  tools/device-login.py tools/device-code-login.sh tools/profiles.py \
  tools/profile-sync.py tools/sync-tick.sh ~/.local/share/onedrive-davfs/tools/
```

If `wasm-tools` is installed, also run
`wasm-tools validate target/wasm32-wasip2/release/onedrive_davfs.wasm`.
The helper scripts import one another: copy the group, not only
`browser-login.py` or `profiles.py`.

**Choose now:** for one simple mount, continue through chapter 5. For unified
personal/work/SharePoint/Teams libraries, go directly to chapter 6 after
registering the app below. You do not have to build a legacy mount first.

### 5.2 Register a public-client Microsoft application

In the [Microsoft Entra/Azure portal](https://portal.azure.com/), open
**Microsoft Entra ID -> App registrations -> New registration**.

1. Give it a recognizable name, such as `My OneDrive desktop mount`.
2. Select supported accounts deliberately. Personal accounts require a
   registration that permits personal Microsoft accounts. Work-only setups can
   use a tenant-specific registration approved by the organization.
3. Record the **Application (client) ID**. For work/school, also record the
   **Directory (tenant) ID**.
4. Under **Authentication**, configure a **Mobile and desktop applications**
   public-client platform. For this helper's browser flow, register
   `http://localhost/callback`; it uses an ephemeral localhost port with PKCE.
   Microsoft's localhost matching rules permit varying ports; the callback
   path must still match.
5. To allow device-code login, enable **Allow public client flows** as required
   by the registration. The device-code flow itself does not use a redirect
   callback. The backend's setup guide also documents the native-client URI
   `https://login.microsoftonline.com/common/oauth2/nativeclient`.
6. Under **API permissions**, add Microsoft Graph **delegated** permissions
   `Files.ReadWrite.All`, `User.Read`, and `offline_access`. Add
   `Sites.Read.All` when scoped SharePoint site discovery needs it.
7. Obtain user/admin consent as required by the tenant and requested scopes.

**No client secret is needed for the native public-client/PKCE flow.** Do not
put an application secret into the plugin. Do not accidentally follow
rclone's different custom-client recipe for this route.

If you cannot register an app or grant consent, ask your administrator.
Successful sign-in in Teams does not prove that this separate app is approved.
For personal-only accounts, portal registration availability may require an
appropriate Entra directory; rclone's default app is an alternative if you
cannot obtain your own registration.

### 5.3 Simple single-library: make a private environment file

Skip to chapter 6 if you chose unified profiles.

The following paths are for **one** library. Do not overwrite an existing
`env`, token store, or mount configuration.

```bash
install -d -m 700 ~/.config/onedrive-davfs ~/.local/state/onedrive-davfs
install -m 600 /dev/null ~/.config/onedrive-davfs/env
```

Open `~/.config/onedrive-davfs/env` in your editor and fill in:

```dotenv
ONEDRIVE_CLIENT_ID="YOUR_CLIENT_ID"
ONEDRIVE_TENANT_ID="common"
ONEDRIVE_SCOPES="offline_access Files.ReadWrite.All User.Read"
ONEDRIVE_DRIVE_BASE="me/drive"
ONEDRIVE_BASIC_AUTH_SECRET="YOUR_RANDOM_LOCAL_SECRET"
```

Generate the local secret with `openssl rand -base64 32`, then put it in the
file. It is the password for **local WebDAV**, not your Microsoft password.
Do not publish it. For work/school, replace `common` with your tenant ID.
If you added `Sites.Read.All`, include it in `ONEDRIVE_SCOPES` for both
login and daemon configuration.

`me/drive` means the signed-in user's primary OneDrive. For a known library,
use `drives/YOUR_DRIVE_ID`; do not paste a Teams sharing URL there.
For discovering/selecting libraries rather than guessing IDs, use chapter 6.

### 5.4 Sign in

In a new terminal, load only the private file you created and trust:

```bash
set -a
. "$HOME/.config/onedrive-davfs/env"
set +a
export ONEDRIVE_STATE_DIR="$HOME/.local/state/onedrive-davfs"
python3 "$HOME/.local/share/onedrive-davfs/tools/browser-login.py"
```

Use a terminal dedicated to this login; loading the file puts its variables
in that terminal's environment. Close it afterward. The browser helper opens
Microsoft sign-in and stores credentials privately in the state directory.

If device-code login is permitted instead, replace the final command with:

```bash
bash "$HOME/.local/share/onedrive-davfs/tools/device-code-login.sh"
```

Visit the displayed Microsoft URL, enter the displayed code, and finish
sign-in. Never give that code to anyone else. Neither login method bypasses
MFA, consent, or conditional-access/device-compliance requirements.

**Checkpoint:** the helper reports success. Do not print `token.json`.

### 5.5 Install the daemon and metadata timer

From the source checkout selected in 5.1:

```bash
cd ~/source/onedrive-davfs
mkdir -p ~/.config/systemd/user
install -m 644 systemd/onedrive-davfs.service \
  systemd/onedrive-davfs-sync.service systemd/onedrive-davfs-sync.timer \
  ~/.config/systemd/user/
install -m 755 tools/sync-tick.sh ~/.local/share/onedrive-davfs/sync-tick.sh
systemctl --user daemon-reload
systemctl --user enable --now onedrive-davfs.service
systemctl --user enable --now onedrive-davfs-sync.timer
systemctl --user start onedrive-davfs-sync.service
```

The legacy sync unit expects `sync-tick.sh` at the top-level installed path,
which is why that additional copy is present.

Check authenticated status using the **plugin helper**, not a secret on the
`curl` command line:

```bash
python3 ~/.config/omarchy/plugins/onedrive-sync/tree_davfs.py status \
  ~/.config/onedrive-davfs/env http://127.0.0.1:8765/
```

Expected: `"ok": true`; after a successful metadata tick,
`"accessVerified": true`. The initial crawl may still be incomplete.
A running process or the mere presence of a token file is not proof of
current Microsoft access.

### 5.6 Mount the local WebDAV endpoint

Use **one authoritative mount definition**. This book uses `/etc/fstab` and
a user service that invokes that entry, avoiding conflicting davfs options.

```bash
mkdir -p ~/OneDrive
install -d -m 700 ~/.davfs2
```

If `~/OneDrive` already exists, first check it is empty/unmounted and that no
other backend owns it. Preserve an existing `~/.davfs2/secrets`; do not truncate
it. Create it in your editor if necessary, with mode `600`.
Add this line, replacing the placeholder with the local WebDAV secret:

```text
http://127.0.0.1:8765/ daemon YOUR_RANDOM_LOCAL_SECRET
```

```bash
chmod 600 ~/.davfs2/secrets
```

Using `sudoedit /etc/fstab`, add this line with your **actual absolute path**:

```text
http://127.0.0.1:8765/ /home/YOUR_LINUX_USER/OneDrive davfs noauto,user,rw,noexec,nosuid,nodev 0 0
```

`~` and `$HOME` do not expand inside fstab. For paths containing spaces, use
fstab's `\040` escaping.
Arch's davfs2 packaging must permit user mounts; if `mount` reports a
helper/group permission problem, consult its installed `mount.davfs` manual
and your package's user-mount instructions rather than changing arbitrary
system binaries' permissions.

Create `~/.config/systemd/user/onedrive-davfs-mount.service`:

```ini
[Unit]
Description=OneDrive davfs mount
After=onedrive-davfs.service
Requires=onedrive-davfs.service

[Service]
Type=forking
ExecStart=/usr/bin/mount %h/OneDrive
ExecStop=/usr/bin/umount %h/OneDrive
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Start the daemon before mounting; it may need a moment to become reachable:

```bash
systemctl --user daemon-reload
systemctl --user enable --now onedrive-davfs-mount.service
findmnt --mountpoint "$HOME/OneDrive"
ls "$HOME/OneDrive"
```

Check both service state **and actual listing**. davfs2 can report a mounted
filesystem even after a startup warning about an unreachable server.

### 5.7 Configure the single-library widget

```bash
omarchy bar set onedrive-sync backend wasm_davfs
omarchy bar set onedrive-sync profileLabel OneDrive
omarchy bar set onedrive-sync profilesFile ''
omarchy bar set onedrive-sync mountPoint "$HOME/OneDrive"
omarchy bar set onedrive-sync davfsUrl http://127.0.0.1:8765/
omarchy bar set onedrive-sync daemonServiceUnit onedrive-davfs.service
omarchy bar set onedrive-sync mountServiceUnit onedrive-davfs-mount.service
omarchy bar set onedrive-sync stateDir "$HOME/.local/state/onedrive-davfs"
omarchy bar set onedrive-sync envFile "$HOME/.config/onedrive-davfs/env"
```

For the Reconnect action, set this command as **one quoted value**:

```bash
omarchy bar set onedrive-sync reconnectCommand \
  'set -a; . "$HOME/.config/onedrive-davfs/env" && set +a && ONEDRIVE_STATE_DIR="$HOME/.local/state/onedrive-davfs" python3 "$HOME/.local/share/onedrive-davfs/tools/browser-login.py"'
```

Only source a private environment file you created. A reconnect command is a
trusted shell command, not a place to paste arbitrary downloaded text.

**Checkpoint:** the panel shows the mount, Browse folders opens a tree, and
search finds known indexed names. **Add library is intentionally absent** in
this single-library mode.

## 6. Native unified accounts and libraries

This is the route for one native widget covering personal + work OneDrive,
SharePoint libraries, and Teams-backed libraries.
Complete sections 5.1 and 5.2 first.

An **account** owns one isolated login. Several **libraries** may share that
account while keeping separate mounts, state, secrets, ports, and services.
Do not create a new account profile for every folder.

### 6.1 Register your first account locally

Example: work account `work`. Replace the client and tenant IDs:

```bash
python3 ~/.local/share/onedrive-davfs/tools/profiles.py account \
  --id work --client-id YOUR_CLIENT_ID --tenant YOUR_TENANT_ID \
  --scopes 'offline_access Files.ReadWrite.All User.Read Sites.Read.All'
```

Omit `Sites.Read.All` if not needed/approved, and omit it consistently in the
next steps. For a personal account, use an ID such as `personal`, a compatible
app registration, and tenant authority `consumers` (or `common`, if deliberately
chosen). Keep the selected authority identical throughout that account's setup.

This creates `~/.config/onedrive-davfs/profiles.json` and the account directory.
It **does not sign in**.

### 6.2 Sign in to that account's directory

```bash
ONEDRIVE_ACCOUNT_DIR="$HOME/.config/onedrive-davfs/account-data/work" \
ONEDRIVE_CLIENT_ID="YOUR_CLIENT_ID" \
ONEDRIVE_TENANT_ID="YOUR_TENANT_ID" \
ONEDRIVE_SCOPES="offline_access Files.ReadWrite.All User.Read Sites.Read.All" \
python3 ~/.local/share/onedrive-davfs/tools/browser-login.py
```

For device-code login, keep the same environment variables and replace the
last line with `bash ~/.local/share/onedrive-davfs/tools/device-code-login.sh`.
Do not sign into the legacy state directory by mistake.

### 6.3 Start a temporary bootstrap host

Why? The setup tool verifies a library through an already authenticated local
backend. Your first library does not have one yet.

Make a private file, only if it does not already exist:

```bash
install -m 600 /dev/null ~/.config/onedrive-davfs/work-bootstrap.env
```

Fill it in using your editor:

```dotenv
ONEDRIVE_CLIENT_ID="YOUR_CLIENT_ID"
ONEDRIVE_TENANT_ID="YOUR_TENANT_ID"
ONEDRIVE_SCOPES="offline_access Files.ReadWrite.All User.Read Sites.Read.All"
ONEDRIVE_DRIVE_BASE="me/drive"
ONEDRIVE_BASIC_AUTH_SECRET="A_NEW_RANDOM_SECRET_FROM_OPENSSL"
```

Use a fresh `openssl rand -base64 32` secret. The client, tenant and scopes
must match the registered account and login exactly. For accounts without a
provisioned primary OneDrive, use a known accessible `drives/YOUR_DRIVE_ID`
instead of assuming `me/drive` exists.

Check that port 8790 is unused:

```bash
ss -ltn 'sport = :8790'
```

No listening row is expected. If occupied, choose another unused loopback
port and replace it in every bootstrap command below.

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

Leave that terminal running. Do not mount this bootstrap endpoint.
Its state directory must be separate from account credentials and other
library state. Do not reuse a state directory from a different account.

### 6.4 Verify and save the first library

In another terminal:

```bash
python3 ~/.local/share/onedrive-davfs/tools/profiles.py library \
  --account work \
  --source-url http://127.0.0.1:8790/ \
  --source-env ~/.config/onedrive-davfs/work-bootstrap.env \
  --selector me/drive --name "Work OneDrive" --id workdocs
```

This uses Microsoft's authenticated identity/drive resolution; it is not
just writing an unverified label.
If needed, substitute `drives/YOUR_DRIVE_ID` for `me/drive`.
The generated default mountpoint is `~/OneDrive-Libraries/workdocs`.
**Do not create that mountpoint before running this command**: the tool
requires a new, nonexistent mountpoint to avoid adopting unrelated local data.

Expected: success and a library profile under:

```text
~/.config/onedrive-davfs/library-data/workdocs/
```

Generated files include `env`, `state/`, service/timer definitions,
`fstab.entry`, and `davfs-secrets.entry`.
The last file contains a secret; do not post or commit it.

### 6.5 Activate the generated library

**Saving is not installing.** The helper does not change `/etc/fstab`, install
davfs credentials, or start any units.

1. Review `library-data/workdocs/fstab.entry`. Use `sudoedit /etc/fstab`
   to add that exact entry once. Do not add a duplicate.
2. Add the generated `davfs-secrets.entry` once to your existing
   `~/.davfs2/secrets`, preserving other entries. This file must be mode `600`.
3. Create the mountpoint from the generated registry entry.
4. Install and start this profile's units.

For this example, after completing the fstab step:

```bash
PROFILE="$HOME/.config/onedrive-davfs/library-data/workdocs"
install -d -m 700 "$HOME/.davfs2"
touch "$HOME/.davfs2/secrets"
chmod 600 "$HOME/.davfs2/secrets"
cat "$PROFILE/davfs-secrets.entry" >> "$HOME/.davfs2/secrets"
mkdir -p "$HOME/OneDrive-Libraries/workdocs" "$HOME/.config/systemd/user"
install -m 644 "$PROFILE/onedrive-davfs-workdocs.service" \
  "$PROFILE/onedrive-davfs-workdocs-mount.service" \
  "$PROFILE/onedrive-davfs-workdocs-sync.service" \
  "$PROFILE/onedrive-davfs-workdocs-sync.timer" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now onedrive-davfs-workdocs.service
```

Run the append command **only once**, not every time you restart. If your
credentials file is managed differently, merge the generated entry using your
normal private editor instead. Do not print its contents for diagnostics.

The setup tool allocates an unused port, so **do not assume it is 8790**.
The bootstrap host occupied that port during allocation. Find the new URL
and private env path without exposing the secret:

```bash
python3 - <<'PY'
import json
from pathlib import Path
registry = json.loads((Path.home() / ".config/onedrive-davfs/profiles.json").read_text())
profile = next(p for p in registry["libraries"] if p["id"] == "workdocs")
for key in ("url", "envFile", "mountPoint"):
    print(key + ": " + profile[key])
PY
```

Use those values with the status helper as in section 5.5. Once reachable,
start its timer/mount and perform a first metadata tick:

```bash
systemctl --user enable --now onedrive-davfs-workdocs-sync.timer
systemctl --user start onedrive-davfs-workdocs-sync.service
systemctl --user enable --now onedrive-davfs-workdocs-mount.service
findmnt --mountpoint "$HOME/OneDrive-Libraries/workdocs"
ls "$HOME/OneDrive-Libraries/workdocs"
```

**Checkpoint:** actual listing works, not merely a green service status.
Indexing may take many timer ticks.
Stop the temporary bootstrap host with **Ctrl+C in its own terminal** after
the real library works. Retain its private env file only if you need it again;
never delete the shared account credential directory as bootstrap cleanup.

### 6.6 Turn on the unified frontend

For the single unified widget:

```bash
omarchy bar set onedrive-sync backend wasm_davfs
omarchy bar set onedrive-sync profilesFile "$HOME/.config/onedrive-davfs/profiles.json"
omarchy bar set onedrive-sync profileSetupCommand "$HOME/.local/share/onedrive-davfs/tools/profiles.py"
omarchy-shell shell rescanPlugins
```

Open **Browse folders**. You should now see a library selector and
**Add library**. The browser exposes enabled libraries as distinct roots;
search can include multiple libraries while file actions retain their
original source mount.

If the controls are absent, check `profilesFile` on the correct widget.
Installing the backend or updating the plugin **does not set it automatically**.
The registry must exist and contain usable library profiles, not just an
account with no activated libraries.

### 6.7 More libraries and more accounts

For another library belonging to the **same account**, use the working source:

```bash
python3 ~/.local/share/onedrive-davfs/tools/profiles.py library \
  --source workdocs --selector drives/YOUR_DRIVE_ID \
  --name "Engineering documents" --id engineering
```

Then activate `engineering` using section 6.5 with that ID in every path and
unit name. A duplicate account/drive pair is rejected deliberately.

Alternatively, select a working library in the panel, choose **Add library**,
discover a library, and **Save library**. The generated profile ID may differ
from its display name; inspect the registry and use the exact generated paths.
Saving still requires the separate fstab/secret/unit activation steps.

For a **different account**, repeat sections 6.1-6.5 with a new ID, its own
login, bootstrap directory, private environment file, and unused bootstrap
port. Example: `personal` account and `personaldocs` library.
Do not bootstrap it through `workdocs`: verification rejects a different
login/tenant. Do not copy tokens between account directories.

## 7. SharePoint and Teams recipes

### 7.1 Work/school OneDrive is not a team library

Your work OneDrive is normally your personal work document collection.
A SharePoint site's **Documents** library is a separate drive. Logging in to
one does not select the other.

For rclone, configure a `work` remote for the business OneDrive and a separate
remote for each SharePoint library you want.
For native unified profiles, register the work account once, then add its
OneDrive and each permitted SharePoint library separately.

### 7.2 Find the right SharePoint site

Open the document library in your browser. Note its site location, for example:

```text
https://example.sharepoint.com/sites/Engineering
```

That is a **site URL**, not necessarily a library ID. A site may contain
Documents, Records, and other libraries. A sharing link or a URL ending in
`Forms/AllItems.aspx` is not the site root to paste into scoped discovery.
Ask the site owner if you are unsure.

**rclone:** use `rclone config`, select SharePoint site/search or known site ID,
and select the intended document library. Confirm the result:

```bash
rclone lsd engineering:
```

Then apply the service/mount/widget pattern from chapter 4.

**Native:** in Browse folders -> Add library, use:

```text
siteUrl:https://example.sharepoint.com/sites/Engineering
```

Other supported discovery scopes:

| Scope | Meaning |
| --- | --- |
| Blank | Drives of the signed-in user; not every site in the tenant. |
| `group:YOUR_GROUP_ID` | Drives of a specified Microsoft 365 group. |
| `site:YOUR_SITE_ID` | Libraries belonging to a specified site. |
| `siteUrl:https://example.sharepoint.com/sites/Engineering` | Resolve this specific site, then list its libraries. |

Before unified profiles exist, a bootstrap host can also run discovery:

```bash
python3 ~/.config/omarchy/plugins/onedrive-sync/tree_davfs.py libraries \
  ~/.config/onedrive-davfs/work-bootstrap.env http://127.0.0.1:8790/ \
  siteUrl:https://example.sharepoint.com/sites/Engineering
```

The response contains library IDs/selectors. Choose the intended library's
`drives/ID` selector, then use section 6.4 for your first library or 6.7 for
an additional one. Discovery succeeds only with suitable delegated scopes
and actual site access.

### 7.3 Teams standard channels

In Teams, open the channel's files/shared tab and choose **Open in SharePoint**.
Microsoft's interface labels may vary.

A standard channel's files live in a folder of the team's parent SharePoint
site's document library. Mount that library, then navigate to the channel's
folder. Do not assume its current display name is the exact folder path.
Use what **Open in SharePoint** actually opens.

For rclone, configure that backing library as `teamfiles` and follow chapter 4.
For native, discover the backing site/library as in 7.2 and activate it.
Native profiles represent libraries, not automatic per-channel folder mounts.

### 7.4 Teams private and shared channels

Private and shared channels have their **own SharePoint sites**, separate
from the parent team's site. A parent-team/group discovery is not guaranteed
to enumerate those sites.

Open **that specific channel** in SharePoint, obtain its backing site URL,
and repeat the SharePoint recipe using that location and an authorized account.
Team membership alone does not grant private/shared-channel access.
Shared/cross-tenant scenarios can require administrator guidance; do not
promise they work merely because the parent team is visible.

### 7.5 Chats, links, and other boundaries

Files uploaded in chats commonly live in the sender's OneDrive and are shared
with participants. They are not automatically a new Teams document library
that this plugin can mount. A "Shared with me" link also does not necessarily
identify a whole accessible drive.

This plugin does not show messages, meetings, tasks, lists, or Teams tabs.
It deals with the document libraries/files its backend can access.

### 7.6 A small acceptance test for each scenario

| Scenario | Read-only check |
| --- | --- |
| Personal OneDrive | Compare a known folder with the same personal account in the browser. |
| Work/school OneDrive | Confirm the work identity and a known work-only folder. |
| SharePoint | Confirm the site **and library**, not just a generic Documents label. |
| Standard Teams channel | Confirm the folder reached by Open in SharePoint. |
| Private/shared channel | Confirm the channel's own site and permitted files. |
| Several accounts | Search/open a known item from each; verify each path belongs to its own mount. |

Do not create/delete a cloud document just to test installation. If you need
to test writes, use an explicitly approved disposable library and understand
that the mount performs real cloud writes.

## 8. Everyday use

### Opening and finding files

**Open folder** uses the desktop's default file manager. Flea is used when
Flea is the registered directory handler:

```bash
xdg-mime query default inode/directory
```

For a functional test, run `xdg-open "$HOME/OneDrive"` using your actual mount.
Opening a file uses its default application. The rclone pending-file
reveal/select action still uses Nautilus; changing folder-opening behavior
does not change that separate action.

Native indexed search needs at least **two characters** and returns at most
100 results per library and 500 overall. Indexing must have reached an item
before it can appear. A partial failure should not hide healthy libraries.

Keyboard shortcuts in the native browser: arrows select rows/actions, Enter
activates, `T` opens terminal, `F` opens, `C` copies the folder, `X` copies its
contents, and `M` composes mail for a file. Copies do not overwrite existing
files and destinations must not be configured cloud mounts.

### Refresh, index, and transfers are different things

The refresh control refreshes the UI/backend view. Native metadata timers
consume Graph delta pages; they are not file-download jobs.
The native panel has no rclone-style **Sync now** action.
rclone's **Sync now** requests a VFS refresh, not `rclone sync`.

The native index may rebuild after an upgrade or credential/drive change.
Do not conclude that missing search results mean files were deleted.
Check the browser/mount and index progress.

### Start, pause, and reconnect

`systemctl --user enable --now ...` starts services now and enables them for
future user logins. Running before login is a different policy decision
(systemd lingering); it is not required by this guide.

Finish uploads and close files before pausing/unmounting. rclone's write
cache can hold pending uploads; do not delete it as a shortcut.

For native profiles, select the intended library before controlling it.
Reconnect signs in to the **owning account**; libraries sharing that account
will use the renewed credentials. Use the generated account-specific reconnect
command rather than a legacy command writing to another token directory.
Reauthentication or policy errors may invalidate cached metadata until a
successful verification/rebuild.

## 9. Updates, migration, and removal

### Updates

Record source revisions and keep private local rollback copies before changing
a working setup. Never commit tokens, private env files, generated credential
snippets, or private registries to this repository.

Update the plugin using Omarchy:

```bash
omarchy plugin update onedrive-sync
omarchy plugin validate ~/.config/omarchy/plugins/onedrive-sync
omarchy-shell shell rescanPlugins
```

If installed code changed but the old behavior persists, restart the shell:

```bash
omarchy restart shell
omarchy-shell shell ping
```

For the native backend, rebuild/install the matching host, component and
helpers together. Preserve account credentials, registry, fstab, and local
secrets. Stop relevant sync timers before replacing artifacts, then restart
the daemon and timers. A daemon restart can affect dependent mounts; check
actual folder access afterward. Do not blindly replace your custom unit files
with upstream defaults or run both old `wasmtime serve` and the native host
on the same port.

### Migrating a legacy native mount

A legacy single-library setup can continue with `profilesFile` blank.
Upgrading binaries does not automatically create a registry or import an
account. To migrate, create an isolated account and a new verified profile
using chapter 6, with a **new mountpoint**. Check it before retiring the old
mount. Do not repurpose a live mount/cache across unrelated identities.

Old indices without verified identity can be recrawled. This is metadata
rebuilding, not intentional removal of cloud documents.

### Remove a native library safely

Example for `engineering`: close files, then stop/disable only that library:

```bash
systemctl --user disable --now onedrive-davfs-engineering-sync.timer
systemctl --user stop onedrive-davfs-engineering-sync.service
systemctl --user disable --now onedrive-davfs-engineering-mount.service
systemctl --user disable --now onedrive-davfs-engineering.service
python3 ~/.local/share/onedrive-davfs/tools/profiles.py remove-library --id engineering
```

The helper removes a registry entry, not cloud data, cached state, or account
credentials. Remove that library's fstab and davfs secret entries deliberately
if retiring it permanently, preserving entries for other libraries.
Do not delete a shared account directory while other libraries use it.

For rclone, stop/disable only its mount service and remove the corresponding
widget entry. Removing a local remote configuration is separate from deleting
cloud files. Never use a cloud-delete or `rclone sync` command as "uninstall".

## 10. When something does not work

### Start with these three questions

1. Does the backend's authenticated read/list operation work?
2. Is the correct local folder actually mounted and readable?
3. Does the intended widget point at that backend/mount/registry?

A successful answer to one does not prove the other two.

| Symptom | Check or next step |
| --- | --- |
| No icon | `omarchy plugin list`; confirm enabled and placed in the bar. |
| No Add library / selector | Native backend selected, nonblank `profilesFile`, existing registry with activated libraries. rclone never shows these controls. |
| Login succeeded but mount fails | Compare local WebDAV secret and davfs entry privately; check fstab path and user-mount permissions. |
| HTTP 401 locally | Missing/wrong local Basic secret; this is not necessarily Microsoft login failure. |
| Need admin approval / access denied | App consent, delegated scopes, tenant, library membership and organizational policy. Ask the administrator. |
| Device-code login blocked | Try approved browser/PKCE flow; policy may still block it. |
| Wrong drive or account | Check browser login identity, selected remote/profile and verified library; do not fix by renaming the label. |
| SharePoint/Teams not in blank discovery | Use the explicit site/group scope; private/shared channels have separate sites. |
| Source belongs to another account/login | Bootstrap with the account's own `--account-dir` and matching client/tenant/scopes. |
| Save library succeeded but folder absent | Generated config still needs fstab, davfs secret, units and mount activation. |
| Missing search items | Check index progress, two-character minimum, result caps and per-library errors. |
| Mount service active, folder unusable | Inspect daemon readiness and perform an actual listing. |
| `different ... in /etc/fstab` | Keep fstab authoritative; use `mount MOUNTPOINT`, not conflicting duplicate `mount.davfs -o` options. |
| Address already in use | Distinct RC ports or native library ports; no duplicate host on the bootstrap port. |
| Import error in login/setup tool | Install matching helper scripts together, including `auth_common.py`. |
| Old behavior after plugin update | Validate installed copy, then restart shell; rescan alone may leave a cached component. |
| RC unavailable, but rclone mount works | Verify matching port/auth policy; plugin cannot supply RC credentials. Do not expose unauthenticated RC. |
| Duplicate widget configured incorrectly | Inspect the exact `bar.layout` entry rather than the first widget with the same ID. |

### Safe diagnostic commands

Single native setup:

```bash
systemctl --user status onedrive-davfs.service onedrive-davfs-mount.service --no-pager
systemctl --user status onedrive-davfs-sync.timer --no-pager
journalctl --user -u onedrive-davfs.service --no-pager -n 40
python3 ~/.config/omarchy/plugins/onedrive-sync/tree_davfs.py status \
  ~/.config/onedrive-davfs/env http://127.0.0.1:8765/
findmnt --mountpoint "$HOME/OneDrive"
```

Unified setup:

```bash
python3 ~/.config/omarchy/plugins/onedrive-sync/profiles_davfs.py status \
  ~/.config/onedrive-davfs/profiles.json
systemctl --user status onedrive-davfs-workdocs.service \
  onedrive-davfs-workdocs-mount.service onedrive-davfs-workdocs-sync.timer --no-pager
```

rclone:

```bash
systemctl --user status rclone-personal.service --no-pager
journalctl --user -u rclone-personal.service --no-pager -n 40
rclone lsd personal:
findmnt --mountpoint "$HOME/OneDrive-Personal"
```

Substitute actual profile/service names. Status/registry responses and logs
may include private account names, paths, or filenames: redact them before
sharing. Never share OAuth tokens, env contents, davfs secrets, or a full
rclone configuration. Do not place secrets directly in command arguments
for troubleshooting.

## 11. Final checklist and references

You are done when:

1. Each chosen account can authenticate with an approved app and permissions.
2. Each remote/library resolves to the intended identity and collection.
3. Each library has its own mountpoint and service configuration.
4. Actual read-only folder listing works, not just service status.
5. Native access verification succeeds and its metadata timer progresses,
   or rclone's expected RC/status behavior is confirmed.
6. The correct widget opens that mount; native unified controls appear only
   when intentionally configured.
7. A logout/login restores enabled services, and you know how to inspect a
   failure without exposing credentials.

No cloud write test is required by this book.

### Further reading

- [Plugin overview and settings](README.md)
- [Frontend manifest: authoritative setting names](manifest.json)
- [Compatible backend source](https://github.com/uhansen/onedrive-davfs/tree/7f3076a)
- [Compatible backend installation guide](https://github.com/uhansen/onedrive-davfs/blob/7f3076a/INSTALL.md)
- [rclone OneDrive configuration and custom applications](https://rclone.org/onedrive/)
- [rclone mount and cache behavior](https://rclone.org/commands/rclone_mount/)
- [rclone RC and its security model](https://rclone.org/rc/)
- [Microsoft: Teams-connected SharePoint sites](https://learn.microsoft.com/en-us/sharepoint/teams-connected-sites)
- [Microsoft: redirect URI rules, including localhost](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url)
- [Microsoft: delegated permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)

Microsoft portal labels and rclone prompts can change. Select by meaning and
verify the resulting account/library instead of relying on old menu numbers.
