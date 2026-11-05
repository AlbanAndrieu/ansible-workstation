#!/usr/bin/env bash
# Workstation cleanup around BleachBit (operator tool, not part of the role).
# Replaces the rm -Rf chains of nabla/env/linux/cleanup-*.sh with BleachBit
# built-in cleaners plus files/bleachbit/workstation_dev.xml (CleanerML).
#
# Usage: bash scripts/workstation-cleanup.sh [check|apply|apply-system]
#   check (default) read-only: disk usage, cleaner availability, preview.
#   apply           user caches only: install the custom cleaner, then
#                   bleachbit --clean. No sudo.
#   apply-system    explicit sudo: apt caches, disabled snap revisions,
#                   journald size, unused flatpaks, optional motion retention.
# Never deletes profiles, installed tools (mise), credentials, databases,
# Docker containers or volumes, audit logs, or Trash unless opted in.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
ACTION="${1:-check}"

CLEANER_SRC="$ROOT/files/bleachbit/workstation_dev.xml"
CLEANER_DST="${XDG_CONFIG_HOME:-$HOME/.config}/bleachbit/cleaners/workstation_dev.xml"
# Space-separated opt-ins, e.g. "system.trash workstation_dev.maven_repository".
EXTRA_CLEANERS="${EXTRA_CLEANERS:-}"
JOURNAL_MAX="${JOURNAL_MAX:-500M}"
APT_AUTOREMOVE="${APT_AUTOREMOVE:-0}"
MOTION_DIR="${MOTION_DIR:-/workspace/Dropbox/motion}"
MOTION_RETENTION_DAYS="${MOTION_RETENTION_DAYS:-}"

# Regenerable caches only. Each id is skipped when this BleachBit lacks it.
USER_CLEANERS=(
  vscode.cache
  google_chrome.cache
  google_chrome.ai
  firefox.cache
  thunderbird.cache
  thumbnails.cache
  claude.cache
  claude.logs
  claude.tmp
  claude.shell_snapshots
  workstation_dev.python_caches
  workstation_dev.node_caches
  workstation_dev.editor_extras
  workstation_dev.chrome_component_caches
  workstation_dev.ansible_tmp
)
# Options backed by an external command: selected only when it is on PATH.
TOOL_CLEANERS=(
  "uv:workstation_dev.uv_cache"
  "pre-commit:workstation_dev.pre_commit_gc"
  "docker:workstation_dev.docker_build"
)
SYSTEM_CLEANERS=(apt.clean apt.autoclean snap.disabled)
# Never accepted, even as opt-in: data loss, credential loss or audit loss.
DENIED_REGEX='(\.passwords$|^system\.(free_disk_space|memory|custom)$|^journald\.clean$)'

info() { printf 'INFO: %s\n' "$*"; }
pass() { printf 'PASS: %s\n' "$*"; }
refuse() {
  printf 'REFUSED: %s\n' "$*" >&2
  exit 2
}
have() { command -v "$1" >/dev/null 2>&1; }

case "$ACTION" in
  check | apply | apply-system) ;;
  *)
    printf 'Usage: %s {check|apply|apply-system}\n' "$0" >&2
    exit 2
    ;;
esac

if [ "$(id -u)" -eq 0 ]; then
  refuse "run as your user; apply-system calls sudo for each system step"
fi
for id in $EXTRA_CLEANERS; do
  [[ "$id" =~ ^[a-z0-9_]+\.[a-z0-9_]+$ ]] \
    || refuse "EXTRA_CLEANERS entries must be cleaner.option ids"
  if [[ "$id" =~ $DENIED_REGEX ]]; then
    refuse "$id is never allowed by this tool"
  fi
done
[[ "$JOURNAL_MAX" =~ ^[0-9]+[KMG]$ ]] || refuse "JOURNAL_MAX must look like 500M"
[[ "$APT_AUTOREMOVE" =~ ^[01]$ ]] || refuse "APT_AUTOREMOVE must be 0 or 1"
if [ -n "$MOTION_RETENTION_DAYS" ]; then
  [[ "$MOTION_RETENTION_DAYS" =~ ^[1-9][0-9]*$ ]] \
    || refuse "MOTION_RETENTION_DAYS must be a positive integer"
fi

AVAILABLE=""
load_available() {
  AVAILABLE="$(bleachbit --list-cleaners 2>/dev/null || true)"
}

# Print the wanted ids that this BleachBit provides, one per line.
select_available() {
  local id
  for id in "$@"; do
    if printf '%s\n' "$AVAILABLE" | grep -qxF -- "$id"; then
      printf '%s\n' "$id"
    else
      info "skipped (not provided by this BleachBit or cleaner not installed): $id" >&2
    fi
  done
}

wanted_user_cleaners() {
  local entry id
  printf '%s\n' "${USER_CLEANERS[@]}"
  for entry in "${TOOL_CLEANERS[@]}"; do
    if have "${entry%%:*}"; then
      printf '%s\n' "${entry#*:}"
    fi
  done
  for id in $EXTRA_CLEANERS; do
    printf '%s\n' "$id"
  done
}

summary_tail() { tail -n 4; }

