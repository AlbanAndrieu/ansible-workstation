#!/usr/bin/env bash
# Operator repair tool for the USER toolchain (not part of the Ansible role).
# Recovers from a lost ~/.local/share/mise: global mise tools (starship,
# direnv, uv, node, python), this project's locked runtimes and the OpenClaw
# source gateway run by systemd --user.
#
# Usage: bash scripts/repair-user-toolchain.sh [check|apply]
#   check (default) read-only diagnosis: no install, no restart.
#   apply           explicit repair: mise install, pinned OpenClaw reinstall
#                   with an npm install-script allowlist, gateway restart.
# Never uses sudo, curl | sh, PAM or the Docker socket. Never prints
# ExecStart arguments nor EnvironmentFile contents.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
ACTION="${1:-check}"

OPENCLAW_UNIT="${OPENCLAW_UNIT:-openclaw-gateway.service}"
OPENCLAW_VERSION="${OPENCLAW_VERSION:-2026.10.7}"
# Only packages whose install step matters for the gateway. protobufjs
# (notice only) and @google/genai (no-op) stay blocked by npm's policy.
NPM_ALLOW_SCRIPTS="${NPM_ALLOW_SCRIPTS:-openclaw,koffi,esbuild}"
MIN_FREE_GB="${MIN_FREE_GB:-10}"
OPENCLAW_RESTART_WAIT="${OPENCLAW_RESTART_WAIT:-3}"

PROBLEMS=0
pass() { printf 'PASS: %s\n' "$*"; }
info() { printf 'INFO: %s\n' "$*"; }
warn() {
  printf 'WARN: %s\n' "$*"
  PROBLEMS=$((PROBLEMS + 1))
}
refuse() {
  printf 'REFUSED: %s\n' "$*" >&2
  exit 2
}

case "${ACTION}" in
check | apply) ;;
*)
  printf 'Usage: %s {check|apply}\n' "$0" >&2
  exit 2
  ;;
esac

# User-level tool: running it as root would install into /root.
if [ "$(id -u)" -eq 0 ]; then
  refuse "run as your user, never as root or with sudo"
fi
[[ "${OPENCLAW_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
  refuse "OPENCLAW_VERSION must be an exact X.Y.Z version"
[[ "${NPM_ALLOW_SCRIPTS}" =~ ^[@a-z0-9._/-]+(,[@a-z0-9._/-]+)*$ ]] ||
  refuse "NPM_ALLOW_SCRIPTS must be an explicit package list"
[[ "${OPENCLAW_UNIT}" =~ ^[A-Za-z0-9@._-]+\.service$ ]] ||
  refuse "OPENCLAW_UNIT must be a systemd service name"
[[ "${MIN_FREE_GB}" =~ ^[0-9]+$ ]] || refuse "MIN_FREE_GB must be an integer"

have() { command -v "$1" >/dev/null 2>&1; }

free_gb() {
  df -Pk -- "${HOME}" | awk 'NR == 2 { printf "%d", $4 / 1048576 }'
}

# Effective ExecStart: the last non-empty assignment (drop-ins come last).
openclaw_execstart() {
  systemctl --user cat "${OPENCLAW_UNIT}" 2>/dev/null |
    sed -n 's/^ExecStart=//p' | awk 'NF' | tail -n 1
}

OC_NODE=""
OC_ENTRY=""
OC_NODE_VERSION=""
parse_openclaw() {
  local line token
  local -a argv
  OC_NODE=""
  OC_ENTRY=""
  OC_NODE_VERSION=""
  line="$(openclaw_execstart || true)"
  [ -n "${line}" ] || return 1
  read -r -a argv <<<"${line}"
  OC_NODE="${argv[0]#[-@+!]}"
  for token in "${argv[@]:1}"; do
    case "${token}" in
    */node_modules/openclaw/*)
      OC_ENTRY="${token}"
      break
      ;;
    esac
  done
  case "${OC_NODE}" in
  */mise/installs/node/*/bin/node)
    OC_NODE_VERSION="${OC_NODE%/bin/node}"
    OC_NODE_VERSION="${OC_NODE_VERSION##*/}"
    ;;
  esac
  return 0
}

check_disk() {
  local gb
  gb="$(free_gb)"
  if [ "${gb}" -ge "${MIN_FREE_GB}" ]; then
    pass "free space in HOME: ${gb} GiB (>= ${MIN_FREE_GB})"
  else
    warn "free space in HOME: ${gb} GiB (< ${MIN_FREE_GB}); free space first"
  fi
}

check_mise() {
  local missing tool path
  if ! have mise; then
    warn "mise not on PATH: reinstall it from the signed APT repository" \
      "documented at https://mise.jdx.dev (never curl | sh)"
    return
  fi
  pass "mise $(mise --version 2>/dev/null | head -n 1)"
  missing="$(cd -- "${HOME}" && mise ls 2>/dev/null | grep -F '(missing)' || true)"
  if [ -n "${missing}" ]; then
    warn "global mise tools missing: $(printf '%s\n' "${missing}" | awk '{print $1}' |
      sort -u | tr '\n' ' ')"
  else
    pass "global mise tools installed"
  fi
  for tool in starship direnv; do
    path="$(cd -- "${HOME}" && mise which "${tool}" 2>/dev/null || true)"
    if [ -n "${path}" ] && [ -x "${path}" ]; then
      pass "${tool} resolved by mise"
    else
      warn "${tool} not installed by mise (prompt/hook errors in new shells)"
    fi
  done
  missing="$(cd -- "${ROOT}" && mise ls 2>/dev/null | grep -F '(missing)' || true)"
  if [ -n "${missing}" ]; then
    warn "project runtimes from mise.lock missing (run: mise install)"
  else
    pass "project runtimes from mise.lock installed"
  fi
}

