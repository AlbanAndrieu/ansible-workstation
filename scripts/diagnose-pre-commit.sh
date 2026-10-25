#!/usr/bin/env bash
# Read-only diagnostics. Works even when .venv, uv or pre-commit are absent.
# Does not source environment files, contact networks or change Git hooks.
set -u

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" || {
  echo "ERROR: cannot locate the checkout" >&2
  exit 2
}
cd -- "$ROOT" || exit 2

echo "=== ansible-workstation pre-commit diagnostic (read only) ==="
printf 'Project: %s\n' "$ROOT"
printf 'Working directory: %s\n' "$PWD"
printf 'Branch: '
git branch --show-current 2>/dev/null || echo "(not available)"
printf 'HEAD: '
git rev-parse --short HEAD 2>/dev/null || echo "(not available)"
printf 'Git worktree: '
git rev-parse --show-toplevel 2>/dev/null || echo "(not available)"

GIT_DIR="$(git rev-parse --path-format=absolute --git-dir 2>/dev/null)" || GIT_DIR=""
COMMON_DIR="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || COMMON_DIR=""
if [ -n "$GIT_DIR" ] && [ -n "$COMMON_DIR" ] && [ "$GIT_DIR" != "$COMMON_DIR" ]; then
  echo "Git hook storage: shared linked worktree (do not reinstall from here)"
else
  echo "Git hook storage: primary checkout or standalone repository"
fi
printf 'Configured hooks path: '
git config --get core.hooksPath 2>/dev/null || echo "(Git default)"
HOOK="$(git rev-parse --path-format=absolute --git-path hooks/pre-commit 2>/dev/null)" || HOOK=""
if [ -n "$HOOK" ] && [ -f "$HOOK" ]; then
  printf 'Active pre-commit hook: %s\n' "$HOOK"
  sed -n '1,2p' "$HOOK"
else
  echo "Active pre-commit hook: absent"
fi

PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  printf 'Project Python: ABSENT (%s)\n' "$PYTHON"
  echo "Cause of silent command: `test -x .venv/bin/python || exit 1` exits without a message."
else
  printf 'Project Python: %s\n' "$PYTHON"
  "$PYTHON" --version 2>&1 || true
  "$PYTHON" - <<'PY'
from importlib.metadata import PackageNotFoundError, version
import pathlib
import sys

print(f"Python sys.prefix: {pathlib.Path(sys.prefix).resolve()}")
try:
    print(f"pre-commit installed: {version('pre-commit')}")
except PackageNotFoundError:
    print("pre-commit installed: NO")
PY
fi

for entry in ".node_cache/" ".config/requirements-lock.txt"; do
  printf 'Git ignore rule for %s: ' "$entry"
  explanation="$(git check-ignore --no-index -v -- "$entry" 2>/dev/null)" || explanation=""
  if [ -n "$explanation" ]; then
    printf '%s\n' "$explanation"
  else
    echo "NONE (local .gitignore may be outdated)"
  fi
done
echo "=== End of read-only diagnostic ==="
