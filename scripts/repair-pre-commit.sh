#!/usr/bin/env bash
# Repair only pre-commit inside this worktree's existing Python environment.
# Explicit opt-in: never run during git commit, shell startup, or direnv.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="$ROOT/.venv/bin/python"
LOCK="$ROOT/uv.lock"

# Git normally shares hook storage across linked worktrees. Installing a
# worktree-specific Python entrypoint there can break other worktrees.
# Repair the hooks from the primary checkout only.
GIT_DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-dir)"
COMMON_DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)"
if [ "$(cd -- "$GIT_DIR" && pwd -P)" != "$(cd -- "$COMMON_DIR" && pwd -P)" ]; then
  echo "REFUSED: linked worktree shares hooks; run repair from primary checkout." >&2
  exit 2
fi


if [ ! -x "$PYTHON" ] || [ ! -f "$ROOT/.venv/pyvenv.cfg" ]; then
  echo "REFUSED: missing project .venv. Create a reviewed, isolated venv first." >&2
  exit 2
fi

# Confirm the interpreter belongs to this checkout's virtual environment.
# Also read the exact pre-commit version from the reviewed uv.lock.
PIN="$("$PYTHON" - "$ROOT" "$LOCK" <<'PY'
import pathlib
import sys
import tomllib

root = pathlib.Path(sys.argv[1]).resolve()
venv = (root / ".venv").resolve()
if pathlib.Path(sys.prefix).resolve() != venv:
    raise SystemExit("REFUSED: selected Python belongs to a different environment")
if sys.prefix == sys.base_prefix:
    raise SystemExit("REFUSED: selected Python is not a virtual environment")
project = tomllib.loads((root / "pyproject.toml").read_text())
if project.get("project", {}).get("name") != "ansible-workstation":
    raise SystemExit("REFUSED: project metadata mismatch")
dev = project.get("dependency-groups", {}).get("dev", [])
if not any(item.startswith("pre-commit>=") for item in dev):
    raise SystemExit("REFUSED: pre-commit is absent from the dev group")
lock = tomllib.loads(pathlib.Path(sys.argv[2]).read_text())
pins = [item["version"] for item in lock.get("package", [])
        if item.get("name") == "pre-commit"]
if len(pins) != 1:
    raise SystemExit("REFUSED: uv.lock must contain exactly one pre-commit version")
print(pins[0])
PY
)"

# Never run uv sync (exact sync may remove unrelated packages).
# This scoped, explicit install updates only pre-commit and its requirements
# in the checked, existing worktree-local environment.
if ! "$PYTHON" - "$PIN" <<'PY'
from importlib.metadata import PackageNotFoundError, version
import sys

try:
    actual = version("pre-commit")
except PackageNotFoundError:
    actual = None
if actual != sys.argv[1]:
    sys.exit(1)
PY
then
  if ! command -v uv >/dev/null 2>&1; then
    echo "REFUSED: uv not installed. Run 'mise install' explicitly." >&2
    exit 2
  fi
  uv pip install --python "$PYTHON" "pre-commit==$PIN"
fi

"$PYTHON" -m pre_commit --version

# Reinstall the standard hooks without overwriting unrelated custom scripts.
# pre-commit install preserves existing hooks by migrating them when possible.
# The hook entrypoint must use this same Python interpreter.
cd -- "$ROOT"
"$PYTHON" -m pre_commit install --hook-type pre-commit --hook-type commit-msg
echo "OK: pre-commit repaired for this worktree (Python: $PYTHON)."
