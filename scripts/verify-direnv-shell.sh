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
  local item char quote segment escaped i hook_present=0
  local -a prompt_items=()
  root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" || return 2
  declaration="$(declare -p PROMPT_COMMAND 2>/dev/null || true)"

  case "$-" in
    *i*) ;;
    *) echo "FAIL: shell is not interactive" >&2; failure=1 ;;
  esac

  # Refuse substring-only matches from quoted messages and longer names.
  # Recognize only a standalone command, without executing PROMPT_COMMAND.
  if [[ "$declaration" == "declare -a"* ]]; then
    prompt_items=("${PROMPT_COMMAND[@]}")
  elif [[ "$declaration" != "declare -A"* &&
          -n "${PROMPT_COMMAND+x}" ]]; then
    prompt_items=("$PROMPT_COMMAND")
  fi
  for item in "${prompt_items[@]}"; do
    quote=''
    segment=''
    escaped=0
    for ((i=0; i<${#item}; i++)); do
      char="${item:i:1}"
      if (( escaped )); then
        segment+="$char"
        escaped=0
        continue
      fi
      if [[ "$char" == '\' && "$quote" != "'" ]]; then
        segment+="$char"
        escaped=1
        continue
      fi
      if [[ -z "$quote" ]]; then
        case "$char" in
          "'"|'"') quote="$char"; segment+="$char" ;;
          ';'|$'\n')
            if [[ "$segment" =~ ^[[:space:]]*_direnv_hook[[:space:]]*$ ]]; then
              hook_present=1
            fi
            segment=''
            ;;
          *) segment+="$char" ;;
        esac
      else
        segment+="$char"
        [[ "$char" == "$quote" ]] && quote=''
      fi
    done
    if [[ -z "$quote" &&
          "$segment" =~ ^[[:space:]]*_direnv_hook[[:space:]]*$ ]]; then
      hook_present=1
    fi
  done

  if ! declare -F _direnv_hook >/dev/null 2>&1 ||
     (( hook_present == 0 )); then
    echo "FAIL: Direnv is not registered as a standalone Bash prompt command" >&2
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
