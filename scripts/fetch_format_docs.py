#!/usr/bin/env python3
"""Refresh the local cache of Compositor's upstream format documentation.

Usage:
  python3 fetch_format_docs.py [--auto] [--for-version N] [--max-age-days D] [target-dir]

Downloads the two upstream docs into <target-dir> (default:
<skill>/references/upstream/) and writes metadata.json recording when the
cache was fetched and the highest project format version it covers.

With --auto, the script first checks the existing cache and exits as a fast
no-op when it is fresh. It refreshes only when the cache is missing, does
not cover --for-version N, is older than --max-age-days (default 7), or has
missing doc files. If the network is unreachable but a usable cache exists,
--auto keeps it and exits 0 so the calling workflow can proceed offline.

Runs on any Python 3 using only the standard library — no third-party
packages, no version restrictions.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import urllib.request
from pathlib import Path

SOURCES = {
    "project-format.md": "https://raw.githubusercontent.com/robbietilton/Compositor/main/docs/project-format.md",
    "writing-comp-files.md": "https://raw.githubusercontent.com/robbietilton/Compositor/main/docs/writing-comp-files.md",
}


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "compositor-skill-doc-fetcher"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def max_version(text):
    """Extract the highest format version from the doc header line
    ('versions 1-21'); returns None when the header is absent."""
    match = re.search(r"versions?\s*1\s*[–-]\s*(\d+)", text[:400])
    return int(match.group(1)) if match else None


def atomic_write(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_metadata(target):
    try:
        return json.loads((target / "metadata.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def cache_age_days(meta):
    """Age of the cache in days, or None when unknown/unparseable."""
    try:
        fetched = datetime.datetime.fromisoformat(meta["fetched_at"])
    except Exception:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - fetched).total_seconds() / 86400.0


def auto_reasons(target, meta, for_version, max_age_days):
    """Why the cache needs a refresh; empty list means it is fresh."""
    reasons = []
    if meta is None:
        return ["no cache metadata"]
    covered = meta.get("max_version")
    if for_version is not None:
        if not isinstance(covered, int):
            reasons.append("cache records no covered version")
        elif covered < for_version:
            reasons.append("cache covers up to v{}, project declares v{}".format(covered, for_version))
    age = cache_age_days(meta)
    if age is None:
        reasons.append("cache fetch time unknown")
    elif age > max_age_days:
        reasons.append("cache is {:.1f} days old (limit {})".format(age, max_age_days))
    for name in SOURCES:
        if not (target / name).is_file():
            reasons.append("cached file missing: {}".format(name))
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the local cache of Compositor upstream docs.")
    parser.add_argument("target_dir", nargs="?", default=None,
                        help="cache directory (default: <skill>/references/upstream)")
    parser.add_argument("--auto", action="store_true",
                        help="no-op when the cache is fresh; refresh only when needed")
    parser.add_argument("--for-version", type=int, default=None,
                        help="project format version the cache must cover")
    parser.add_argument("--max-age-days", type=float, default=7.0,
                        help="with --auto, refresh when the cache is older than this (default: 7)")
    args = parser.parse_args()

    target = (Path(args.target_dir).expanduser().resolve() if args.target_dir
              else Path(__file__).resolve().parent.parent / "references" / "upstream")
    meta = load_metadata(target)

    if args.auto:
        reasons = auto_reasons(target, meta, args.for_version, args.max_age_days)
        if not reasons:
            print("Doc cache fresh (covers v{}, fetched {}); nothing to do.".format(
                meta.get("max_version"), meta.get("fetched_at")))
            return 0
        for reason in reasons:
            print("Refreshing: {}".format(reason))

    target.mkdir(parents=True, exist_ok=True)
    metadata = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "max_version": None,
        "sources": dict(SOURCES),
    }
    for name, url in SOURCES.items():
        try:
            text = fetch(url)
        except Exception as exc:
            print("ERROR: could not fetch {}: {}".format(name, exc), file=sys.stderr)
            if args.auto and meta is not None:
                print("Keeping the existing cache and proceeding offline; "
                      "bundled notes remain the fallback.", file=sys.stderr)
                return 0
            print("No usable cache exists; the bundled notes remain the fallback.", file=sys.stderr)
            return 1
        atomic_write(target / name, text)
        if name == "project-format.md":
            metadata["max_version"] = max_version(text)
        print("fetched {} ({} bytes)".format(name, len(text.encode("utf-8"))))

    atomic_write(target / "metadata.json", json.dumps(metadata, indent=2) + "\n")
    print("Cache refreshed: {} (covers up to format version {})".format(target, metadata["max_version"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
