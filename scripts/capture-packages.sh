#!/usr/bin/env bash
# Write the non-default package selection into files/packages/ and copy the APT
# keyrings that captured sources reference outside /etc. Read-only on the system.
# Only public OpenPGP keyrings are copied; anything else is refused (exit 1).
set -euo pipefail
export LC_ALL=C

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Overridable only so the contract tests can run against fixture directories.
out="${CAPTURE_PACKAGES_OUT:-${root}/files/packages}"
keyrings="${CAPTURE_KEYRINGS_DEST:-${root}/files/keyrings}"
sources="${CAPTURE_SOURCES_DIR:-${root}/files/etc/apt/sources.list.d}"
keyring_root="${CAPTURE_KEYRING_ROOT:-/usr/share/keyrings}"

# shellcheck source=scripts/capture-common.sh
. "${root}/scripts/capture-common.sh"

status=0
tmp="$(mktemp -d)"
trap 'rm -rf -- "${tmp}"' EXIT
mkdir -p -- "${out}" "${keyrings}"

# Retired services and versioned kernels: never reinstalled.
legacy='^(graylog|tomcat|nexus|pacemaker|corosync|elasticsearch|kibana|consul|redis|kube(let|adm)|gvm|openvas|ospd|nessus|graphite|carbon|hostapd|tgt|cockpit|telegraf|datadog|zabbix-(release|agent2-plugin)|wazuh|nfs-kernel-server|mongodb|heartbeat)'
kernel='^linux-(image|headers|modules|objects|signatures|tools|cloud-tools|hwe)-[0-9]'

keep() { grep -vE "${legacy}|${kernel}" || true; }

apt-mark showmanual | sort -u >"${tmp}/manual"
apt list --installed 2>/dev/null | awk -F/ '/\[installed,local\]/ {print $1}' | sort -u >"${tmp}/norepo"
# Fresh Ubuntu desktop already pulls these in: they are the default, not a choice.
apt-cache depends --recurse --no-suggests --no-conflicts --no-breaks --no-replaces --no-enhances \
  ubuntu-desktop ubuntu-desktop-minimal ubuntu-minimal ubuntu-standard 2>/dev/null |
  grep -vE '^[[:space:]<]' | sed 's/:any$//' | sort -u >"${tmp}/default"

comm -23 "${tmp}/manual" "${tmp}/norepo" | comm -23 - "${tmp}/default" | keep >"${out}/apt.txt"
# Installed but no configured repository provides them: re-add the vendor repo by hand.
comm -12 "${tmp}/manual" "${tmp}/norepo" | keep >"${out}/apt-no-repo.txt"

# Base, runtime and theme snaps are pulled in automatically.
snap list 2>/dev/null | awk -v strict="${out}/snap.txt" -v classic="${out}/snap-classic.txt" '
  BEGIN { printf "" > strict; printf "" > classic }
  NR > 1 && $6 !~ /base|snapd/ && $1 !~ /^(core[0-9]*|bare|gnome-|gtk-common-themes|mesa-)/ {
    print $1 > ($6 ~ /classic/ ? classic : strict)
  }' || true
flatpak list --app --columns=application 2>/dev/null | sort -u >"${out}/flatpak.txt" || true

# Keyrings referenced by captured sources but stored outside /etc.
{ grep -ohE '(Signed-By:[[:space:]]*|signed-by=)/usr/share/keyrings/[^],[:space:]]+' \
  "${sources}"/* 2>/dev/null || true; } |
  sed -E 's#^(Signed-By:[[:space:]]*|signed-by=)/usr/share/keyrings/##' | sort -u >"${tmp}/keyrings"

while IFS= read -r name; do
  key="${keyring_root}/${name}"
  case "${name}" in
  */* | .*)
    note "refused (unexpected keyring name): ${name}"
    status=1
    ;;
  *)
    if [ ! -r "${key}" ]; then
      note "keyring missing: ${key}"
    elif ! is_public_pgp "${key}"; then
      note "refused (not a public OpenPGP key): ${key}"
      status=1
    elif ! write_inside "${keyrings}" "${keyrings}/${name}" <"${key}"; then
      status=1
    else
      chmod 0644 -- "${keyrings}/${name}"
    fi
    ;;
  esac
done <"${tmp}/keyrings"

wc -l "${out}"/*.txt
exit "${status}"
