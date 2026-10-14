#!/usr/bin/env python3
"""Read-only aggregation of authenticated per-library plugin endpoints."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse

from tree_davfs import join_url, load_basic_secret, request_json

MAX_LIBRARIES = 32
MAX_RESULTS = 500


def load_profiles(filename):
    raw = Path(os.path.expanduser(filename)).read_bytes()
    document = json.loads(raw)
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("Unsupported profile registry version")
    libraries = document.get("libraries")
    if not isinstance(libraries, list) or len(libraries) > MAX_LIBRARIES:
        raise ValueError("Profile registry must contain at most 32 libraries")
    used = {key: set() for key in ("id", "port", "mountPoint", "stateDir", "envFile")}
    result = []
    validated = []
    used_units = set()
    for original in libraries:
        if not isinstance(original, dict):
            raise ValueError("Invalid library profile")
        library = dict(original)
        if not isinstance(library.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", library["id"]):
            raise ValueError("Invalid library profile ID")
        if not isinstance(library.get("url"), str) or not isinstance(library.get("name", ""), str):
            raise ValueError("Library URL and name must be strings")
        if not isinstance(library.get("enabled", True), bool):
            raise ValueError("Library enabled flag must be boolean")
        for key in ("daemonServiceUnit", "mountServiceUnit"):
            unit = library.get(key, "")
            if not isinstance(unit, str) or (unit and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*\.service", unit)):
                raise ValueError("Invalid library service unit")
            if unit:
                if unit in used_units:
                    raise ValueError("Library service units must not be shared")
                used_units.add(unit)
        url = urllib.parse.urlsplit(library["url"])
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1")
                or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")
                or not url.port):
            raise ValueError("Library endpoints must be loopback HTTP roots with an explicit port")
        library["url"] = library["url"].rstrip("/") + "/"
        library["port"] = url.port
        for key in ("mountPoint", "stateDir", "envFile"):
            raw_path = library.get(key, "")
            if not isinstance(raw_path, str) or not os.path.isabs(os.path.expanduser(raw_path)):
                raise ValueError(f"Invalid {key} in library profile")
            value = os.path.realpath(os.path.expanduser(raw_path))
            if value == "/":
                raise ValueError(f"Invalid {key} in library profile")
            library[key] = value
        for key in used:
            if library[key] in used[key]:
                raise ValueError(f"Duplicate library {key}")
            used[key].add(library[key])
        for previous in validated:
            for key in ("mountPoint", "stateDir"):
                for previous_key in ("mountPoint", "stateDir"):
                    common = os.path.commonpath((previous[previous_key], library[key]))
                    if common in (previous[previous_key], library[key]):
                        raise ValueError(f"Overlapping library {key}")
        if os.path.commonpath((library["mountPoint"], library["stateDir"])) in (
                library["mountPoint"], library["stateDir"]):
            raise ValueError("Library mount and state directories must not overlap")
        validated.append(library)
        if library.get("enabled", True):
            result.append(library)
    result.sort(key=lambda profile: (profile.get("name", ""), profile["id"]))
    return result, hashlib.sha256(raw).hexdigest()


def fetch(profile, action, value=""):
    secret, error = load_basic_secret(profile["envFile"])
    if not secret:
        return {"ok": False, "error": error or "Missing WebDAV secret"}
    paths = {
        "status": ("/_status", None),
        "tree": ("/_tree", {"path": value or "/"}),
        "search": ("/_search", {"q": value}),
        "libraries": ("/_libraries", discovery_query(value) if action == "libraries" else None),
    }
    endpoint, query = paths[action]
    return request_json(join_url(profile["url"], endpoint, query), secret, timeout=15)


def discovery_query(value):
    if not value:
        return None
    for prefix, key in (("group:", "groupId"), ("site:", "siteId"), ("siteUrl:", "siteUrl")):
        if value.startswith(prefix) and value[len(prefix):]:
            return {key: value[len(prefix):]}
    raise ValueError("Discovery scope must be group:<id>, site:<id>, or siteUrl:<https URL>")


def virtual_path(profile_id, path="/"):
    return "/@" + profile_id + ("" if path == "/" else path)


def qualify(profile, entry):
    path = entry.get("path", "/")
    if not isinstance(path, str) or not path.startswith("/") or any(
            segment in (".", "..") for segment in path.split("/")):
        raise ValueError("Daemon returned an invalid item path")
    return dict(entry, path=virtual_path(profile["id"], path), sourcePath=path,
                profileId=profile["id"], libraryLabel=profile.get("name", profile["id"]),
                mountPoint=profile["mountPoint"])


def aggregate(profiles, action, value="", profile_id=""):
    if action in ("tree", "libraries") and (action == "libraries" or value != "/"):
        if action == "tree":
            match = re.fullmatch(r"/@([A-Za-z0-9_-]+)(/.*)?", value)
            if not match:
                raise ValueError("Select a library before browsing its folders")
            profile_id, value = match[1], match[2] or "/"
        profile = next((profile for profile in profiles if profile["id"] == profile_id), None)
        if not profile:
            raise ValueError("Library profile is unavailable or has been removed")
        response = fetch(profile, action, value)
        if action == "tree" and response.get("ok"):
            response = qualify(profile, response)
            response["children"] = [qualify(profile, child) for child in response.get("children", [])
                                    if child.get("isDir") is True]
        return response
    if action == "tree":
        return {"ok": True, "path": "/", "name": "Libraries", "isDir": True, "children": [
            qualify(profile, {"path": "/", "name": profile.get("name", profile["id"]), "isDir": True})
            for profile in profiles
        ]}
    if action not in ("status", "search"):
        raise ValueError("Unknown aggregate action")
    if action == "search" and len(value) < 2:
        return {"ok": True, "ready": True, "results": [], "truncated": False}
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda profile: fetch(profile, action, value), profiles))
    errors = [{"profileId": profile["id"], "label": profile.get("name", profile["id"]),
               "error": response.get("error") or response.get("lastSyncError") or "Library index is unavailable"}
              for profile, response in zip(profiles, responses)
              if not response.get("ok") or response.get("error") or response.get("lastSyncError")
              or (action == "search" and not response.get("ready"))]
    if action == "status":
        return {"ok": True, "indexEnabled": True, "profiles": profiles,
                "libraryStatuses": [{"profileId": profile["id"], "status": response}
                                    for profile, response in zip(profiles, responses)],
                "partial": bool(errors), "errors": errors,
                "crawlComplete": bool(profiles) and all(response.get("crawlComplete") for response in responses),
                "totalDirs": sum(response.get("totalDirs", 0) for response in responses),
                "totalFiles": sum(response.get("totalFiles", 0) for response in responses)}
    results = []
    for profile, response in zip(profiles, responses):
        if response.get("ok") and response.get("ready"):
            results.extend(qualify(profile, entry) for entry in response.get("results", [])[:100])
    results.sort(key=lambda entry: (entry["libraryLabel"], entry["profileId"], entry["sourcePath"]))
    truncated = len(results) > MAX_RESULTS or any(
        response.get("truncated") or len(response.get("results", [])) > 100 for response in responses)
    return {"ok": True, "ready": any(response.get("ready") for response in responses),
            "query": value, "results": results[:MAX_RESULTS], "truncated": truncated,
            "partial": bool(errors), "errors": errors}


def main():
    try:
        action, registry = sys.argv[1:3]
        value = sys.argv[3] if len(sys.argv) > 3 else ("" if action == "libraries" else "/")
        profile_id = sys.argv[4] if len(sys.argv) > 4 else ""
        profiles, revision = load_profiles(registry)
        response = aggregate(profiles, action, value, profile_id)
        response["profileRevision"] = revision
    except (OSError, ValueError) as error:
        response = {"ok": False, "error": str(error)}
    print(json.dumps(response))


if __name__ == "__main__":
    main()
