#!/usr/bin/env python3
"""Package AstrBot Plugin for Distribution and GitHub Releases.

Creates:
- dist/{plugin_name}-v{version}.zip
- dist/{plugin_name}-v{version}.zip.sha256

Excludes development artifacts (e.g. web/src, tests, __pycache__, .git).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
METADATA_FILE = ROOT_DIR / "metadata.yaml"


def read_plugin_metadata() -> tuple[str, str]:
    if not METADATA_FILE.exists():
        raise FileNotFoundError(f"Missing {METADATA_FILE}")
    content = METADATA_FILE.read_text(encoding="utf-8")

    name_match = re.search(r"^name:\s*[\"']?([^\"'\s#]+)[\"']?", content, re.MULTILINE)
    version_match = re.search(r"^version:\s*[\"']?([^\"'\s#]+)[\"']?", content, re.MULTILINE)

    if not name_match or not version_match:
        raise ValueError(f"Could not parse 'name' or 'version' from {METADATA_FILE}")

    return name_match.group(1).strip(), version_match.group(1).strip()


def collect_release_files() -> list[tuple[Path, str]]:
    """Collect files to package into the zip archive with relative arcnames."""
    files: list[tuple[Path, str]] = []

    # Single root files
    root_files = [
        "metadata.yaml",
        "main.py",
        "README.md",
        "LICENSE",
        "pyproject.toml",
        "_manifest.json",
    ]
    for filename in root_files:
        p = ROOT_DIR / filename
        if p.is_file():
            files.append((p, filename))

    # Directories
    directories = ["core", "pages"]
    for dir_name in directories:
        d = ROOT_DIR / dir_name
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            # Ignore cache & temp files
            if "__pycache__" in p.parts or p.suffix in {".pyc", ".pyo", ".DS_Store"}:
                continue
            rel_path = p.relative_to(ROOT_DIR).as_posix()
            files.append((p, rel_path))

    return sorted(files, key=lambda x: x[1])


def compute_sha256(file_path: Path) -> str:
    sha = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def package_plugin(output_dir: Path, dry_run: bool = False) -> list[Path]:
    name, version = read_plugin_metadata()
    files = collect_release_files()

    versioned_zip = output_dir / f"{name}-v{version}.zip"
    versioned_sha = output_dir / f"{name}-v{version}.zip.sha256"

    created_paths = [versioned_zip, versioned_sha]

    print(f"📦 Packaging plugin '{name}' v{version}")
    print(f"   Collected {len(files)} files to package:")
    for _, arcname in files[:8]:
        print(f"     - {arcname}")
    if len(files) > 8:
        print(f"     - ... ({len(files) - 8} more files)")

    if dry_run:
        print(f"[DRY-RUN] Would write {versioned_zip} and {versioned_sha}")
        return created_paths

    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean existing dist folder if needed
    for old_file in output_dir.glob("*"):
        if old_file.is_file():
            old_file.unlink()

    # Build versioned zip with internal root directory matching plugin name
    # for clean extraction in AstrBot plugin folders
    with zipfile.ZipFile(versioned_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path, arcname in files:
            # Package with top-level folder
            target_arcname = f"{name}/{arcname}"
            zf.write(file_path, target_arcname)

    # Generate Checksum
    v_sha = compute_sha256(versioned_zip)

    # Write individual .sha256 file
    versioned_sha.write_text(f"{v_sha}  {versioned_zip.name}\n", encoding="utf-8")

    print(f"✅ Created: {versioned_zip} ({versioned_zip.stat().st_size / 1024:.1f} KB)")
    print(f"✅ Created: {versioned_sha} (SHA-256: {v_sha})")

    return created_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Package AstrBot plugin into distributable zip files.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT_DIR / "dist",
        help="Destination directory for built zip packages (default: ./dist)",
    )
    parser.add_argument("--dry-run", action="store_true", help="List files without creating archive")

    args = parser.parse_args()

    try:
        package_plugin(args.output_dir, dry_run=args.dry_run)
    except Exception as e:
        print(f"❌ Packaging failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
