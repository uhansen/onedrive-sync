#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash setup.sh install
  bash setup.sh account --account ID --library ID [account/library options]
  bash setup.sh activate --library ID

install   Install/enable the plugin, install required packages and the backend.
account   Sign in, choose a library and offer to activate it.
activate  Resume activation of an already generated library.

Use "bash setup.sh account --help" for account/library options.
Run on Omarchy Linux as your normal user, without sudo.
EOF
}

case "${1:-}" in
  -h | --help) usage; exit 0 ;;
  install | account | activate) action="$1"; shift ;;
  *) usage >&2; exit 2 ;;
esac

[[ "$(uname -s)" == Linux ]] || { echo "Setup requires Omarchy Linux, not macOS." >&2; exit 1; }
case "$(uname -m)" in
  x86_64 | aarch64 | arm64) ;;
  *) echo "Setup supports only x86-64 and ARM64." >&2; exit 1 ;;
esac
(( EUID != 0 )) || { echo "Run setup as your normal user, without sudo." >&2; exit 1; }
command -v omarchy >/dev/null || { echo "Setup requires omarchy on PATH." >&2; exit 1; }

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$action" != install ]]; then
  command -v python3 >/dev/null || { echo "Install the backend first: bash setup.sh install" >&2; exit 1; }
  exec python3 "$script_dir/setup_account.py" "$action" "$@"
fi

(( $# == 0 )) || { usage >&2; exit 2; }
active="$(systemctl --user list-units --state=active,activating,reloading,deactivating --no-legend --plain 'onedrive-davfs*.service' 'onedrive-davfs*.timer')"
[[ -z "$active" ]] || {
  echo "A OneDrive backend is running; nothing was changed." >&2
  echo "For an existing installation, skip install and use the account/activate commands." >&2
  echo "For an upgrade, close cloud files and stop its mount, sync timer and daemon first." >&2
  exit 1
}

omarchy pkg add git
plugin_dir="$HOME/.config/omarchy/plugins/onedrive-sync"
if [[ -e "$plugin_dir" || -L "$plugin_dir" ]]; then
  [[ ! -L "$plugin_dir" ]] || { echo "Refusing a symlinked plugin directory." >&2; exit 1; }
  omarchy plugin validate "$plugin_dir"
  omarchy plugin enable onedrive-sync
else
  omarchy plugin add https://github.com/uhansen/onedrive-sync.git --enable
fi

omarchy pkg add python curl openssl xdg-utils davfs2 python-gobject
mode="$(cd "$script_dir" && python3 -c 'from install_backend import check_platform; print(check_platform())')"
if [[ "$mode" == source ]]; then
  omarchy pkg add base-devel cmake pkgconf
  if ! command -v cargo >/dev/null; then
    omarchy pkg add rust
  fi
fi
bash "$script_dir/install_backend.sh"
echo "Plugin and backend installed. Next: configure an account as described in SETUP.md."
