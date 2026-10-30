#!/usr/bin/env bash
# NetworkManager dispatcher, root-owned and explicitly installed via Ansible.
# Apply only to the vetted LAN profile and interface; never change global DNSSEC.
set -euo pipefail

iface="${1:-}"
action="${2:-}"
[[ "$iface" == "eno1" ]] || exit 0

resolved="/usr/bin/resolvectl"
[[ -x "$resolved" ]] || exit 0
nta="$("$resolved" nta eno1 2>/dev/null)" || exit 0
[[ "$nta" == *":"* ]] || exit 0
existing="${nta#*:}"
existing="${existing#"${existing%%[![:space:]]*}"}"
existing="${existing%"${existing##*[![:space:]]}"}"

case "$action" in
  up|dhcp4-change|reapply)
    # Fail closed unless current profile, DNS and route are approved.
    # Clear our stale per-link NTA if the profile or DNS route changes.
    # Never erase any unrelated or additional NTA.
    if [[ "${CONNECTION_ID:-}" != "Wired eno1" ]]; then
      [[ "$existing" != "int.albandrieu.com" ]] || "$resolved" nta eno1 ""
      exit 0
    fi
    # Avoid calling nmcli from inside a NetworkManager dispatcher.
    dns="$("$resolved" dns eno1 2>/dev/null)" || exit 0
    domains="$("$resolved" domain eno1 2>/dev/null)" || exit 0
    if [[ "$dns" != *": 172.17.0.1" ]] || [[ " ${domains#*:} " != *" ~int.albandrieu.com "* ]]; then
      [[ "$existing" != "int.albandrieu.com" ]] || "$resolved" nta eno1 ""
      exit 0
    fi
    [[ -z "$existing" || "$existing" == "int.albandrieu.com" ]] || exit 0
    [[ "$existing" == "int.albandrieu.com" ]] || "$resolved" nta eno1 int.albandrieu.com
    ;;
  down)
    # Clear only our single runtime anchor; never remove unrelated anchors.
    if [[ "$existing" == "int.albandrieu.com" ]]; then
      "$resolved" nta eno1 ""
    fi
    ;;
esac
