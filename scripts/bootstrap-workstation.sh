#!/usr/bin/env bash
# Explicit initialization, only after reviewing mise.toml and uv.lock.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$ROOT"
echo "=== ansible-workstation: locked toolchain bootstrap ==="

# uv-project.sh refuses unrelated, corrupted or unmanaged environments.
bash "$ROOT/scripts/uv-project.sh" sync

if [ ! -x "$ROOT/.venv/bin/python" ] || [ ! -x "$ROOT/.venv/bin/ansible" ]; then
  echo "REFUSED: project venv lacks Python or Ansible after sync." >&2
  exit 2
fi
"$ROOT/.venv/bin/python" -m pre_commit --version
bash "$ROOT/scripts/repair-pre-commit.sh"
echo "PASS: project Python, Ansible, pre-commit and hooks initialized."
