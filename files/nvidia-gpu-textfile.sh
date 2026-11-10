#!/usr/bin/env bash
# Write NVIDIA GPU metrics for the node_exporter textfile collector, every INTERVAL seconds.
# Usage: nvidia-gpu-textfile.sh OUTPUT.prom [INTERVAL]
# One long-running nvidia-smi instead of a timer: no journal line per sample.
# node_textfile_mtime_seconds shows staleness if nvidia-smi stops answering.
set -euo pipefail

out="${1:?output .prom file}"
interval="${2:-15}"
fields=uuid,name,driver_version,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw,power.limit,clocks.gr,fan.speed

# Prints one gauge; skips [N/A] and other non-numeric values. $5 converts to base units.
gauge() {
  local value="${3// /}"
  [[ "${value}" =~ ^[0-9]+(\.[0-9]+)?$ ]] || return 0
  printf '# HELP %s %s\n# TYPE %s gauge\n%s{uuid="%s"} %s\n' "$1" "$2" "$1" "$1" "${uuid}" \
    "$(awk -v v="${value}" -v s="$4" 'BEGIN { printf "%.10g", v * s }')"
}

# shortcut: one file per sample line, so it only fits a single-GPU host; group lines per sample for more.
nvidia-smi --query-gpu="${fields}" --format=csv,noheader,nounits -l "${interval}" |
  while IFS=, read -r uuid name driver util mem_util mem_used mem_total temp power power_limit clock fan; do
    tmp="$(mktemp "${out}.XXXXXX")"
    trap 'rm -f "${tmp}"' EXIT
    {
      echo "# HELP nvidia_gpu_info GPU model and driver."
      echo "# TYPE nvidia_gpu_info gauge"
      echo "nvidia_gpu_info{uuid=\"${uuid}\",name=\"${name# }\",driver_version=\"${driver# }\"} 1"
      gauge nvidia_gpu_utilization_ratio "Share of time a kernel ran on the GPU." "${util}" 0.01
      gauge nvidia_gpu_memory_utilization_ratio "Share of time the memory was read or written." "${mem_util}" 0.01
      gauge nvidia_gpu_memory_used_bytes "VRAM in use." "${mem_used}" 1048576
      gauge nvidia_gpu_memory_total_bytes "VRAM size." "${mem_total}" 1048576
      gauge nvidia_gpu_temperature_celsius "GPU core temperature." "${temp}" 1
      gauge nvidia_gpu_power_draw_watts "Board power draw." "${power}" 1
      gauge nvidia_gpu_power_limit_watts "Board power limit." "${power_limit}" 1
      gauge nvidia_gpu_clock_graphics_hertz "Graphics clock." "${clock}" 1000000
      gauge nvidia_gpu_fan_speed_ratio "Fan speed." "${fan}" 0.01
    } >"${tmp}"
    chmod 0644 "${tmp}"
    mv "${tmp}" "${out}"
  done