report_usage() {
  local path
  echo "--- disk"
  df -h / "$HOME" 2>/dev/null | awk 'NR == 1 || !seen[$0]++'
  echo "--- largest cache locations (read-only)"
  for path in "$HOME/.cache" "$HOME/.npm" "$HOME/.m2" "$HOME/.config/Code" \
    "$HOME/.config/Cursor" "$HOME/.config/google-chrome" \
    "$HOME/.local/share/Trash"; do
    [ -e "$path" ] && du -sh -- "$path" 2>/dev/null || true
  done
  if have docker; then
    echo "--- docker (images/build cache only are cleaned; never volumes)"
    docker system df 2>/dev/null || true
  fi
}

check_cleaner_install() {
  local target
  if [ ! -f "$CLEANER_DST" ]; then
    info "custom cleaner not installed yet (apply installs it): $CLEANER_DST"
    echo "--- custom cleaner targets (read-only sizes)"
    grep -oE 'path="[^"]+"' "$CLEANER_SRC" | sed -E 's/^path="(.*)"$/\1/' \
      | while read -r target; do
        target="${target/#\~/$HOME}"
        [ -e "$target" ] && du -sh -- "$target" 2>/dev/null || true
      done
  elif cmp -s "$CLEANER_SRC" "$CLEANER_DST"; then
    pass "custom cleaner up to date"
  else
    info "custom cleaner differs from the repository copy (apply updates it)"
  fi
}

run_user() {
  local -a selection
  if ! have bleachbit; then
    [ "$ACTION" = check ] || refuse "bleachbit is not installed (tasks/workstation.yml installs it)"
    info "bleachbit not installed: preview skipped"
    return
  fi
  load_available
  mapfile -t selection < <(wanted_user_cleaners | sort -u)
  mapfile -t selection < <(select_available "${selection[@]}")
  if [ "${#selection[@]}" -eq 0 ]; then
    info "no cleaner selected"
    return
  fi
  if [ "$ACTION" = check ]; then
    echo "--- bleachbit --preview (${#selection[@]} options)"
    bleachbit --preview "${selection[@]}" 2>&1 | summary_tail
  else
    echo "--- bleachbit --clean (${#selection[@]} options)"
    bleachbit --clean "${selection[@]}" 2>&1 | summary_tail
  fi
}

check_system() {
  echo "--- system (apply-system, sudo)"
  if have journalctl; then
    journalctl --disk-usage 2>/dev/null || true
  fi
  if have snap; then
    info "disabled snap revisions: $(LC_ALL=C snap list --all 2>/dev/null \
      | awk '$NF ~ /disabled/' | wc -l)"
  fi
  if have apt-get; then
    info "apt autoremove candidates: $(apt-get -s autoremove 2>/dev/null \
      | grep -c '^Remv' || true) (removed only with APT_AUTOREMOVE=1)"
  fi
  if [ -n "$MOTION_RETENTION_DAYS" ] && [ -d "$MOTION_DIR" ]; then
    info "motion captures older than ${MOTION_RETENTION_DAYS}d: $(find "$MOTION_DIR" \
      -xdev -type f \( -name '*.jpg' -o -name '*.mkv' \) \
      -mtime +"$MOTION_RETENTION_DAYS" 2>/dev/null | wc -l)"
  fi
}

run_system() {
  local -a selection
  have sudo || refuse "sudo is required for apply-system"
  if have bleachbit; then
    load_available
    mapfile -t selection < <(select_available "${SYSTEM_CLEANERS[@]}")
    if [ "${#selection[@]}" -gt 0 ]; then
      echo "--- sudo bleachbit --clean ${selection[*]}"
      sudo bleachbit --clean "${selection[@]}" 2>&1 | summary_tail
    fi
  fi
  if have snap; then
    if ! printf '%s\n' "$AVAILABLE" | grep -qxF snap.disabled; then
      LC_ALL=C snap list --all | awk '$NF ~ /disabled/ {print $1, $3}' \
        | while read -r name revision; do
          sudo snap remove "$name" --revision="$revision"
        done
    fi
    sudo snap set system refresh.retain=2
  fi
  if have journalctl; then
    sudo journalctl --vacuum-size="$JOURNAL_MAX"
  fi
  if have flatpak; then
    flatpak uninstall --user --unused -y || true
    sudo flatpak uninstall --system --unused -y || true
  fi
  if [ "$APT_AUTOREMOVE" = 1 ]; then
    sudo apt-get autoremove --purge -y
  fi
  if [ -n "$MOTION_RETENTION_DAYS" ] && [ -d "$MOTION_DIR" ]; then
    sudo find "$MOTION_DIR" -xdev -type f \( -name '*.jpg' -o -name '*.mkv' \) \
      -mtime +"$MOTION_RETENTION_DAYS" -delete
  fi
}

case "$ACTION" in
  check)
    echo "=== workstation cleanup: check (read-only) ==="
    report_usage
    check_cleaner_install
    run_user
    check_system
    ;;
  apply)
    echo "=== workstation cleanup: apply (user caches, no sudo) ==="
    install -D -m 0644 -- "$CLEANER_SRC" "$CLEANER_DST"
    run_user
    df -h "$HOME" | tail -n 1
    ;;
  apply-system)
    echo "=== workstation cleanup: apply-system (sudo) ==="
    run_system
    df -h / | tail -n 1
    ;;
esac
