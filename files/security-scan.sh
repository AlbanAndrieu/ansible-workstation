#!/usr/bin/env bash
# Run one security scanner as root and keep its report locally (playbooks/security-scans.yml).
# Usage: security-scan.sh lynis|rkhunter|clamav|openscap
# Reports: /var/lib/security-reports/<date>/ (root:albandrieu 0750); the NFS docroot is root_squash,
# so security-reports-publish.service copies them as the user. Metrics: node_exporter textfile.
set -euo pipefail
umask 027

tool="${1:?usage: security-scan.sh lynis|rkhunter|clamav|openscap}"
scan_state=COMPLETE
# Overridable only so the contract tests can run without root.
base="${SECURITY_REPORTS_DIR:-/var/lib/security-reports}"
metrics="${SECURITY_METRICS_DIR:-/var/lib/prometheus/node-exporter}"
group="${SECURITY_REPORTS_GROUP:-albandrieu}"
day="${base}/$(date +%F)"
mkdir -p "${day}"
chgrp "${group}" "${base}" "${day}"
chmod 0750 "${base}" "${day}"

# A non-zero scanner exit is evidence of INCOMPLETE, not a clean run.
# OnFailure in systemd publishes this receipt even when a scanner aborts.
started=false
finish_scan() {
  local rc=$?
  trap - EXIT
  set +e
  if [[ "${started}" = true ]]; then
    systemctl stop clamav-daemon >/dev/null 2>&1
  fi
  if ((rc != 0)); then
    case "${tool}" in
    lynis | rkhunter | clamav | openscap)
      printf '{"tool":"%s","state":"INCOMPLETE"}\n' "${tool}" \
        >"${day}/.scan-${tool}.json.tmp" &&
        chmod 0640 "${day}/.scan-${tool}.json.tmp" &&
        mv -f "${day}/.scan-${tool}.json.tmp" "${day}/.scan-${tool}.json" &&
        chgrp "${group}" "${day}/.scan-${tool}.json"
      ;;
    esac
  fi
  exit "${rc}"
}
trap finish_scan EXIT

# Atomic write so node_exporter never reads half a file.
metric() {
  local tmp="${metrics}/.security_${tool}.prom.$$"
  printf '%s\n' "$@" >"${tmp}"
  chmod 0644 "${tmp}"
  mv "${tmp}" "${metrics}/security_${tool}.prom"
}

case "${tool}" in
lynis)
  # /etc/lynis/custom.prf skips CRYP-7902, which hung on the NFS mounts.
  lynis audit system --quick --no-colors --report-file "${day}/lynis-report.dat" \
    --log-file "${day}/lynis.log" >"${day}/lynis.txt" 2>&1
  index="$(sed -n 's/^hardening_index=//p' "${day}/lynis-report.dat")"
  warnings="$(grep -c '^warning\[\]=' "${day}/lynis-report.dat" || true)"
  metric "security_lynis_hardening_index ${index:-0}" "security_lynis_warnings ${warnings}" \
    "security_scan_last_success_timestamp_seconds{tool=\"lynis\"} $(date +%s)"
  ;;
rkhunter)
  # Exit 1 only means warnings: the count goes to the metric, not to a failed unit.
  rkhunter --update --nocolors >/dev/null 2>&1 || true
  rkhunter_rc=0
  rkhunter --check --sk --nocolors --rwo --logfile "${day}/rkhunter.log" \
    >"${day}/rkhunter-warnings.txt" 2>&1 || rkhunter_rc=$?
  if [ "${rkhunter_rc}" -gt 1 ]; then scan_state=INCOMPLETE; fi
  rootkits="$(sed -n 's/.*Possible rootkits: //p' "${day}/rkhunter.log" | tail -1)"
  warnings="$(grep -c '^Warning:' "${day}/rkhunter-warnings.txt" || true)"
  if [ "${scan_state}" = COMPLETE ]; then
    metric "security_rkhunter_possible_rootkits ${rootkits:-0}" "security_rkhunter_warnings ${warnings}" \
      "security_scan_last_success_timestamp_seconds{tool=\"rkhunter\"} $(date +%s)"
  else
    metric "security_rkhunter_possible_rootkits ${rootkits:-0}" "security_rkhunter_warnings ${warnings}"
  fi
  ;;
