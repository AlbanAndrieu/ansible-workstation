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

CAPTURE_INTERNAL_MARKER='@@INTERNAL@@'

# Replace private infrastructure addresses and names with CAPTURE_INTERNAL_MARKER:
# RFC 1918, CGNAT (Tailscale) and IPv6 ULA addresses with their prefix, names
# under int.albandrieu.com, .lan, .internal or .home.arpa, and Hostname/HostName
# values. Kept on purpose: the generic RFC 1918 blocks of filter rules, which
# reveal nothing, loopback, public resolvers, and public vhosts, already listed
# in Certificate Transparency logs.
scrub_internal() {
  local m="${CAPTURE_INTERNAL_MARKER}" o='[0-9]{1,3}'
  local private="10\\.${o}\\.${o}\\.${o}|172\\.(1[6-9]|2[0-9]|3[01])\\.${o}\\.${o}|192\\.168\\.${o}\\.${o}|100\\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\\.${o}\\.${o}"
  local edge='[^A-Za-z0-9.-]'
  sed -E \
    -e 's#(^|[^0-9.])10\.0\.0\.0/8([^0-9]|$)#\1@@KEEP_RFC1918_A@@\2#g' \
    -e 's#(^|[^0-9.])172\.16\.0\.0/12([^0-9]|$)#\1@@KEEP_RFC1918_B@@\2#g' \
    -e 's#(^|[^0-9.])192\.168\.0\.0/16([^0-9]|$)#\1@@KEEP_RFC1918_C@@\2#g' \
    -e "s#(^|[^0-9A-Za-z.])(${private})(/[0-9]{1,2})?#\\1${m}#g" \
    -e "s#(^|[^0-9A-Za-z:.])[fF][cdCD][0-9a-fA-F]{2}(:[0-9a-fA-F]{0,4}){2,7}(/[0-9]{1,3})?#\\1${m}#g" \
    -e "s#(^|${edge})([A-Za-z0-9-]+\\.)*int\\.albandrieu\\.com([^A-Za-z0-9_-]|\$)#\\1${m}\\3#Ig" \
    -e "s#(^|${edge})([A-Za-z0-9-]+\\.)+(lan|internal|home\\.arpa)([^A-Za-z0-9_-]|\$)#\\1${m}\\4#Ig" \
    -e "s/^([[:space:]#;]*Hostname[[:space:]]*=[[:space:]]*).+/\\1${m}/I" \
    -e "s/^([[:space:]]*HostName[[:space:]]+).+/\\1${m}/I" \
    -e 's#@@KEEP_RFC1918_A@@#10.0.0.0/8#g; s#@@KEEP_RFC1918_B@@#172.16.0.0/12#g' \
    -e 's#@@KEEP_RFC1918_C@@#192.168.0.0/16#g'
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
