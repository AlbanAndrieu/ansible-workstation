#!/usr/bin/env bash
# Copy the /etc files listed in files/etc-manifest.txt into files/etc/, redacting secrets
# and private infrastructure addresses or names (capture-common.sh).
# Read-only on the system: no sudo, unreadable or absent paths are reported and skipped.
# Whatever the manifest says, refuses secret stores, paths or symlinks leaving /etc,
# directories, binaries other than public OpenPGP keys, and files still carrying a
# secret signature after redaction. Exits 1 when anything was refused.
set -euo pipefail
export LC_ALL=C

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Overridable only so the contract tests can run against a fixture tree.
src="${CAPTURE_ETC_SOURCE:-/etc}"
manifest="${CAPTURE_ETC_MANIFEST:-${root}/files/etc-manifest.txt}"
dest="${CAPTURE_ETC_DEST:-${root}/files/etc}"

# shellcheck source=scripts/capture-common.sh
. "${root}/scripts/capture-common.sh"

# Relative to /etc. Superset of FORBIDDEN in tests/test_etc_capture_contract.py.
forbidden='(^|/)g?shadow-?$|ssh_host_|system-connections|letsencrypt|auth\.conf\.d|credentials|GeoIP\.conf|docker/key\.json|wireguard|sudoers|ssl/private|(^|/)credstore|\.(key|pem|p12|pfx)$'

status=0
refuse() {
  note "refused ($1): $2"
  status=1
}

src_real="$(realpath -e -- "${src}")"
mkdir -p -- "${dest}"
work="$(mktemp -d)"
trap 'rm -rf -- "${work}"' EXIT

capture_one() {
  local rel="$1" shown="$2" real mode staged="${work}/staged"
  if ! real="$(realpath -e -- "${src_real}/${rel}" 2>/dev/null)"; then
    note "absent, kept repo copy: ${shown}"
    return
  fi
  case "${real}" in
  "${src_real}"/*) ;;
  *)
    refuse "symlink leaves /etc" "${shown}"
    return
    ;;
  esac
  if [[ "${real#"${src_real}"/}" =~ ${forbidden} ]]; then
    refuse "symlink to a secret store" "${shown}"
    return
  fi
  if [ ! -f "${real}" ]; then
    refuse "not a regular file" "${shown}"
    return
  fi
  if [ ! -r "${real}" ]; then
    note "unreadable without sudo, skipped: ${shown}"
    return
  fi

  # Stage outside the repository so a refused file never replaces the repo copy.
  if is_text "${real}"; then
    if ! redact <"${real}" | scrub_internal >"${staged}"; then
      refuse "read error" "${shown}"
      return
    fi
    if has_secret_signature "${staged}"; then
      refuse "secret signature left after redaction" "${shown}"
      return
    fi
  elif is_public_pgp "${real}"; then
    if ! cat -- "${real}" >"${staged}"; then
      refuse "read error" "${shown}"
      return
    fi
  else
    refuse "binary other than a public OpenPGP key" "${shown}"
    return
  fi

  if ! write_inside "${dest}" "${dest}/${rel}" <"${staged}"; then
    status=1
    return
  fi
  mode=0644
  if [ -x "${real}" ] && [ "$(head -c2 -- "${real}")" = "#!" ]; then
    mode=0755
  fi
  chmod "${mode}" -- "${dest}/${rel}"
  if grep -qF -- "${CAPTURE_MARKER}" "${dest}/${rel}"; then
    note "redacted secret(s): ${shown}"
  fi
  if grep -qF -- "${CAPTURE_INTERNAL_MARKER}" "${dest}/${rel}"; then
    note "internal address(es) or hostname(s) removed: ${shown}"
  fi
  if ! world_readable "${real}"; then
    note "not world-readable on the host, review before commit: ${shown}"
  fi
}

declare -A listed=()
while IFS= read -r path || [ -n "${path}" ]; do
  path="${path%$'\r'}"
  path="${path#"${path%%[![:space:]]*}"}"
  path="${path%"${path##*[![:space:]]}"}"
  case "${path}" in
  "" | "#"*) continue ;;
  /etc/?*) ;;
  *)
    refuse "outside /etc" "${path}"
    continue
    ;;
  esac
  rel="${path#/etc/}"
  case "/${rel}/" in
  */../* | */./* | *//*)
    refuse "non-canonical path" "${path}"
    continue
    ;;
  esac
  if [ -n "${listed[${rel}]:-}" ]; then
    note "duplicate manifest entry, ignored: ${path}"
    continue
  fi
  listed[${rel}]=1
  if [[ "${rel}" =~ ${forbidden} ]]; then
    refuse "secret store" "${path}"
    continue
  fi
  capture_one "${rel}" "${path}"
done <"${manifest}"

# Report, never delete: removing a repo copy is a reviewed Git change.
while IFS= read -r -d '' file; do
  rel="${file#"${dest}"/}"
  if [ -z "${listed[${rel}]:-}" ]; then
    note "not in manifest, review or delete: /etc/${rel}"
  fi
done < <(find "${dest}" -type f -print0)

echo "Review with: git -C '${root}' status files/etc && git -C '${root}' diff files/etc"
exit "${status}"