clamav)
  # clamd only for the scan: one multi-threaded pass instead of a single-core clamscan that
  # never finished. Real local filesystems only; TrueNAS scans its own datasets.
  mapfile -t targets < <(findmnt -rn -t ext4,xfs,btrfs -o TARGET,FSROOT |
    awk '$2 == "/" && $1 !~ "^/run/media/" {print $1}')
  # --fdpass needs clamd's Unix socket. Over TCP, clamd (user clamav) opens every path itself and
  # is denied: "Infected files: 0" with nothing scanned, 21/11 to 26/11/2026.
  if ! grep -q '^LocalSocket ' "${CLAMD_CONF:-/etc/clamav/clamd.conf}"; then
    echo "clamd has no LocalSocket: --fdpass cannot work, scan refused" >&2
    exit 78
  fi
  if ! systemctl is-active --quiet clamav-daemon; then
    systemctl start clamav-daemon
    started=true
  fi
  # clamd needs about a minute to load its signatures before it answers.
  clamdscan --ping=60:5 >/dev/null
  rc=0
  clamdscan --multiscan --fdpass --infected --log="${day}/clamav.log" "${targets[@]}" \
    >"${day}/clamav.txt" 2>&1 || rc=$?
  # 1 = infected files found, 2 = errors (unreadable files): both still produce a report.
  [ "${rc}" -le 2 ] || exit "${rc}"
  infected="$(grep -c ' FOUND$' "${day}/clamav.txt" || true)"
  if [ "${rc}" -eq 2 ]; then
    scan_state=INCOMPLETE
    metric "security_clamav_infected_files ${infected}"
  else
    metric "security_clamav_infected_files ${infected}" \
      "security_scan_last_success_timestamp_seconds{tool=\"clamav\"} $(date +%s)"
  fi
  ;;
openscap)
  # No SSG content for 26.04 yet: the 24.04 content with its platform check retargeted.
  src=/usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml
  ds="${base}/ssg-ubuntu2404-$(lsb_release -cs)-ds.xml"
  sed "s/\^DISTRIB_CODENAME=noble\\\$/^DISTRIB_CODENAME=$(lsb_release -cs)\$/" "${src}" >"${ds}"
  # Exit 2 means some rules failed: expected, the report is what matters. Absolute path: the
  # hand-built /usr/local/bin/oscap comes first in PATH and misses librpm.so.8 (26/11/2026).
  "${OSCAP:-/usr/bin/oscap}" xccdf eval --profile xccdf_org.ssgproject.content_profile_cis_level1_workstation \
    --results "${day}/openscap-results.xml" --report "${day}/openscap-cis-l1-workstation.html" \
    "${ds}" >"${day}/openscap.txt" 2>&1 || [ $? -eq 2 ]
  fail="$(grep -cP '^Result\s+fail' "${day}/openscap.txt" || true)"
  pass="$(grep -cP '^Result\s+pass' "${day}/openscap.txt" || true)"
  metric "security_openscap_rules{result=\"fail\"} ${fail}" "security_openscap_rules{result=\"pass\"} ${pass}" \
    "security_scan_last_success_timestamp_seconds{tool=\"openscap\"} $(date +%s)"
  ;;
*)
  echo "unknown tool: ${tool}" >&2
  exit 64
  ;;
esac

printf '{"tool":"%s","state":"%s"}\n' "${tool}" "${scan_state}" >"${day}/.scan-${tool}.json.tmp"
chmod 0640 "${day}/.scan-${tool}.json.tmp"
mv "${day}/.scan-${tool}.json.tmp" "${day}/.scan-${tool}.json"
chgrp -R "${group}" "${day}"
chmod -R g+rX "${day}"
