#!/usr/bin/env python3
"""Authenticated JSON helper for onedrive-davfs plugin endpoints.

Reads the local Basic-auth shared secret from the daemon env file (same
trust boundary as tools/sync-tick.sh) and calls GET /_status or GET /_tree
with X-OneDrive-Plugin: 1. Never prints the secret or OAuth tokens.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def load_basic_secret(env_path):
    path = os.path.expanduser(env_path or "")
    if not path or not os.path.isfile(path):
        return None, "env file not found"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() != "ONEDRIVE_BASIC_AUTH_SECRET":
                    continue
                secret = value.strip().strip("'").strip('"')
                if secret:
                    return secret, None
    except OSError as exc:
        return None, str(exc)
    return None, "ONEDRIVE_BASIC_AUTH_SECRET missing"


def join_url(base, path, query=None):
    root = (base or "http://127.0.0.1:8765/").rstrip("/")
    url = root + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url


def request_json(url, secret, timeout=8):
    token = base64.b64encode(("daemon:" + secret).encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": "Basic " + token,
        "X-OneDrive-Plugin": "1",
        "Accept": "application/json",
    }
    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "ok": False,
            "error": "HTTP %s" % exc.code,
            "status": exc.code,
            "body": body[:400],
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error": str(exc) or "unreachable"}
    try:
        parsed = json.loads(body)
    except ValueError:
        return {"ok": False, "error": "invalid JSON from daemon", "status": status}
    if isinstance(parsed, dict):
        parsed.setdefault("ok", True)
        return parsed
    return {"ok": False, "error": "unexpected JSON shape"}


def fail(message):
    print(json.dumps({"ok": False, "error": message}))
    return 0


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    env_file = sys.argv[2] if len(sys.argv) > 2 else "~/.config/onedrive-davfs/env"
    davfs_url = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8765/"
    path = sys.argv[4] if len(sys.argv) > 4 else "/"

    if action not in ("status", "tree"):
        return fail("unknown action")

    secret, err = load_basic_secret(env_file)
    if not secret:
        return fail(err or "missing secret")

    if action == "status":
        payload = request_json(join_url(davfs_url, "/_status"), secret, timeout=4)
    else:
        payload = request_json(
            join_url(davfs_url, "/_tree", {"path": path or "/"}),
            secret,
            timeout=12,
        )
        if isinstance(payload, dict) and isinstance(payload.get("children"), list):
            payload["children"] = [
                child
                for child in payload["children"]
                if isinstance(child, dict) and child.get("isDir") is True
            ]
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
