#!/usr/bin/env bash
# Called by direnv from .envrc. Offline: create only an EMPTY project .venv.
# No dependency resolution, downloads, secrets, git changes, or hook installation.
set -u

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" || exit 2
VENV="$ROOT/.venv"
MARKER="$VENV/.ansible-workstation-uv-managed"

if [ -L "$VENV" ]; then
  echo "ansible-workstation: symlinked .venv is not allowed; refusing activation." >&2
  exit 1
fi
if [ -e "$VENV" ]; then
  if [ ! -f "$VENV/pyvenv.cfg" ] || [ ! -x "$VENV/bin/python" ]; then
    echo "ansible-workstation: existing .venv is incomplete; preserved unchanged." >&2
    echo "Run 'mise run recover-venv' explicitly after reviewing its contents." >&2
    exit 1
  fi
  # Never mark a pre-existing environment as managed: avoid destructive sync.
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "ansible-workstation: uv is unavailable; run 'mise install' explicitly." >&2
  exit 0
fi
if ! command -v python >/dev/null 2>&1; then
  echo "ansible-workstation: Python unavailable; run 'mise install' explicitly." >&2
  exit 0
fi

PYTHON="$(command -v python)"
if ! "$PYTHON" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)
PY
then
  echo "ansible-workstation: Python 3.12 not selected by mise; no .venv created." >&2
  exit 0
fi

# No Python downloads, no network, no uv sync, no package install.
# Never overwrite an existing environment. A first-time empty venv is safe
# to sync later using the separately guarded 'mise run sync' task.
if ! uv venv --offline --no-python-downloads --python "$PYTHON" "$VENV" >&2; then
  echo "ansible-workstation: offline uv venv creation failed; inspect .venv." >&2
  exit 1
fi
if [ ! -f "$VENV/pyvenv.cfg" ] || [ ! -x "$VENV/bin/python" ]; then
  echo "ansible-workstation: uv venv reported success but Python is missing." >&2
  exit 1
fi
touch "$MARKER"
echo "ansible-workstation: created empty offline .venv (run 'mise run init' for dependencies)." >&2
