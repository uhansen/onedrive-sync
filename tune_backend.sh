#!/usr/bin/env bash
# Rendering is the default; applying and restoring require explicit flags.
set -euo pipefail
command -v python3 >/dev/null || { echo "Requires Python 3: omarchy pkg add python" >&2; exit 1; }
exec python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/tune_backend.py" "$@"
