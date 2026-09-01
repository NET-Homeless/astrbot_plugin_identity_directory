#!/usr/bin/env python3
"""Version Management & Synchronization Script.

Single Source of Truth (SSOT): metadata.yaml
Synchronizes version with:
- metadata.yaml
- web/package.json
- pyproject.toml

Usage:
  python3 scripts/bump_version.py --check
  python3 scripts/bump_version.py --get
  python3 scripts/bump_version.py patch
  python3 scripts/bump_version.py minor
  python3 scripts/bump_version.py major
  python3 scripts/bump_version.py 0.3.0 [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
METADATA_FILE = ROOT_DIR / "metadata.yaml"
PACKAGE_JSON_FILE = ROOT_DIR / "web" / "package.json"
PYPROJECT_FILE = ROOT_DIR / "pyproject.toml"

SEMVER_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def read_metadata_version() -> str:
    if not METADATA_FILE.exists():
        raise FileNotFoundError(f"Missing {METADATA_FILE}")
    content = METADATA_FILE.read_text(encoding="utf-8")
    match = re.search(r"^version:\s*[\"']?([^\"'\s#]+)[\"']?", content, re.MULTILINE)
    if not match:
        raise ValueError(f"Could not find 'version' field in {METADATA_FILE}")
    return match.group(1).strip()


def read_package_json_version() -> str:
    if not PACKAGE_JSON_FILE.exists():
        raise FileNotFoundError(f"Missing {PACKAGE_JSON_FILE}")
    data = json.loads(PACKAGE_JSON_FILE.read_text(encoding="utf-8"))
    version = data.get("version")
    if not version:
        raise ValueError(f"Missing 'version' in {PACKAGE_JSON_FILE}")
    return str(version).strip()


def read_pyproject_version() -> str | None:
    if not PYPROJECT_FILE.exists():
        return None
    content = PYPROJECT_FILE.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    return match.group(1).strip() if match else None


def calculate_bump(current: str, action: str) -> str:
    match = SEMVER_PATTERN.match(current)
    if not match:
        raise ValueError(f"Current version '{current}' is not a valid Semantic Version (x.y.z)")
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))

    if action == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if action == "minor":
        return f"{major}.{minor + 1}.0"
    if action == "major":
        return f"{major + 1}.0.0"
    raise ValueError(f"Unknown bump action '{action}'")


def update_metadata(new_version: str, dry_run: bool = False) -> None:
    content = METADATA_FILE.read_text(encoding="utf-8")
    new_content = re.sub(
        r"^(version:\s*)[\"']?[^\"'\s#]+[\"']?",
        rf"\g<1>{new_version}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if content == new_content and read_metadata_version() != new_version:
        raise RuntimeError(f"Failed to replace version in {METADATA_FILE}")
    if not dry_run:
        METADATA_FILE.write_text(new_content, encoding="utf-8")


def update_package_json(new_version: str, dry_run: bool = False) -> None:
    content = PACKAGE_JSON_FILE.read_text(encoding="utf-8")
    new_content = re.sub(
        r'("version":\s*)"[^"]+"',
        rf'\1"{new_version}"',
        content,
        count=1,
    )
    if not dry_run:
        PACKAGE_JSON_FILE.write_text(new_content, encoding="utf-8")


def update_pyproject(new_version: str, dry_run: bool = False) -> None:
    if not PYPROJECT_FILE.exists():
        return
    content = PYPROJECT_FILE.read_text(encoding="utf-8")
    if not re.search(r'^version\s*=\s*["\'][^"\']+["\']', content, re.MULTILINE):
        return
    new_content = re.sub(
        r'^(version\s*=\s*)["\'][^"\']+["\']',
        rf'\g<1>"{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if not dry_run:
        PYPROJECT_FILE.write_text(new_content, encoding="utf-8")


def check_sync() -> int:
    try:
        meta_ver = read_metadata_version()
        pkg_ver = read_package_json_version()
        pyproj_ver = read_pyproject_version()
    except Exception as e:
        print(f"❌ Version check failed: {e}", file=sys.stderr)
        return 1

    if not SEMVER_PATTERN.match(meta_ver):
        print(f"❌ Invalid SemVer in metadata.yaml: '{meta_ver}'", file=sys.stderr)
        return 1

    mismatches = []
    if meta_ver != pkg_ver:
        mismatches.append(f"web/package.json ({pkg_ver})")
    if pyproj_ver is not None and pyproj_ver != meta_ver:
        mismatches.append(f"pyproject.toml ({pyproj_ver})")

    if mismatches:
        print("❌ Version mismatch detected with metadata.yaml (SSOT: {meta_ver})!", file=sys.stderr)
        for mismatch in mismatches:
            print(f"   mismatch: {mismatch}", file=sys.stderr)
        print("💡 Run 'python3 scripts/bump_version.py <version>' to synchronize.", file=sys.stderr)
        return 1

    print(f"✅ Version in sync: v{meta_ver} (metadata.yaml, package.json, pyproject.toml)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage and synchronize project versions.")
    parser.add_argument(
        "target",
        nargs="?",
        help="Target version (e.g. 0.3.0) or bump action (patch, minor, major)",
    )
    parser.add_argument("--check", action="store_true", help="Check if all versions are in sync")
    parser.add_argument("--get", action="store_true", help="Print current metadata version")
    parser.add_argument("--dry-run", action="store_true", help="Preview version changes without writing")

    args = parser.parse_args()

    if args.check:
        return check_sync()

    current_version = read_metadata_version()

    if args.get:
        print(current_version)
        return 0

    if not args.target:
        parser.print_help()
        return 1

    target = args.target.strip().lstrip("v")
    if target in {"patch", "minor", "major"}:
        new_version = calculate_bump(current_version, target)
    else:
        if not SEMVER_PATTERN.match(target):
            print(f"❌ Error: '{target}' is not a valid Semantic Version (x.y.z)", file=sys.stderr)
            return 1
        new_version = target

    prefix = "[DRY-RUN] " if args.dry_run else ""
    print(f"{prefix}Bumping version: {current_version} -> {new_version}")

    update_metadata(new_version, dry_run=args.dry_run)
    update_package_json(new_version, dry_run=args.dry_run)
    update_pyproject(new_version, dry_run=args.dry_run)

    print(
        f"{prefix}✅ Successfully updated metadata.yaml, web/package.json & pyproject.toml to v{new_version}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
