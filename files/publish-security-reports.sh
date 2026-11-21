#!/usr/bin/env bash
# Copy the local security reports to the Apache docroot and rebuild its index (playbooks/security-scans.yml).
# Runs as albandrieu, the owner of the local /var/www/reports (not the TrueNAS NFS docroot).
# Apache serves /reports to the LAN and to Cloudflare Access (files/etc/apache2/conf-available/nabla-lan-only.conf).
set -euo pipefail
umask 027

# Overridable only so the contract tests can run against temporary directories.
src="${SECURITY_REPORTS_DIR:-/var/lib/security-reports}"
dest="${SECURITY_PUBLISH_DIR:-/var/www/reports/security}"
keep_days=90

mkdir -p "${dest}"
# The setgid www-data parent gives new files the www-data group, so Apache can read them.
rsync -rt --chmod=D2750,F0640 --exclude='ssg-*-ds.xml' "${src}/" "${dest}/"
find "${dest}" -mindepth 1 -maxdepth 1 -type d -name '20??-??-??' -mtime +"${keep_days}" -exec rm -r -- {} +

# Render only structured, privacy-safe aggregate counters and LAN-only raw links.
# Never send unredacted findings to the public site or DefectDojo automatically.
python3 "$(dirname "$0")/render-security-reports.py" --source "$src" --destination "$dest"