check_venv() {
  local py="${ROOT}/.venv/bin/python"
  if [ -x "${py}" ] && "${py}" -c 'import sys' >/dev/null 2>&1; then
    pass "project .venv interpreter works"
  else
    warn "project .venv interpreter broken: mise run recover-venv, then mise run init"
  fi
}

check_openclaw() {
  if ! have systemctl || ! systemctl --user cat "${OPENCLAW_UNIT}" >/dev/null 2>&1; then
    info "${OPENCLAW_UNIT} not installed for this user; skipped"
    return
  fi
  if ! parse_openclaw; then
    warn "${OPENCLAW_UNIT} has no effective ExecStart"
    return
  fi
  if [ -x "${OC_NODE}" ]; then
    pass "gateway node binary present${OC_NODE_VERSION:+ (node ${OC_NODE_VERSION})}"
  else
    warn "gateway node binary missing${OC_NODE_VERSION:+ (node ${OC_NODE_VERSION})}"
  fi
  if [ -n "${OC_ENTRY}" ] && [ -f "${OC_ENTRY}" ]; then
    pass "gateway OpenClaw entrypoint present"
  else
    warn "gateway OpenClaw entrypoint missing (npm package not installed)"
  fi
  if systemctl --user is-active --quiet "${OPENCLAW_UNIT}"; then
    pass "${OPENCLAW_UNIT} active"
  else
    warn "${OPENCLAW_UNIT} not active (journalctl --user -u ${OPENCLAW_UNIT} -n 50)"
  fi
}

check_failed_units() {
  local unit units
  have systemctl || return 0
  units="$(systemctl --user --failed --no-legend --plain 2>/dev/null |
    awk '{print $1}' || true)"
  if [ -z "${units}" ]; then
    pass "no failed systemd --user unit"
    return
  fi
  for unit in ${units}; do
    warn "failed user unit: ${unit} (journalctl --user -u ${unit} -n 50)"
    case "${unit}" in
    bitcoin-qt.service)
      info "bitcoin-qt: legacy unit from tasks/services.yml; if unused:" \
        "systemctl --user disable --now bitcoin-qt.service &&" \
        "systemctl --user reset-failed bitcoin-qt.service"
      ;;
    esac
  done
}

run_checks() {
  PROBLEMS=0
  echo "=== user toolchain diagnosis (read-only) ==="
  check_disk
  check_mise
  check_venv
  check_openclaw
  check_failed_units
  echo "=== problems: ${PROBLEMS} ==="
}

repair_mise() {
  have mise || refuse "mise is missing; reinstall it from the signed APT repository"
  echo "--- mise install (global config)"
  (cd -- "${HOME}" && mise install)
  mise reshim
  echo "--- mise install (project mise.lock)"
  (cd -- "${ROOT}" && mise install)
  if ! (cd -- "${ROOT}" && mise exec -- bash scripts/uv-project.sh check >/dev/null); then
    info "project venv still invalid: mise run recover-venv, then mise run init"
  fi
}

repair_openclaw() {
  local node_dir
  if ! have systemctl || ! systemctl --user cat "${OPENCLAW_UNIT}" >/dev/null 2>&1; then
    info "${OPENCLAW_UNIT} not installed for this user; nothing to repair"
    return
  fi
  parse_openclaw || refuse "${OPENCLAW_UNIT} has no effective ExecStart"
  if [ -z "${OC_NODE_VERSION}" ]; then
    info "gateway node is not mise-managed; not modified"
    return
  fi
  echo "--- node ${OC_NODE_VERSION} for the gateway"
  (cd -- "${HOME}" && mise install "node@${OC_NODE_VERSION}")
  node_dir="$(dirname -- "${OC_NODE}")"
  [ -x "${node_dir}/npm" ] || refuse "npm missing next to the gateway node"
  echo "--- openclaw@${OPENCLAW_VERSION} (install scripts: ${NPM_ALLOW_SCRIPTS})"
  PATH="${node_dir}:${PATH}" "${node_dir}/npm" install -g --prefix "${node_dir%/bin}" \
    --allow-scripts="${NPM_ALLOW_SCRIPTS}" "openclaw@${OPENCLAW_VERSION}"
  [ -n "${OC_ENTRY}" ] && [ -f "${OC_ENTRY}" ] ||
    refuse "OpenClaw entrypoint still missing; compare the unit drop-in with" \
      "the installed package layout before restarting"
  systemctl --user daemon-reload
  systemctl --user restart "${OPENCLAW_UNIT}"
  sleep "${OPENCLAW_RESTART_WAIT}"
}

if [ "${ACTION}" = apply ]; then
  gb="$(free_gb)"
  [ "${gb}" -ge "${MIN_FREE_GB}" ] ||
    refuse "only ${gb} GiB free in HOME (< ${MIN_FREE_GB}); free space first"
  repair_mise
  repair_openclaw
fi

run_checks
[ "${PROBLEMS}" -eq 0 ]
