#!/usr/bin/env bash
# Copy the /etc files listed in files/etc-manifest.txt into files/etc/, redacting secrets.
# Read-only on the system: no sudo, unreadable or absent paths are reported and skipped.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
manifest="${root}/files/etc-manifest.txt"
dest="${root}/files/etc"
marker='@@SECRET@@'

redact() {
  sed -E \
    -e "s/^([[:space:]]*(password|passwd|secret|token|api_key)[[:space:]]*[=:][[:space:]]*).+/\1${marker}/I" \
    -e "s/^([[:space:]#]*HashedControlPassword[[:space:]]+).+/\1${marker}/" \
    -e "s/(Environment=\"?[A-Z_]*(KEY|TOKEN|SECRET|PASSWORD)=)[^\" ]+/\1${marker}/"
}

grep -Ev '^[[:space:]]*(#|$)' "${manifest}" | while read -r path; do
  case "${path}" in
  /etc/*) ;;
  *)
    echo "refused (outside /etc): ${path}" >&2
    continue
    ;;
  esac
  if [ ! -e "${path}" ]; then
    echo "absent, kept repo copy: ${path}" >&2
  elif [ ! -r "${path}" ]; then
    echo "unreadable without sudo, skipped: ${path}" >&2
  else
    target="${dest}/${path#/etc/}"
    mkdir -p "$(dirname "${target}")"
    redact <"${path}" >"${target}"
    mode=0644
    [ -x "${path}" ] && [ "$(head -c2 "${path}")" = "#!" ] && mode=0755
    chmod "${mode}" "${target}"
    if grep -q "${marker}" "${target}"; then
      echo "redacted secret(s): ${path}" >&2
    fi
  fi
done
echo "Review with: git -C '${root}' status files/etc && git -C '${root}' diff files/etc"
