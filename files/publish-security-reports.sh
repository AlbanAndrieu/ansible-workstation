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

# Newest first; one line per day with the files it holds.
{
  printf '<!doctype html>\n<html lang="fr"><meta charset="utf-8"><title>Rapports de sécurité</title>\n'
  printf '<h1>Rapports de sécurité de la workstation</h1>\n<p>Mis à jour le %s.</p>\n<ul>\n' "$(date '+%F %T')"
  for d in $(find "${dest}" -mindepth 1 -maxdepth 1 -type d -name '20??-??-??' -printf '%f\n' | sort -r); do
    printf '<li>%s :' "${d}"
    for f in "${dest}/${d}"/*; do
      [ -f "${f}" ] || continue
      n="$(basename "${f}")"
      printf ' <a href="%s/%s">%s</a>' "${d}" "${n}" "${n}"
    done
    printf '</li>\n'
  done
  printf '</ul>\n</html>\n'
} >"${dest}/index.html.tmp"
mv "${dest}/index.html.tmp" "${dest}/index.html"
