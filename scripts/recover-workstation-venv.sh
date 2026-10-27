#!/usr/bin/env bash
# Explicit, non-destructive recovery for a BROKEN .venv, not used by direnv.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV="$ROOT/.venv"
if [ ! -e "$VENV" ] && [ ! -L "$VENV" ]; then
  echo "No .venv exists. Run 'direnv reload' or 'mise run init'."
  exit 0
fi

if [ -f "$VENV/pyvenv.cfg" ] && [ -x "$VENV/bin/python" ]; then
  echo "REFUSED: .venv has a working Python; it is not a broken venv." >&2
  echo "Do not archive a potentially healthy environment automatically." >&2
  exit 2
fi

# Preserve every byte. No rm, cleanup or replacement of existing backups.
BACKUP="$ROOT/.venv.incomplete-$(date +%Y%m%d-%H%M%S)-$$"
if [ -e "$BACKUP" ] || [ -L "$BACKUP" ]; then
  echo "REFUSED: backup path exists ($BACKUP)" >&2
  exit 2
fi

mv -- "$VENV" "$BACKUP"
echo "Archived broken .venv to: $BACKUP"
echo "No package install was performed. Run 'direnv reload' to create a new empty .venv,"
echo "then 'mise run init' to install reviewed locked dependencies and Git hooks."
