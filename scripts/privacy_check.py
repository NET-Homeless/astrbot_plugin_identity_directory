#!/usr/bin/env python3
"""Public-source privacy scanner.

The scanner deliberately contains no project-specific personal-data denylist.
It checks high-confidence credential, local-path, email, and account-ID shapes
with regular expressions, then allows generic test placeholders through an
explicit allowlist. Diagnostics never include the matched value.

With staged changes, only added lines are scanned. With ``--all`` (or when no
staged additions exist), all tracked source files are scanned.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".svelte",
        ".json",
        ".yaml",
        ".yml",
        ".md",
        ".sh",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".properties",
    }
)
SOURCE_FILENAMES = frozenset({".env", ".env.example"})
IGNORED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "pages",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "test-results",
        "playwright-report",
        "blob-report",
    }
)

# Public, generic fixtures that are safe to keep in an open-source repository.
# This is an allowlist of examples, not a list of somebody's real identifiers.
ALLOWLIST_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "identifier": (re.compile(r"(?:100001|10000000[1-9]|123456789)"),),
    "email": (
        re.compile(
            r"(?i)[^@\s]+@(?:example\.(?:com|org|net)|"
            r"(?:[a-z0-9-]+\.)?(?:invalid|test)|users\.noreply\.github\.com)"
        ),
    ),
    "path": (
        re.compile(
            r"(?ix)(?:/tmp(?:/.*)?|/workspace(?:/.*)?|/app(?:/.*)?|"
            r"/Users/(?:user|username|example|test)(?:/.*)?|"
            r"/home/(?:user|username|example|test)(?:/.*)?|"
            r"[A-Z]:\\Users\\(?:user|username|example|test)(?:\\.*)?)"
        ),
    ),
    "secret_value": (
        re.compile(
            r"(?ix)^(?:\$\{\{[^}]+\}\}|\$\{[^}]+\}|<[^>]+>|"
            r"(?:sk-)?(?:test|example|dummy|fake|mock|sample|placeholder|"
            r"redacted|masked|secret(?:[-_ ]?value)?|changeme)"
            r"(?:[-_.][a-z0-9]+)*)$"
        ),
    ),
}

SECRET_FIELD_PATTERN = (
    r"(?:[a-z0-9]+[_-])*"
    r"(?:api[_-]?key|access[_-]?(?:key|token)|auth(?:orization)?|bearer|"
    r"client[_-]?secret|private[_-]?key|password|passwd|secret|token)"
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    rf"(?ix)\b(?P<key>{SECRET_FIELD_PATTERN})\b\s*[:=]\s*"
    rf"(?P<quote>['\"])(?P<value>[^'\"\r\n]{{8,}})(?P=quote)"
)

EMAIL_PATTERN = re.compile(r"(?i)(?P<value>\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b)")
LOCAL_PATH_PATTERN = re.compile(
    r"""(?ix)
    (?P<value>
        /Users/[A-Za-z0-9._-]+(?:/[^\s"'<>)]*)*
        |/home/[A-Za-z0-9._-]+(?:/[^\s"'<>)]*)*
        |[A-Za-z]:\\Users\\[A-Za-z0-9._-]+(?:\\[^\s"'<>)]*)*
    )
    """
)
IDENTIFIER_PATTERN = re.compile(
    r"(?ix)\b(?P<key>(?:[a-z0-9]+[_-])*"
    r"(?:qq(?:[_-]?(?:id|number|uin))?|uin|user|group|account|sender|member)"
    r"(?:[_-]?id)?)\b\s*[:=,]\s*['\"]?(?P<value>\d{5,12})['\"]?"
)

TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI/兼容 API Key", re.compile(r"\bsk-[A-Za-z0-9_-]{40,}\b")),
    ("Anthropic API Key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{30,}\b")),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("GitHub Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("GitHub Fine-grained Token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "JWT",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]{10,})?\b"),
    ),
    (
        "私钥块",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |DSA |EC |PGP )?PRIVATE KEY-----", re.IGNORECASE),
    ),
    (
        "Bearer Token",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}\b"),
    ),
)


def _allowlisted(kind: str, value: str) -> bool:
    candidate = value.strip().strip("\"'`")
    return any(pattern.fullmatch(candidate) for pattern in ALLOWLIST_PATTERNS.get(kind, ()))


def _location(file_path: str, line_no: int) -> str:
    return f"[{file_path}{f' (line {line_no})' if line_no else ''}]"


def scan_line(file_path: str, line: str, line_no: int = 0) -> list[str]:
    """Return redacted diagnostics for one source line."""
    violations: list[str] = []
    location = _location(file_path, line_no)

    for match in IDENTIFIER_PATTERN.finditer(line):
        if not _allowlisted("identifier", match.group("value")):
            violations.append(
                f"{location} 检测到疑似真实账号 ID 字面量（字段 {match.group('key')}）；请改用公共测试占位符"
            )

    for match in EMAIL_PATTERN.finditer(line):
        if not _allowlisted("email", match.group("value")):
            violations.append(f"{location} 检测到未列入白名单的邮箱地址；请移除或改用 example/test 域名")

    for match in LOCAL_PATH_PATTERN.finditer(line):
        if not _allowlisted("path", match.group("value")):
            violations.append(f"{location} 检测到本机绝对路径；请改用相对路径或公共示例路径")

    for match in SECRET_ASSIGNMENT_PATTERN.finditer(line):
        if not _allowlisted("secret_value", match.group("value")):
            violations.append(
                f"{location} 检测到敏感字段 {match.group('key')} 的非占位字面量；请移除凭据或改用公共占位符"
            )

    for label, pattern in TOKEN_PATTERNS:
        if pattern.search(line):
            violations.append(f"{location} 检测到疑似 {label}；请移除真实凭据")

    return list(dict.fromkeys(violations))


def get_staged_diff_lines() -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "diff", "--cached", "-U0"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("无法读取 Git 暂存区")
    if not result.stdout.strip():
        return []

    lines: list[tuple[str, str]] = []
    current_file = "unknown"
    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if line.startswith("+") and not line.startswith("+++"):
            lines.append((current_file, line[1:]))
    return lines


def _tracked_source_paths() -> list[tuple[str, Path]]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("无法读取 Git 跟踪文件列表")

    paths: list[tuple[str, Path]] = []
    for raw_path in result.stdout.split(chr(0)):
        if not raw_path:
            continue
        rel_path = Path(raw_path)
        if rel_path.suffix not in SOURCE_EXTENSIONS and rel_path.name not in SOURCE_FILENAMES:
            continue
        if any(part in IGNORED_DIRS for part in rel_path.parts):
            continue
        absolute_path = ROOT_DIR / rel_path
        if absolute_path.is_file():
            paths.append((rel_path.as_posix(), absolute_path))
    return paths


def scan_entire_repository() -> list[str]:
    """Scan tracked source files without reading ignored or untracked files."""
    violations: list[str] = []
    for rel_path, path in _tracked_source_paths():
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_no, line in enumerate(content.splitlines(), start=1):
            violations.extend(scan_line(rel_path, line, line_no=line_no))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Public-source privacy and credential scanner.")
    parser.add_argument("--all", action="store_true", help="Force scan all tracked repository source files")
    args = parser.parse_args()

    try:
        staged_lines = get_staged_diff_lines()
        if args.all or not staged_lines:
            violations = scan_entire_repository()
        else:
            violations = [
                violation for file_path, line in staged_lines for violation in scan_line(file_path, line)
            ]
    except (OSError, RuntimeError) as exc:
        print(f"隐私扫描器无法完成：{exc}", file=sys.stderr)
        return 2

    unique_violations = list(dict.fromkeys(violations))
    if unique_violations:
        print("❌ 隐私与敏感信息检查失败：", file=sys.stderr)
        for violation in unique_violations:
            print(f"  • {violation}", file=sys.stderr)
        print("\n💥 检查已拦截：请移除风险内容或改用公共占位符。", file=sys.stderr)
        return 1

    print("✅ 隐私深度检查通过（仅扫描高置信风险格式）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
