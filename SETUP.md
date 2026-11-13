# Install the plugin, install the backend, configure accounts

Follow these steps in order on **Omarchy Linux**, as your normal user.
Supported hardware is x86-64 or ARM64, including Apple Silicon already running
Omarchy Linux, **not macOS**. These scripts do not install the operating system
or hardware drivers.

The setup uses `onedrive-davfs`, not rclone. It mounts files on demand; it is
**not a full offline mirror** of your OneDrive.

## 1. Install the Omarchy plugin

```bash
omarchy plugin add https://github.com/uhansen/onedrive-sync.git --enable
```

Review Omarchy's trust prompt and choose the widget's bar position.
If the plugin is already installed, do not add another copy.

## 2. Install the backend via Bash

In your terminal, run **without sudo**:

```bash
SETUP="$HOME/.config/omarchy/plugins/onedrive-sync/setup.sh"
bash "$SETUP" install
```

This script installs/enables the plugin if missing, installs required packages
through `omarchy pkg add`, and calls `install_backend.sh` to install the verified
backend bundle into `~/.local`. Package installation may ask for your sudo
password. ARM64 and older/non-glibc x86-64 systems also get native build tools;
if Cargo is missing, the script installs Rust. Source builds download locked
Cargo dependencies.

Existing plugin files and account configuration are not overwritten. If a
backend service or sync timer is already running, installation stops before
making changes: skip this step for a working installation. For upgrades, close
open cloud files and stop the relevant mount, timer and daemon first.
The installer does not sign in or start account services.

From an existing source checkout, `bash ./setup.sh install` performs both
installation steps. Keep the scripts, Python helpers and `artifacts/` together.

## 3. Configure your accounts and libraries

An **account** is a Microsoft login; a **library** is its own OneDrive or an
accessible SharePoint/Teams document library. Each account gets separate
credentials. Its libraries share that login, but have separate mounts and
services. Nothing is copied between cloud accounts.

### Have an approved application ID ready

Microsoft sign-in and organization approval cannot be automated away.
Use an approved **public-client** app registration:

