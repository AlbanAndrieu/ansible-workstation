#!/usr/bin/env bash
# Move /home onto its NVMe LV, once, at boot before any session or daemon writes to it.
# Usage: home-nvme-switch.sh LV HOME STAGING FSTAB
# A warm copy already sits on the LV: the final pass only copies what changed. A failure leaves
# the old /home in place, so the boot goes on with it (docs/runbook-storage-nvme.md).
set -euo pipefail

lv="${1:?LV device}"
home="${2:?home directory}"
staging="${3:?staging mount point}"
fstab="${4:?fstab}"
old="${home}.sda-old"

if mountpoint -q "${home}"; then
  echo "${home} is already a mount point: nothing to do"
  exit 0
fi

mountpoint -q "${staging}" || mount "${lv}" "${staging}"
rsync -aHAXS --numeric-ids --delete "${home}/" "${staging}/"
umount "${staging}"

rollback() {
  if mountpoint -q "${home}"; then umount "${home}"; fi
  rmdir "${home}" 2>/dev/null || true
  mv "${old}" "${home}"
  echo "switch failed: ${home} put back" >&2
}
mv "${home}" "${old}"
trap rollback ERR
mkdir -m 0755 "${home}"
mount "${lv}" "${home}"
echo "${lv} ${home} ext4 defaults,nofail,x-systemd.device-timeout=30s 0 0" >>"${fstab}"
trap - ERR
echo "${home} is now on ${lv}; the old copy stays in ${old}"
