#!/usr/bin/env python3
"""Copy a library item locally, without overwriting or writing into cloud mounts."""

import argparse
from pathlib import Path
import subprocess


def copy_entry(source, destination, forbidden_roots, contents=False):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).expanduser().resolve()
    for root in forbidden_roots:
        root = Path(root).expanduser().resolve()
        if destination == root or root in destination.parents:
            raise ValueError("Copy destination must be outside all OneDrive library mounts")
    if source.is_dir() and (destination == source or source in destination.parents):
        raise ValueError("Cannot copy a directory into itself")
    destination.mkdir(parents=True, exist_ok=True)
    source_text = str(source) + ("/." if contents else "")
    subprocess.run(["cp", "-R", "--no-clobber", "--", source_text, str(destination) + "/"], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--forbidden-root", action="append", default=[])
    parser.add_argument("--contents", action="store_true")
    args = parser.parse_args()
    try:
        copy_entry(args.source, args.destination, args.forbidden_root, args.contents)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + "\n")
