#!/usr/bin/env bash
# NetworkManager dispatcher, root-owned and explicitly installed via Ansible.
# Apply only to the vetted LAN profile and interface; never change global DNSSEC.
set -euo pipefail

iface="${1:-}"
action="${2:-}"
[[ "$iface" == "eno1" ]] || exit 0
[[ "${CONNECTION_ID:-}" == "Wired eno1" ]] || exit 0

resolved="/usr/bin/resolvectl"
[[ -x "$resolved" ]] || exit 0
nta="$("$resolved" nta eno1 2>/dev/null)" || exit 0
[[ "$nta" == *":"* ]] || exit 0
existing="${nta#*:}"
existing="${existing#"${existing%%[![:space:]]*}"}"
existing="${existing%"${existing##*[![:space:]]}"}"

case "$action" in
  up|dhcp4-change|reapply)
    # Fail closed unless the link still routes the private namespace to pfSense.
    # Do not invoke nmcli from within a NetworkManager dispatcher.
    dns="$("$resolved" dns eno1 2>/dev/null)" || exit 0
    domains="$("$resolved" domain eno1 2>/dev/null)" || exit 0
    [[ "$dns" == *": 172.17.0.1" ]] || exit 0
    [[ " ${domains#*:} " == *" ~int.albandrieu.com "* ]] || exit 0
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
