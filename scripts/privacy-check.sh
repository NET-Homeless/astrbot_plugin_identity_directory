#!/usr/bin/env bash
# Public-source privacy scanner entry point.
# Keep all detection and redaction logic in the Python implementation.
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
exec python3 "$repo_root/scripts/privacy_check.py" --all "$@"
