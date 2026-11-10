#!/usr/bin/env bash
# Write the Docker healthcheck state of the given containers for the node_exporter textfile collector.
# Usage: docker-health-textfile.sh OUTPUT.prom CONTAINER...
# A missing, stopped or unhealthy container reports 0; node_textfile_mtime_seconds shows staleness.
set -euo pipefail

out="${1:?output .prom file}"
shift
# Same directory for an atomic rename; the collector ignores names not ending in .prom.
tmp="$(mktemp "${out}.XXXXXX")"
trap 'rm -f "${tmp}"' EXIT

{
  echo "# HELP workstation_container_healthy 1 when the Docker healthcheck of the container reports healthy."
  echo "# TYPE workstation_container_healthy gauge"
  for name in "$@"; do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${name}" 2>/dev/null || echo missing)"
    healthy=0
    [[ "${status}" == healthy ]] && healthy=1
    echo "workstation_container_healthy{container=\"${name}\"} ${healthy}"
  done
} >"${tmp}"

chmod 0644 "${tmp}"
mv "${tmp}" "${out}"
trap - EXIT
