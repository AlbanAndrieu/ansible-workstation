"""Safely mirror the redacted CTEM Amass summary from TrueNAS NFS to local Apache.

Source: /media/www/reports/ctem/amass-summary.json (NFS, sanitized)
Target: /var/www/reports/ctem/ (existing local Apache Alias /reports)
Never copy NFS HTML, candidates-*.json, PostgreSQL or TrueNAS private reports.
Manual --apply only; no timer or permanent NFS mount is installed.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import grp
from html import escape
import json
import os
from pathlib import Path
import stat

SOURCE = Path("/media/www/reports/ctem/amass-summary.json")
TARGET = Path("/var/www/reports/ctem")
CATALOG_CLASSES = {
    "MATCHED_PUBLIC_INTENT", "LAN_ONLY_POLICY_REVIEW",
    "NON_PUBLIC_INTENT_REVIEW", "AMBIGUOUS_ENTITY_REVIEW",
    "UNMAPPED_REVIEW",
}
ALLOWED = {
    "schema_version", "report", "observed_at", "status",
    "vantage", "domains_in_scope", "candidate_count",
    "catalog_categories", "interpretation",
}
MAX_SOURCE = 16_384


def verified_public(data: object) -> dict:
    if not isinstance(data, dict) or set(data) != ALLOWED:
        raise ValueError("invalid or unexpected CTEM report keys")
    if (data["schema_version"] != 1 or data["report"] != "ctem-amass-aggregates"
            or data["status"] != "OBSERVED_NOT_CERTIFIED"
            or data["vantage"] != "truenas-internal"
            or data["interpretation"] != "ASSET_CANDIDATES_NOT_CONFIRMED_PUBLIC_EXPOSURES_OR_VULNERABILITIES"
            or type(data["domains_in_scope"]) is not int
            or not 1 <= data["domains_in_scope"] <= 100
            or type(data["candidate_count"]) is not int
            or not 0 <= data["candidate_count"] <= 100_000_000):
        raise ValueError("invalid CTEM summary contract")
    classes = data["catalog_categories"]
    if (not isinstance(classes, dict) or set(classes) != CATALOG_CLASSES
            or any(type(value) is not int or value < 0 for value in classes.values())
            or sum(classes.values()) != data["candidate_count"]):
        raise ValueError("invalid CTEM class totals")
    if not isinstance(data["observed_at"], str):
        raise ValueError("missing time")
    stamp = datetime.fromisoformat(data["observed_at"].replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("observation time lacks timezone")
    return data


def load_source(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("CTEM NFS source not present or symlink")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or not 0 < st.st_size <= MAX_SOURCE:
        raise ValueError("CTEM summary exceeds bound")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        data = stream.read(MAX_SOURCE + 1)
    if len(data) != st.st_size:
        raise ValueError("CTEM NFS summary changed during copy")
    return verified_public(json.loads(data))


def render(data: dict) -> str:
    categories = "".join(
        "<tr><td>" + escape(key) + "</td><td>" + str(val) + "</td></tr>"
        for key, val in sorted(data["catalog_categories"].items())
    )
    return (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='robots' content='noindex,nofollow,noarchive'>"
        "<meta http-equiv='Content-Security-Policy' "
        "content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'\">"
        "<title>CTEM | Agrégats uniquement</title>"
        "<style>body{font:16px system-ui,sans-serif;max-width:900px;"
        "margin:2rem auto;padding:0 1rem}td,th{padding:.5rem;"
        "border-bottom:1px solid #ddd;text-align:left}</style>"
        "</head><body><h1>CTEM — Observation Amass</h1>"
        "<p>Aucun sous-domaine ni relation réseau affiché.</p>"
        "<p>Constat : " + escape(data["observed_at"]) + "</p>"
        "<p>Domaines : " + str(data["domains_in_scope"])
        + " ; actifs candidats : " + str(data["candidate_count"]) + "</p>"
        "<table><tbody>" + categories + "</tbody></table>"
        "<p>Une découverte n'est pas une vulnérabilité confirmée.</p></body></html>\n"
    )


def publish(destination: Path, data: dict) -> None:
    parent = destination.parent
    if destination.is_symlink() or parent.is_symlink() or not parent.is_dir():
        raise ValueError("unsafe local Apache directory")
    owner = os.geteuid()
    group = grp.getgrnam("www-data").gr_gid
    info = parent.stat()
    if info.st_uid != owner or info.st_gid != group or not info.st_mode & stat.S_ISGID:
        raise ValueError("Apache report parent has unexpected ownership/group")
    if not destination.exists():
        destination.mkdir(mode=0o2750)
    if (destination.is_symlink() or destination.stat().st_uid != owner
            or destination.stat().st_gid != group):
        raise ValueError("Apache CTEM target ownership invalid")
    for filename, content in (
        ("amass-summary.json", json.dumps(data, sort_keys=True, indent=2) + "\n"),
        ("index.html", render(data)),
    ):
        target = destination / filename
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError("Apache target not a regular file")
        tmp = destination / f".{filename}.tmp-{os.getpid()}"
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                     | getattr(os, "O_NOFOLLOW", 0), 0o640)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=SOURCE)
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument("--check", action="store_true")
    m.add_argument("--apply", action="store_true")
    opts = p.parse_args()
    if opts.apply and (
        os.geteuid() == 0 or os.environ.get("CTEM_WORKSTATION_MIRROR_APPROVED") != "YES"
    ):
        p.error("non-root workstation user and CTEM_WORKSTATION_MIRROR_APPROVED=YES required")
    summary = load_source(opts.source)
    if opts.check:
        print("CHECK: approved CTEM redacted NFS summary valid; Apache not modified")
        return 0
    publish(TARGET, summary)
    print("PUBLISHED: redacted CTEM summary copied to local Apache /reports/ctem")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        raise SystemExit(f"REJECTED: {type(exc).__name__}; no untrusted NFS HTML copied") from None
