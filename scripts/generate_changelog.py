#!/usr/bin/env python3
"""Generate Structured and Categorized Markdown Changelog for GitHub Releases.

Parses Conventional Commits between the previous tag and HEAD (or current commit).
Supports direct push workflows and PR merges.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
METADATA_FILE = ROOT_DIR / "metadata.yaml"
REPO_URL = "https://github.com/NET-Homeless/astrbot_plugin_identity_directory"

CATEGORIES = [
    ("feat", "🚀 Features / 新特性"),
    ("fix", "🐛 Bug Fixes / 问题修复"),
    ("perf", "⚡ Performance / 性能优化"),
    ("refactor", "♻️ Refactoring / 代码重构"),
    ("docs", "📝 Documentation / 文档变更"),
    ("chore", "🔧 Maintenance / 工程与构建"),
    ("ci", "🤖 CI & Automation / 流水线更新"),
    ("test", "🧪 Testing / 测试用例"),
]

CONVENTIONAL_RE = re.compile(
    r"^(?P<type>feat|fix|perf|refactor|docs|chore|ci|test|build|style)"
    r"(?:\((?P<scope>[^\)]+)\))?"
    r"(?P<breaking>!)?"
    r":\s*(?P<desc>.+)$",
    re.IGNORECASE,
)


def get_current_version() -> str:
    if not METADATA_FILE.exists():
        return "0.0.0"
    content = METADATA_FILE.read_text(encoding="utf-8")
    m = re.search(r"^version:\s*[\"']?([^\"'\s#]+)[\"']?", content, re.MULTILINE)
    return m.group(1).strip() if m else "0.0.0"


def get_previous_tag() -> str | None:
    try:
        res = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "HEAD~1"],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        tag = res.stdout.strip()
        return tag or None
    except Exception:
        return None


def get_commits_range(prev_tag: str | None) -> list[tuple[str, str, str]]:
    """Return list of (short_hash, subject, author)."""
    git_range = f"{prev_tag}..HEAD" if prev_tag else "HEAD"
    try:
        res = subprocess.run(
            ["git", "log", git_range, "--pretty=format:%h%x09%s%x09%an"],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        commits = []
        for line in lines:
            parts = line.split("\t")
            if len(parts) == 3:
                commits.append((parts[0], parts[1], parts[2]))
        return commits
    except Exception:
        return []


def generate_changelog(version: str, prev_tag: str | None) -> str:
    commits = get_commits_range(prev_tag)
    current_tag = f"v{version}"

    categorized: dict[str, list[str]] = {key: [] for key, _ in CATEGORIES}
    other_commits: list[str] = []
    breaking_changes: list[str] = []

    for short_hash, subject, author in commits:
        match = CONVENTIONAL_RE.match(subject)
        commit_link = f"[`{short_hash}`]({REPO_URL}/commit/{short_hash})"

        if match:
            ctype = match.group("type").lower()
            scope = match.group("scope")
            is_breaking = bool(match.group("breaking"))
            desc = match.group("desc").strip()

            scope_prefix = f"**{scope}**: " if scope else ""
            entry = f"- {scope_prefix}{desc} ({commit_link}) - @{author}"

            if is_breaking:
                breaking_changes.append(entry)

            # Map build/style to chore
            if ctype in {"build", "style"}:
                ctype = "chore"

            if ctype in categorized:
                categorized[ctype].append(entry)
            else:
                other_commits.append(f"- {subject} ({commit_link}) - @{author}")
        else:
            other_commits.append(f"- {subject} ({commit_link}) - @{author}")

    # Build Markdown Content
    md_lines: list[str] = [
        f"## Release {current_tag}",
        "",
    ]

    if breaking_changes:
        md_lines.append("### ⚠️ Breaking Changes / 重大变更")
        md_lines.extend(breaking_changes)
        md_lines.append("")

    has_content = False
    for ctype, title in CATEGORIES:
        entries = categorized.get(ctype, [])
        if entries:
            has_content = True
            md_lines.append(f"### {title}")
            md_lines.extend(entries)
            md_lines.append("")

    if other_commits:
        has_content = True
        md_lines.append("### 📌 Other Changes / 其他提交")
        md_lines.extend(other_commits)
        md_lines.append("")

    if not has_content:
        md_lines.append("日常功能维护与质量优化。")
        md_lines.append("")

    # Add Compare link
    if prev_tag:
        compare_url = f"{REPO_URL}/compare/{prev_tag}...{current_tag}"
        md_lines.append(f"🔍 **Full Changelog**: [{prev_tag} → {current_tag}]({compare_url})")
    else:
        commits_url = f"{REPO_URL}/commits/{current_tag}"
        md_lines.append(f"🔍 **Full Changelog**: [{current_tag}]({commits_url})")

    return "\n".join(md_lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate rich Markdown changelog for release.")
    parser.add_argument("--version", help="Current version (defaults to metadata.yaml)")
    parser.add_argument("--output", type=Path, help="Write markdown output to file")

    args = parser.parse_args()

    version = args.version or get_current_version()
    prev_tag = get_previous_tag()

    changelog_md = generate_changelog(version, prev_tag)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(changelog_md, encoding="utf-8")
        print(f"✅ Wrote changelog to {args.output}")
    else:
        print(changelog_md)

    return 0


if __name__ == "__main__":
    sys.exit(main())
