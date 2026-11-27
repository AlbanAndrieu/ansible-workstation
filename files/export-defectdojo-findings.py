#!/usr/bin/env python3
"""Turn the latest Lynis and OpenSCAP reports into one DefectDojo Generic Findings file.

Manual step, never automatic: the owner reviews the file, then imports it on TrueNAS
through the nabla-compose gate (producer workstation-host). Fixed envelope and fields,
stable ids, no IP or e-mail address: the gate can check the file strictly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from xml.etree import ElementTree

NAME = "Nabla workstation host scans"
TYPE = "Workstation Host Scan"
LYNIS = re.compile(
    r"^(warning|suggestion)\[\]=([A-Z]+-[0-9]{4})\|([^|]*)\|([^|]*)\|([^|]*)\|",
    re.MULTILINE,
)
RULE = "xccdf_org.ssgproject.content_rule_"
PROFILE = "CIS Level 1 Workstation (SSG Ubuntu 24.04 content)"
SEVERITY = {"high": "High", "medium": "Medium", "low": "Low"}
INTERNAL = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b|[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def latest(source: Path, filename: str) -> Path | None:
    days = sorted(
        d
        for d in source.glob("20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]")
        if (d / filename).is_file()
    )
    return days[-1] / filename if days else None


def finding(tool: str, ident: str, title: str, severity: str, description: str) -> dict:
    title, description = (
        INTERNAL.sub("@@INTERNAL@@", s).strip() for s in (title, description)
    )
    return {
        "title": f"{tool} {ident}: {title}",
        "severity": severity,
        "description": description[:2000],
        "unique_id_from_tool": "workstation-"
        + hashlib.sha256(f"{tool}|{ident}|{title}".encode()).hexdigest(),
        "active": True,
        "verified": False,
    }


def lynis(report: Path) -> list[dict]:
    rows = []
    for kind, ident, text, details, solution in LYNIS.findall(
        report.read_text(errors="replace"),
    ):
        extra = [s for s in (details, solution) if s and s != "-"]
        rows.append(
            finding(
                "Lynis",
                ident,
                text,
                "Medium" if kind == "warning" else "Low",
                " ".join([f"Lynis {kind}: {text.rstrip('.')}.", *extra]),
            ),
        )
    return rows


def openscap(results: Path) -> list[dict]:
    titles, rows = {}, []
    for _, elem in ElementTree.iterparse(results):
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag == "Rule":
            titles[elem.get("id")] = " ".join(elem.findtext("{*}title", "").split())
            elem.clear()
        elif tag == "rule-result":
            if elem.findtext("{*}result") == "fail" and elem.get(
                "idref",
                "",
            ).startswith(RULE):
                idref = elem.get("idref")
                rows.append(
                    finding(
                        "OpenSCAP",
                        idref.removeprefix(RULE),
                        titles.get(idref, idref),
                        SEVERITY.get(elem.get("severity"), "Info"),
                        f"{PROFILE}: rule {idref} failed.",
                    ),
                )
            elem.clear()
    return rows


def export(source: Path) -> dict:
    found = []
    if path := latest(source, "lynis-report.dat"):
        found += lynis(path)
    if path := latest(source, "openscap-results.xml"):
        found += openscap(path)
    unique = list({row["unique_id_from_tool"]: row for row in found}.values())
    if not unique:
        raise SystemExit("no Lynis or OpenSCAP finding to export")
    return {"name": NAME, "type": TYPE, "findings": unique}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("/var/lib/security-reports"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.dumps(export(args.source), indent=1, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=args.output.parent, prefix=".defectdojo-")
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, args.output)
    print(f"{len(json.loads(data)['findings'])} findings -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
