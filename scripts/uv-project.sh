#!/usr/bin/env bash
# A fail-closed uv entrypoint. This script never uses the system Ansible fallback.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
ACTION="${1:-check}"

case "${ACTION}" in
  lock | sync | check | info) ;;
  *)
    printf 'Usage: %s {info|lock|check|sync}\n' "$0" >&2
    exit 2
    ;;
esac

# A global uv override can otherwise direct exact sync to a DIFFERENT project
# or even a system Python installation. Refuse before touching any packages.
for key in UV_PROJECT UV_PROJECT_ENVIRONMENT UV_NO_PROJECT UV_NO_WORKSPACE; do
  if [ -n "${!key:-}" ]; then
    printf 'REFUSED: %s is set. Run in a clean project shell.\n' "$key" >&2
    exit 2
  fi
done

# Validate metadata with the system Python. No imports from .venv needed.
check_metadata() {
  python3 - "$ROOT" <<'PY'
from pathlib import Path
import sys
import tomllib

root = Path(sys.argv[1])
path = root / "pyproject.toml"
if not path.is_file():
    raise SystemExit("REFUSED: pyproject.toml not found in checkout")
project = tomllib.loads(path.read_text()).get("project", {})
deps = project.get("dependencies", [])
if project.get("name") != "ansible-workstation":
    raise SystemExit("REFUSED: wrong uv project")
if project.get("requires-python") != ">=3.12,<3.15":
    raise SystemExit("REFUSED: unexpected requires-python")
if not any(s.startswith("ansible-core>=2.21,") for s in deps):
    raise SystemExit("REFUSED: expected ansible-core dependency missing")
if "dev" not in tomllib.loads(path.read_text()).get("dependency-groups", {}):
    raise SystemExit("REFUSED: dev dependency group missing")
print("PASS: explicit ansible-workstation project metadata")
PY
}

check_lock() {
  python3 - "$ROOT" <<'PY'
from pathlib import Path
import sys
import tomllib

path = Path(sys.argv[1]) / "uv.lock"
if not path.is_file():
    raise SystemExit("REFUSED: uv.lock missing; use 'mise run lock' first")
lock = tomllib.loads(path.read_text())
names = {p.get("name") for p in lock.get("package", [])}
missing = {"ansible-core", "ruff", "pytest"} - names
if missing:
    raise SystemExit("REFUSED: uv.lock missing packages: " + ", ".join(sorted(missing)))
if len(names) < 8:
    raise SystemExit("REFUSED: uv.lock looks incomplete")
print(f"PASS: lockfile includes {len(names)} packages and the Ansible toolchain")
PY
}

check_metadata

if [ "$ACTION" = info ]; then
  echo "project=$ROOT"
  echo "python=$("$ROOT/.venv/bin/python" --version 2>/dev/null || echo 'no local venv')"
  echo "ansible=$(test -x "$ROOT/.venv/bin/ansible" && echo local || echo missing)"
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "REFUSED: uv is unavailable; run 'mise install' first" >&2
  exit 2
fi

if [ "$ACTION" = lock ]; then
  uv --project "$ROOT" lock
  check_lock
  exit 0
fi

check_lock
uv --project "$ROOT" lock --check

if [ "$ACTION" = check ]; then
  if [ ! -x "$ROOT/.venv/bin/ansible" ]; then
    echo "REFUSED: .venv/bin/ansible missing; use 'mise run sync'" >&2
    exit 2
  fi
  "$ROOT/.venv/bin/ansible" --version
  exit 0
fi

# Never follow a symlink to an environment outside the selected checkout.
if [ -L "$ROOT/.venv" ]; then
  echo "REFUSED: symlinked .venv; refuse to sync an external environment." >&2
  exit 2
fi

# Exact sync removes unlisted packages. Never alter an existing venv we did
# not create. Rename/archive it manually if it was made by pipenv/Poetry/uv.
marker="$ROOT/.venv/.ansible-workstation-uv-managed"
if { [ -e "$ROOT/.venv" ] || [ -L "$ROOT/.venv" ]; } &&
   { [ ! -f "$ROOT/.venv/pyvenv.cfg" ] || [ ! -x "$ROOT/.venv/bin/python" ]; }; then
  echo "REFUSED: incomplete .venv; run 'mise run recover-venv' to archive it." >&2
  exit 2
fi
if [ -e "$ROOT/.venv" ] && [ ! -f "$marker" ]; then
  echo "REFUSED: existing unmanaged .venv; archive it before explicit sync" >&2
  exit 2
fi
uv --project "$ROOT" sync --locked --python 3.12
test -x "$ROOT/.venv/bin/ansible"
touch "$marker"
"$ROOT/.venv/bin/ansible" --version
