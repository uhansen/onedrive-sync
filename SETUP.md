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
