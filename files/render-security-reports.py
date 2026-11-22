#!/usr/bin/env python3
"""Render a static, sanitized security posture dashboard from local scanner reports.

Never copy raw scanner text, hostnames, paths, usernames or finding descriptions
into the JSON summary. Full reports remain protected by the LAN-only Apache ACL.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import tempfile

DATE = re.compile(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}\Z")
TOOLS = ("lynis", "rkhunter", "clamav", "openscap")
LINKS = (
    "lynis.txt", "lynis-report.dat", "rkhunter-warnings.txt",
    "clamav.txt", "openscap-cis-l1-workstation.html", "openscap.txt",
)
MAX_READ = 1024 * 1024


def read_text(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_READ:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def count_integer(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def collect(tool: str, day: Path) -> dict:
    raw = {
        "lynis": ("lynis-report.dat", "lynis.txt"),
        "rkhunter": ("rkhunter-warnings.txt", "rkhunter.log"),
        "clamav": ("clamav.txt", "clamav.log"),
        "openscap": ("openscap.txt", "openscap-results.xml"),
    }[tool]
    receipt_path = day / f".scan-{tool}.json"
    receipt = read_text(receipt_path)
    state = "NOT_RUN"
    if receipt is None and (receipt_path.exists() or receipt_path.is_symlink()):
        state = "INCOMPLETE"
    elif receipt is not None:
        try:
            payload = json.loads(receipt)
            if payload.get("tool") == tool and payload.get("state") in ("COMPLETE", "INCOMPLETE"):
                state = payload["state"]
            else:
                state = "INCOMPLETE"
        except (ValueError, AttributeError):
            state = "INCOMPLETE"
    if state == "NOT_RUN" and any((day / filename).is_file() for filename in raw):
        state = "PARTIAL"
    metrics: dict[str, int] = {}
    if tool == "lynis":
        data = read_text(day / "lynis-report.dat") or ""
        index = count_integer(r"^hardening_index=([0-9]{1,3})\s*$", data)
        if index is not None and index <= 100:
            metrics["hardening_index"] = index
        metrics["warnings"] = len(re.findall(r"^warning\[\]=", data, re.MULTILINE))
        if index is None and state == "COMPLETE":
            state = "INCOMPLETE"
    elif tool == "rkhunter":
        data = read_text(day / "rkhunter-warnings.txt")
        if data is not None:
            metrics["warning_lines"] = len(re.findall(r"^Warning:", data, re.MULTILINE))
        else:
            if state == "COMPLETE":
                state = "INCOMPLETE"
    elif tool == "clamav":
        data = read_text(day / "clamav.txt") or ""
        count = count_integer(r"^Infected files:\s*(\d+)\s*$", data)
        if count is not None:
            metrics["infected_files_reported"] = count
        # A truncated scanner report is never a clean bill of health.
        if count is None and state == "COMPLETE":
            state = "INCOMPLETE"
    elif tool == "openscap":
        data = read_text(day / "openscap.txt") or ""
        metrics["passed"] = len(re.findall(r"^Result\s+pass\b", data, re.MULTILINE))
        metrics["failed"] = len(re.findall(r"^Result\s+fail\b", data, re.MULTILINE))
        if metrics["passed"] + metrics["failed"] == 0 and state == "COMPLETE":
            state = "INCOMPLETE"
    return {"state": state, "metrics": metrics}


def summarize(source: Path) -> dict:
    days = []
    if source.is_dir() and not source.is_symlink():
        for day in sorted(source.iterdir(), reverse=True):
            if not DATE.fullmatch(day.name) or not day.is_dir() or day.is_symlink():
                continue
            days.append({
                "date": day.name,
                "scans": {tool: collect(tool, day) for tool in TOOLS},
            })
    return {
        "schema": "workstation-security-summary/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "local-workstation",
        "classification": "REDACTED_COUNTS_ONLY",
        "days": days[:90],
    }


def to_html(summary: dict, dest: Path) -> str:
    rows = []
    for entry in summary["days"]:
        day = entry["date"]
        for tool, record in entry["scans"].items():
            state = record["state"]
            counts = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in record["metrics"].items()) or "aucune métrique validée"
            links = []
            for filename in LINKS:
                if not filename.startswith(tool) and not (tool == "lynis" and filename == "lynis-report.dat"):
                    continue
                if (dest / day / filename).is_file() and not (dest / day / filename).is_symlink():
                    href = f"{day}/{filename}"
                    links.append(f'<a href="{html.escape(href, quote=True)}">{html.escape(filename)}</a>')
            rows.append(
                f"<tr><td>{html.escape(day)}</td><th scope='row'>{html.escape(tool)}</th>"
                f"<td><strong>{html.escape(state)}</strong></td><td>{html.escape(counts)}</td>"
                f"<td>{' · '.join(links) if links else '—'}</td></tr>"
            )
    body = "\n".join(rows) or '<tr><td colspan="5">Aucun scan disponible — NOT_RUN</td></tr>'
    recent = []
    for tool in TOOLS:
        latest = next(
            ((day["date"], day["scans"][tool]["state"]) for day in summary["days"]
             if day["scans"][tool]["state"] != "NOT_RUN"),
            (None, "NOT_RUN"),
        )
        stamp = latest[0] or "aucune date"
        recent.append(
            f'<li><strong>{html.escape(tool)}</strong>'
            f'<span class="status">{html.escape(latest[1])}</span>'
            f'<small>{html.escape(stamp)}</small></li>'
        )
    cards = "".join(recent)
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Posture de sécurité · Workstation</title>'
        '<style>body{font:1rem system-ui;margin:2rem auto;max-width:76rem;padding:0 1rem;'
        'color:#24303a}table{width:100%;border-collapse:collapse}td,th{padding:.75rem;'
        'border-bottom:1px solid #ccd4dc;text-align:left}thead{background:#edf2f5}'
        'a{color:#135b9b}small{color:#586574}table{display:block;overflow-x:auto}'
        '.status-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));'
        'gap:.75rem;list-style:none;padding:0}.status-grid li{display:flex;'
        'flex-direction:column;gap:.3rem;padding:1rem;border:1px solid #ccd4dc;'
        'border-radius:.5rem}.status{font-weight:700;letter-spacing:.04em}</style>'
        '</head><body><main><h1>Posture de sécurité · Workstation</h1>'
        '<p>Rapport local. Un compteur nul n’est pas une preuve d’absence de vulnérabilité.'
        ' Les scans incomplets sont marqués INCOMPLETE ou PARTIAL.</p>'
        f'<small>Actualisé : {html.escape(summary["generated_at"])}</small>'
        '<section aria-label="Dernier résultat connu par scanner">'
        '<h2>Dernier résultat disponible</h2><ul class="status-grid">'
        + cards + '</ul></section><h2>Historique local</h2>'
        '<table><thead><tr><th>Date</th><th>Outil</th><th>État</th>'
        '<th>Mesures</th><th>Rapport privé</th></tr></thead><tbody>'
        + body + '</tbody></table></main></body></html>\n'
    )


def atomic_write(path: Path, content: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".security-summary-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), 0o640)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if not args.destination.is_dir() or args.destination.is_symlink():
        parser.error("destination must be a pre-existing regular directory")
    summary = summarize(args.source)
    atomic_write(args.destination / "summary.json", json.dumps(summary, indent=2) + "\n")
    atomic_write(args.destination / "index.html", to_html(summary, args.destination))
    print(f"security_summary_days={len(summary['days'])} publication=local")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
