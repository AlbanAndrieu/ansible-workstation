# shellcheck shell=bash
# Helpers shared by capture-etc.sh and capture-packages.sh. Sourced, never executed.
# Both scripts copy host files into this Git repository, so every write is
# symlink-safe and nothing that looks like secret material is kept.

CAPTURE_MARKER='@@SECRET@@'

# Signatures that must never survive redaction: private keys and token formats.
CAPTURE_LEAK='-----BEGIN [A-Z ]*PRIVATE KEY|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}|gh[opsur]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|glpat-[A-Za-z0-9_-]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|(^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}'

# The capture report goes to stderr; stdout is left to the caller.
note() { printf '%s\n' "$*" >&2; }

# True for text files; empty files count as text.
is_text() { [ ! -s "$1" ] || grep -Iq . -- "$1"; }

has_secret_signature() { grep -Eq -- "${CAPTURE_LEAK}" "$1"; }

world_readable() { [ $((8#$(stat -c %a -- "$1") & 4)) -ne 0 ]; }

# True for public OpenPGP key material only: an armored public block, or a
# binary keyring whose first packet is a public key (tag 6). A secret key
# (tag 5) or an armored private block fails.
is_public_pgp() {
  local first tag
  if is_text "$1"; then
    grep -qF -- '-----BEGIN PGP PUBLIC KEY BLOCK-----' "$1" &&
      ! grep -qF -- 'PRIVATE KEY' "$1"
    return
  fi
  first="$(od -An -tu1 -N1 -- "$1" | tr -d '[:space:]')"
  [ -n "${first}" ] && ((first & 128)) || return 1
  if ((first & 64)); then
    tag=$((first & 63))
  else
    tag=$(((first >> 2) & 15))
  fi
  [ "${tag}" -eq 6 ]
}

# Replace secret values with CAPTURE_MARKER, comments included: a commented
# line can still hold a real password. Keys naming a file, path or directory
# keep their value. Files keeping the marker are restored by hand only.
redact() {
  local m="${CAPTURE_MARKER}"
  local secret='[A-Za-z0-9_.-]*(password|passwd|passphrase|secret|token|api[_-]?key|apikey|private[_-]?key|access[_-]?key|psk)[A-Za-z0-9_.-]*'
  local directive='HashedControlPassword|netcam_userpass|netcam_high_userpass|webcontrol_authentication|stream_authentication|requirepass|masterauth'
  sed -E \
    -e "s#([a-z][a-z0-9+.-]*://[^/:@[:space:]]+:)[^@/[:space:]]+@#\\1${m}@#g" \
    -e "/^[[:space:]#;]*[\"']?[A-Za-z0-9_.-]*(file|path|dir)[\"']?[[:space:]]*[=:]/Ib" \
    -e "/^[[:space:]]*\\[passwords\\]/,/^[[:space:]]*\\[/{/^[[:space:]]*\\[/!s/^([[:space:]#;]*[^=[:space:]]+[[:space:]]*=[[:space:]]*).+/\\1${m}/}" \
    -e "s/^([[:space:]#;]*[\"']?${secret}[\"']?[[:space:]]*[=:][[:space:]]*).+/\\1${m}/I" \
    -e "s/^([[:space:]#;]*(${directive})[[:space:]]+).+/\\1${m}/I" \
    -e "/^[[:space:]#;]*Environment=/s/([A-Za-z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|PASSWD|PSK)[A-Za-z0-9_]*=)[^\" ]+/\\1${m}/Ig"
}

# Copy stdin to $2, which must stay inside directory $1. Symlinks planted in
# the repository are never followed: the parent must resolve inside $1 and
# the target is replaced by rename, not opened.
write_inside() {
  local base target="$2" dir tmp
  base="$(realpath -e -- "$1")" || return 1
  dir="$(dirname -- "${target}")"
  case "$(realpath -m -- "${dir}")/" in
  "${base}"/*) ;;
  *)
    note "refused (destination escapes ${base}): ${target}"
    return 1
    ;;
  esac
  if [ -d "${target}" ] && [ ! -L "${target}" ]; then
    note "refused (destination is a directory): ${target}"
    return 1
  fi
  mkdir -p -- "${dir}"
  tmp="$(mktemp -- "${dir}/.capture.XXXXXX")"
  if ! cat >"${tmp}"; then
    rm -f -- "${tmp}"
    return 1
  fi
  mv -fT -- "${tmp}" "${target}"
}
