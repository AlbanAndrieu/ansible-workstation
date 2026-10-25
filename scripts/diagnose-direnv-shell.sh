#!/usr/bin/env bash
# Source in the ACTUAL interactive Bash to inspect its in-memory prompt hooks.
# Reading this script executes no network requests, uv sync, or Git mutations.
# Usage: source scripts/diagnose-direnv-shell.sh
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  echo "REFUSED: run 'source scripts/diagnose-direnv-shell.sh' in your interactive Bash." >&2
  exit 2
fi

echo "=== Direnv: current Bash hook diagnosis (read only) ==="
case $- in
  *i*) echo "Shell: interactive Bash" ;;
  *) echo "Shell: non-interactive; prompt hooks do not execute here" ;;
esac
printf 'Current directory: %s\n' "$PWD"

if declare -F _direnv_hook >/dev/null 2>&1; then
  echo "Direnv Bash function: installed"
else
  echo "Direnv Bash function: MISSING"
fi

# Check declaration only. Never execute arbitrary PROMPT_COMMAND entries.
_prompt_declaration="$(declare -p PROMPT_COMMAND 2>/dev/null || true)"
if [[ -z "$_prompt_declaration" ]]; then
  echo "PROMPT_COMMAND: missing"
elif [[ "$_prompt_declaration" == *"_direnv_hook"* ]]; then
  echo "PROMPT_COMMAND: contains _direnv_hook"
else
  echo "PROMPT_COMMAND: Direnv hook MISSING (other prompt init may have overwritten it)"
fi
unset _prompt_declaration

if [[ -n "${DIRENV_DIR:-}" ]]; then
  echo "DIRENV_DIR: present"
else
  echo "DIRENV_DIR: absent (not proof by itself)"
fi

printf 'Expected project venv: %s\n' "$PWD/.venv"
printf 'VIRTUAL_ENV: '
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  if [[ "$VIRTUAL_ENV" == "$PWD/.venv" ]]; then
    echo "project venv"
  else
    echo "other environment (check your current shell)"
  fi
else
  echo "not set"
fi

for binary in python ansible; do
  target="$(type -P "$binary" 2>/dev/null || true)"
  printf '%s resolves to: %s\n' "$binary" "${target:-MISSING}"
done
unset target binary

if ! command -v direnv >/dev/null 2>&1; then
  echo "Direnv binary: MISSING"
else
  echo "Direnv binary: available"
fi

echo "Check this shell's _direnv_hook and PROMPT_COMMAND before modifying it."
echo "For temporary recovery in this shell: eval \"\$(direnv hook bash)\""
echo "Then run _direnv_hook and recheck VIRTUAL_ENV (trusted .envrc only)."
echo "=== End of Direnv hook diagnosis ==="
