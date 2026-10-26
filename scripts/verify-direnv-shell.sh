#!/usr/bin/env bash
# Source ONLY in the interactive Bash to verify current-shell Direnv isolation.
# Read only; no network, secrets, package install, Git writes or Ansible apply.
# Usage: source scripts/verify-direnv-shell.sh
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  echo "REFUSED: source scripts/verify-direnv-shell.sh in the current Bash." >&2
  exit 2
fi

_nabla_verify_direnv_shell() {
  local root declaration py ansible failure=0
  root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" || return 2
  declaration="$(declare -p PROMPT_COMMAND 2>/dev/null || true)"

  case "$-" in
    *i*) ;;
    *) echo "FAIL: shell is not interactive" >&2; failure=1 ;;
  esac

  if ! declare -F _direnv_hook >/dev/null 2>&1 ||
     [[ "$declaration" != *"_direnv_hook"* ]]; then
    echo "FAIL: Direnv is not registered in the Bash prompt" >&2
    failure=1
  fi
  if [[ "$declaration" == *"_mise_hookhistory"* ||
        "${PS1:-}" == *"_mise_hookhistory"* ]]; then
    echo "FAIL: malformed mise/history token in prompt" >&2
    failure=1
  fi

  if [[ -L "$root/.venv" || ! -f "$root/.venv/pyvenv.cfg" ||
        ! -x "$root/.venv/bin/python" || ! -x "$root/.venv/bin/ansible" ]]; then
    echo "FAIL: missing, invalid or symlinked project .venv" >&2
    failure=1
  fi

  if [[ "${VIRTUAL_ENV:-}" != "$root/.venv" ]]; then
    echo "FAIL: VIRTUAL_ENV is not the repository-local .venv" >&2
    failure=1
  fi

  py="$(type -P python 2>/dev/null || true)"
  ansible="$(type -P ansible 2>/dev/null || true)"
  if [[ "$py" != "$root/.venv/bin/python" ]]; then
    echo "FAIL: python resolves outside the project venv" >&2
    failure=1
  fi
  if [[ "$ansible" != "$root/.venv/bin/ansible" ]]; then
    echo "FAIL: ansible resolves outside the project venv" >&2
    failure=1
  fi

  if (( failure )); then
    echo "Shell verification failed. See scripts/diagnose-direnv-shell.sh." >&2
    return 1
  fi
  echo "PASS: interactive Direnv prompt and isolated Python/Ansible environment"
  return 0
}
if _nabla_verify_direnv_shell; then
  unset -f _nabla_verify_direnv_shell
  return 0
else
  unset -f _nabla_verify_direnv_shell
  return 1
fi
