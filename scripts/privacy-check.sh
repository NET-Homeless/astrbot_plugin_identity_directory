#!/usr/bin/env bash
# 全仓库隐私检查：阻止真实邮箱、API 密钥、本机绝对路径进入版本库。
#
# 扫描 Git index 中的全部文件，而不是只检查暂存区的变更文件。
# .gitignore 只负责防止本地凭据和运行时产物进入版本库，不是扫描边界。
# 纯二进制资产和依赖锁文件跳过；刻意保留的示例行可以加上 privacy-allow 标记。
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

# 模式定义（ERE）
EMAIL='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
EMAIL_ALLOW='@(([A-Za-z0-9-]+\.)*example\.(com|org|net)|[A-Za-z0-9.-]*\.(invalid|test)|localhost|users\.noreply\.github\.com)'

# 本机路径：家目录字面值 + 各平台的用户目录形态。
HOME_ESCAPED=$(printf '%s' "${HOME:-}" | sed 's/[.[\*^$()+?{|]/\\&/g')
# privacy-allow: 这里是检查模式，不是实际本机路径。
PATHS="/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|C:\\\\Users\\\\"

# 密钥：按真实凭据的格式与长度特征匹配，短的演示值不会命中。
# privacy-allow: 这里是检查模式，不是实际凭据。
KEYS='sk-[A-Za-z0-9_-]{40,}|sk-ant-[A-Za-z0-9_-]{30,}|AIza[0-9A-Za-z_-]{35}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{17,}\.eyJ[A-Za-z0-9_-]{17,}'

[ -n "$HOME_ESCAPED" ] && PATHS="$HOME_ESCAPED|$PATHS"
fail=0

email_check_skipped() {
  case "$1" in
    # pyproject.toml/Cargo.toml authors 字段是作者刻意公开的署名邮箱。
    Cargo.toml | pyproject.toml) return 0 ;;
    *) return 1 ;;
  esac
}

emit() {
  # $1=类别 $2=文件 $3=grep -n 的输出（行号:内容，可多行）
  if [ "$fail" -eq 0 ]; then
    echo "✗ 隐私检查未通过 —— 以下内容不应进入仓库：" >&2
  fi
  fail=1
  printf '%s\n' "$3" | sed "s|^|  [$1] $2:|" >&2
}

while IFS= read -r -d '' file; do
  case "$file" in
    # 锁文件与二进制资产：无手写内容，跳过以免噪声。
    *.lock | */pnpm-lock.yaml | pnpm-lock.yaml | *.png | *.jpg | *.jpeg | *.gif | *.webp | *.ico | *.woff | *.woff2 | *.gz | *.zip)
      continue
      ;;
  esac

  [ -f "$file" ] || continue
  # grep -I 将包含 NUL 的文件视为二进制；空文件也无需扫描。
  LC_ALL=C grep -Iq . -- "$file" 2>/dev/null || continue

  if ! email_check_skipped "$file"; then
    hits=$(LC_ALL=C grep -nE "$EMAIL" -- "$file" | LC_ALL=C grep -vE "$EMAIL_ALLOW" | LC_ALL=C grep -v 'privacy-allow' || true)
    [ -n "$hits" ] && emit "邮箱" "$file" "$hits"
  fi

  hits=$(LC_ALL=C grep -nE "$PATHS" -- "$file" | LC_ALL=C grep -v 'privacy-allow' || true)
  [ -n "$hits" ] && emit "本机路径" "$file" "$hits"

  hits=$(LC_ALL=C grep -nE "$KEYS" -- "$file" | LC_ALL=C grep -v 'privacy-allow' || true)
  [ -n "$hits" ] && emit "疑似密钥" "$file" "$hits"
done < <(git ls-files --cached -z)

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  echo "  处理方式：移除上述内容后重新检查；若确认是刻意保留的演示值，" >&2
  echo "  在该行加 privacy-allow 注释标记。" >&2
  exit 1
fi

echo "✓ 隐私检查通过（已扫描整个仓库）"
