#!/usr/bin/env bash
# Draw the xscreensaver Matrix hack full screen on every monitor after MATRIX_IDLE_MIN minutes idle.
# The xscreensaver daemon cannot run under GNOME Wayland: GNOME itself blanks and locks the session
# (org.gnome.desktop.session idle-delay); this only draws until the next input or the lock.
# Usage: matrix-screensaver.sh [--once]
set -uo pipefail

idle_limit_ms=$((${MATRIX_IDLE_MIN:-10} * 60000))
hack="${MATRIX_HACK:-/usr/libexec/xscreensaver/xmatrix}"
export DISPLAY="${DISPLAY:-:0}"
pids=()

# Mutter keeps counting under Wayland, where X11 idle timers only see Xwayland clients.
idle_ms() {
  gdbus call --session --dest org.gnome.Mutter.IdleMonitor \
    --object-path /org/gnome/Mutter/IdleMonitor/Core \
    --method org.gnome.Mutter.IdleMonitor.GetIdletime 2>/dev/null |
    sed -nE 's/^\(uint64 ([0-9]+),\)$/\1/p'
}

locked() {
  gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver \
    --method org.gnome.ScreenSaver.GetActive 2>/dev/null | grep -q true
}

start() {
  local geometry pid wid
  # Xwayland lists each GNOME monitor as WIDTH/mmxHEIGHT/mm+X+Y.
  while read -r geometry; do
    "${hack}" -geometry "${geometry}" &
    pids+=("$!")
  done < <(xrandr --listmonitors |
    sed -nE 's#^ *[0-9]+: [^ ]+ ([0-9]+)/[0-9]+x([0-9]+)/[0-9]+\+([0-9]+)\+([0-9]+).*#\1x\2+\3+\4#p')
  sleep 1
  # Fullscreen keeps each window on the monitor it opened on, above the top bar.
  for pid in "${pids[@]}"; do
    for wid in $(wmctrl -lp | awk -v pid="${pid}" '$3 == pid {print $1}'); do
      wmctrl -i -r "${wid}" -b add,fullscreen
    done
  done
}

stop() {
  ((${#pids[@]})) && kill "${pids[@]}" 2>/dev/null
  pids=()
}

trap 'stop; exit 0' TERM INT

while :; do
  idle="$(idle_ms)"
  if [[ -n "${idle}" ]] && ((idle >= idle_limit_ms)) && ! locked; then
    ((${#pids[@]})) || start
  else
    stop
  fi
  [[ "${1:-}" == --once ]] && break
  sleep 2
done