1. In the [Microsoft Entra portal](https://entra.microsoft.com/), create or
   obtain an app registration supporting your intended account types.
   Personal accounts require support for personal Microsoft accounts.
2. Under Authentication, add a mobile/desktop platform and
   `http://localhost/callback` for browser login. Enable public-client flows
   for device-code login.
3. Add delegated Microsoft Graph permissions `Files.ReadWrite.All`,
   `User.Read` and `offline_access`. Site discovery additionally uses
   `Sites.Read.All`; request it only when needed and approved.
4. Copy the application/client ID. For work accounts, obtain the correct
   tenant ID. Do not create or supply a client secret.

Your administrator may need to grant consent or approve the device. Setup
cannot bypass tenant policy, MFA, licensing, or library membership.

The following examples use the `SETUP` variable from step 2. Replace
`YOUR_CLIENT_ID`, `YOUR_TENANT_ID` and example site URLs before running them.

### Personal OneDrive

```bash
bash "$SETUP" account \
  --account personal --library personal --name "Personal OneDrive" \
  --client-id YOUR_CLIENT_ID --tenant consumers
```

Sign in with the intended personal Microsoft account. The default library
selector is `me/drive`: that account's own OneDrive.

### Microsoft 365 work/school OneDrive

```bash
bash "$SETUP" account \
  --account work --library workdocs --name "Work OneDrive" \
  --client-id YOUR_CLIENT_ID --tenant YOUR_TENANT_ID --sites
```

Sign in with the intended work/school account. `--sites` requests the optional
site-discovery permission for later SharePoint/Teams setup. Omit it if you do
not need that permission or it is not approved.

### SharePoint

For the already registered `work` account:

```bash
bash "$SETUP" account \
  --account work --library engineering --name "Engineering documents" \
  --site-url https://example.sharepoint.com/sites/Engineering
```

Use the **site root**, not a sharing link or `Forms/AllItems.aspx` URL.
The script lists that site's accessible document libraries and asks you to
choose one. It does not choose the first result automatically.

If this is the account's first library, also supply `--client-id` and
`--tenant`; a primary OneDrive is not required.

For a known drive ID, use `--selector drives/YOUR_DRIVE_ID` instead of
`--site-url`. This avoids site discovery and does not request `Sites.Read.All`.
An existing account's consent/scopes are never silently broadened.

### Teams

In Teams, open the channel's files/shared tab and choose **Open in SharePoint**.
Use the backing site's root URL:

```bash
bash "$SETUP" account \
  --account work --library teamdocs --name "Team documents" \
  --site-url https://example.sharepoint.com/sites/YourTeam
```

Standard channels usually share the parent team's document library; the
channel folder is inside it. Private/shared channels have their **own backing
site**: use that channel's site, not the parent team's. Chat attachments are
not automatically a separate Teams library.

For a known Microsoft 365 group, `--group-id YOUR_GROUP_ID` can replace
`--site-url`. Discovery only covers the specified site/group, not every site
in the tenant.

### What the account script automates

It registers a new account or reuses its existing matching configuration,
launches Microsoft's login helper if credentials are absent, starts and
cleans up a temporary loopback bootstrap host, verifies access, and generates
the library's private configuration. No manual bootstrap environment files,
secrets or port selection are needed.

It then asks you to type **yes** before activation. Activation:

- Backs up `/etc/fstab` before appending the generated user-mount entry.
- Merges the generated WebDAV secret into `~/.davfs2/secrets` with mode `600`.
- Installs and enables the generated user daemon, sync timer and mount units.
- Waits for the backend, verifies cloud access and reads the mounted directory.
- Configures the OneDrive widget's unified library selector.

Existing fstab entries, credentials and customized units are preserved.
Conflicting entries or nonempty mountpoints cause an explicit error, not an
overwrite. `sudo` is used only for the fstab backup/append and, if necessary,
adding your user to davfs2's configured mount group. If group membership was
added, **log out and back in**, then resume activation below.

The mount is `~/OneDrive-Libraries/LIBRARY_ID`. Libraries appear in
`~/.config/onedrive-davfs/profiles.json`; private per-library files are under
`~/.config/onedrive-davfs/library-data/LIBRARY_ID/`.

**Existing single-library/rclone users:** activation switches the widget to
native unified profiles. It does not migrate or stop existing mounts or import
their credentials. Review that confirmation before accepting. These examples
assume one OneDrive widget; multiple widget instances need explicit manual
placement/settings.

### Resume, add accounts, or use device-code sign-in

If activation was cancelled or failed after saving a profile:

```bash
bash "$SETUP" activate --library workdocs
```

Activation is repeatable without duplicating matching fstab/secret entries.
Do not register the same library ID again. To add another library for the same
account, reuse `--account work` with a **new** `--library` ID.
For another Microsoft login, choose a **new account ID** and provide its own
client/tenant settings; existing account credentials are never replaced.

Add `--login device` to an account command if browser sign-in is unavailable.
Complete the Microsoft verification code yourself. Use `--no-activate` to
generate configuration without changing fstab, services or widget settings.
For all options:

```bash
bash "$SETUP" account --help
```

## 4. Verify

For the personal example:

```bash
findmnt --mountpoint "$HOME/OneDrive-Libraries/personal"
ls "$HOME/OneDrive-Libraries/personal"
python3 "$HOME/.config/omarchy/plugins/onedrive-sync/profiles_davfs.py" status \
  "$HOME/.config/onedrive-davfs/profiles.json"
```

Compare a known folder with the same account/library in your browser. For
Teams, use the location reached through **Open in SharePoint**.
The authenticated status should report `accessVerified` with no sync error.
The timer updates metadata about every 30 seconds; initial indexing takes
longer. Search needs two characters and a sufficiently populated index.
File downloads happen on demand; uploads normally start after closing a file.

If setup fails, read its explicit error, fix consent/permissions or the
reported local conflict, and rerun `activate` for the saved library. Do not
delete credential directories or upload historical `lost+found` files
blindly. Never share token files, WebDAV secrets or unredacted status output.

## Optional performance tuning

Defaults remain conservative: roughly 30-second delta polling, davfs2's
50 MiB cache, 10-second post-close upload delay and 60-second directory refresh.
Polling controls cloud metadata discovery, not background downloads. Cache and
poll delays are not a guaranteed sum; opening a file can trigger revalidation.

The bundled backend batches outbound writes and reuses bounded HTTPS
connections. An unchanged delta cursor avoids decoding the full snapshot;
account/drive identity is still checked on every tick. Writes and sync remain
serialized to protect credentials and indexes. This is not parallel cloud upload.
For transport troubleshooting, `ONEDRIVE_HTTP_POOL_IDLE_PER_HOST=0` in the
generated environment file disables connection reuse after a daemon restart
(default 1 idle connection per host, at most 8 globally).

Generate **only the options you want**, without applying them:

```bash
TUNING="$HOME/.config/onedrive-davfs/performance-personal"
bash "$HOME/.config/omarchy/plugins/onedrive-sync/tune_backend.sh" \
  --output "$TUNING" --library personal \
  --mount "$HOME/OneDrive-Libraries/personal" \
  --poll-seconds 10 --cache-mib 512 --upload-delay 1 --dir-refresh 10 \
  --max-upload-mib 1024 --perf-log
```

Use the actual library ID and mountpoint. Omit `--library` for legacy
`onedrive-davfs.service` / `onedrive-davfs-sync.timer` installations.
The output directory must be new; nothing existing is overwritten. It must
remain in place because generated service drop-ins reference `performance.env`.
Omitted options leave existing settings unchanged.
The polling drop-in replaces timer triggers with the standard 15-second
boot trigger and your selected interval; review it before using a customized
calendar/timer schedule.

To apply after installing this backend version, review generated files, close
cloud files and let pending uploads finish. Copy the generated `systemd-user/`
drop-in directories into `~/.config/systemd/user/`, preserving existing files.
Back up `~/.davfs2/davfs2.conf`, then merge `davfs2.conf.snippet` into the
section for that exact mountpoint (create the file if absent). Do not duplicate
an existing mount section or replace unrelated settings.
Run `systemctl --user daemon-reload`; stop the library's mount service, restart
its daemon and sync timer, then start the mount service again. For `personal`,
the units are `onedrive-davfs-personal-mount.service`,
`onedrive-davfs-personal.service`, and `onedrive-davfs-personal-sync.timer`.
Do not unmount with unsaved/open files. Remounting is required for davfs changes.

Larger caches use more disk; davfs can exceed the configured size for open
files. Lower upload delays can upload temporary/intermediate editor files.
Faster polling increases Microsoft Graph traffic and can cause throttling.
Keep local copies of important pending uploads; do not clear `lost+found`.

The upload limit defaults to **64 MiB**. `--max-upload-mib 1024` explicitly
allows up to 1 GiB. Uploads spool into private, unlinked local files before
cloud transmission, using disk up to the configured per-request limit and
bounded 10 MiB transfer chunks. Unknown-length bodies are size-checked too.
Insufficient local storage fails explicitly. The existing approximately
five-minute request budget still applies: large files on slow connections can
time out. Interrupted sessions are cancelled when possible or expire at
Microsoft; uploads are not blindly retried or resumed across daemon restarts.
Cloud quota, policy, and Graph limits still apply.

`--perf-log` enables privacy-safe host stage timings in the journal and
successful sync-stage timings in authenticated status. Turn it off with
`ONEDRIVE_PERF_LOG=0` in the generated environment file and restart the daemon.
Inspect `journalctl --user -u onedrive-davfs-personal.service`; timing records
omit URLs, file/account names and credentials. Other ordinary logs/status may
contain private details; review before sharing. Timings distinguish queue,
credential, identity, snapshot and network delays rather than assuming a slow
tick means slow Graph.

Advanced, opt-in `--cached-dav-reads` lets cached HEAD/PROPFIND metadata requests
run while a transfer/sync holds the writer slot. It never falls back to Graph:
missing/stale cache entries return 503 until synchronization makes them available.
Leave it off if applications require immediate network lookup of uncached names.
This does not parallelize GET downloads or uploads.

Offline verification on a disposable account fixture reduced peak host RSS
during 32 MiB upload intake from about 130 MiB to 37 MiB. With an intentionally
blocked writer, optional cached directory lookup took about 0.8 ms instead of
516 ms. These are isolated memory/contention measurements, **not Microsoft
upload throughput or promised cloud visibility**. The 34,416-node native
snapshot fixture took about 11 ms to decode, so snapshot parsing alone does
not explain the observed multi-second sync ticks.

To undo tuning, remove only the generated `90-performance.conf` drop-ins,
restore the affected davfs options from your backup, reload systemd and repeat
the controlled restart/remount. Do not remove customized drop-ins or credentials.
