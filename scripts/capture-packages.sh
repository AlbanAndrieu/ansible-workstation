#!/usr/bin/env bash
# Write the non-default package selection into files/packages/ and copy the APT
# keyrings that captured sources reference outside /etc. Read-only on the system.
set -euo pipefail
export LC_ALL=C

root="$(cd "$(dirname "$0")/.." && pwd)"
out="${root}/files/packages"
keyrings="${root}/files/keyrings"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
mkdir -p "${out}" "${keyrings}"

# Retired services and versioned kernels: never reinstalled.
legacy='^(graylog|tomcat|nexus|pacemaker|corosync|elasticsearch|kibana|consul|redis|kube(let|adm)|gvm|openvas|ospd|nessus|graphite|carbon|hostapd|tgt|cockpit|telegraf|datadog|zabbix-(release|agent2-plugin)|wazuh|nfs-kernel-server|mongodb|heartbeat)'
kernel='^linux-(image|headers|modules|objects|signatures|tools|cloud-tools|hwe)-[0-9]'

apt-mark showmanual | sort -u >"${tmp}/manual"
apt list --installed 2>/dev/null | awk -F/ '/\[installed,local\]/ {print $1}' | sort -u >"${tmp}/norepo"
# Fresh Ubuntu desktop already pulls these in: they are the default, not a choice.
apt-cache depends --recurse --no-suggests --no-conflicts --no-breaks --no-replaces --no-enhances \
  ubuntu-desktop ubuntu-desktop-minimal ubuntu-minimal ubuntu-standard 2>/dev/null |
  grep -vE '^[[:space:]<]' | sed 's/:any$//' | sort -u >"${tmp}/default"

comm -23 "${tmp}/manual" "${tmp}/norepo" | comm -23 - "${tmp}/default" |
  grep -vE "${legacy}|${kernel}" >"${out}/apt.txt" || true
# Installed but no configured repository provides them: re-add the vendor repo by hand.
comm -12 "${tmp}/manual" "${tmp}/norepo" | grep -vE "${legacy}|${kernel}" >"${out}/apt-no-repo.txt" || true

# Base, runtime and theme snaps are pulled in automatically.
: >"${out}/snap.txt"
: >"${out}/snap-classic.txt"
snap list 2>/dev/null | awk 'NR > 1 && $6 !~ /base|snapd/ && $1 !~ /^(core[0-9]*|bare|gnome-|gtk-common-themes|mesa-)/ {
  print $1 > ($6 ~ /classic/ ? "'"${out}"'/snap-classic.txt" : "'"${out}"'/snap.txt")
}'
flatpak list --app --columns=application 2>/dev/null | sort -u >"${out}/flatpak.txt"

# Keyrings referenced by captured sources but stored outside /etc.
grep -ohE '(Signed-By:[[:space:]]*|signed-by=)/usr/share/keyrings/[^],[:space:]]+' \
  "${root}"/files/etc/apt/sources.list.d/* | sed -E 's/^(Signed-By:[[:space:]]*|signed-by=)//' | sort -u |
  while read -r key; do
    if [ -r "${key}" ]; then
      cp "${key}" "${keyrings}/"
    else
      echo "keyring missing: ${key}" >&2
    fi
  done

wc -l "${out}"/*.txt
