#!/usr/bin/env bash
# Weekly ClamAV scan of the workstation's own disks (stabilize-workstation.yml).
# TrueNAS shares (NFS automounts under /media) are scanned on TrueNAS: --cross-fs=no never enters them.
set -euo pipefail

# Real local filesystems only: bind mounts (FSROOT other than /) and removable media are skipped.
mapfile -t targets < <(
  findmnt -rn -t ext4,xfs,btrfs -o TARGET,FSROOT | awk '$2 == "/" && $1 !~ "^/run/media/" {print $1}'
)

exec nice -n 19 ionice -c3 clamscan --recursive --infected --cross-fs=no \
  --exclude-dir='^/home/[^/]+/\.clamtk/viruses' \
  --log="/var/log/clamav/local-disks-$(date +%F).log" "${targets[@]}"
