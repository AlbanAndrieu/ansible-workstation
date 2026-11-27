"""Contract for the manual Lynis/OpenSCAP export to DefectDojo Generic Findings."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "files/export-defectdojo-findings.py"
FIELDS = {
    "title",
    "severity",
    "description",
    "unique_id_from_tool",
    "active",
    "verified",
}
R = "xccdf_org.ssgproject.content_rule_"
XCCDF = f"""<?xml version="1.0"?>
<Benchmark xmlns="http://checklists.nist.gov/xccdf/1.2">
 <Group id="g"><Rule id="{R}grub2_password" severity="high">
  <title>Set Boot Loader
   Password in grub2</title></Rule></Group>
 <TestResult>
  <rule-result idref="{R}grub2_password" severity="high"><result>fail</result>
  </rule-result>
  <rule-result idref="{R}aide_installed" severity="medium"><result>pass</result>
  </rule-result>
 </TestResult>
</Benchmark>
"""
# Repeated on purpose: a duplicate line yields one finding.
DNS = "suggestion[]=NAME-4028|Check DNS for 172.17.0.24 and root@example.org|-|-|\n"


class DefectDojoExportContracts(unittest.TestCase):
    def setUp(self):
        self.src = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.src, ignore_errors=True)
        self.out = self.src / "out.json"

    def day(self, name, files):
        path = self.src / name
        path.mkdir()
        for filename, body in files.items():
            (path / filename).write_text(body)

    def run_export(self):
        return subprocess.run(
            [sys.executable, "-I", EXPORT, "--source", self.src, "--output", self.out],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_latest_reports_become_strict_generic_findings(self):
        self.day("2026-11-25", {"lynis-report.dat": "warning[]=OLD-0001|stale|-|-|\n"})
        self.day(
            "2026-11-26",
            {
                "lynis-report.dat": "warning[]=AUTH-9216|grpck found errors.|-|-|\n"
                + DNS
                + DNS,
                "openscap-results.xml": XCCDF,
            },
        )
        result = self.run_export()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(self.out.read_text())
        self.assertEqual(oct(self.out.stat().st_mode & 0o777), "0o600")
        self.assertEqual(set(report), {"name", "type", "findings"})
        self.assertEqual(
            (report["name"], report["type"]),
            ("Nabla workstation host scans", "Workstation Host Scan"),
        )
        rows = {row["title"]: row for row in report["findings"]}
        self.assertEqual(
            {title: row["severity"] for title, row in rows.items()},
            {
                "Lynis AUTH-9216: grpck found errors.": "Medium",
                "Lynis NAME-4028: Check DNS for @@INTERNAL@@ and @@INTERNAL@@": "Low",
                "OpenSCAP grub2_password: Set Boot Loader Password in grub2": "High",
            },
        )
        self.assertNotIn("172.17.", self.out.read_text())
        self.assertNotIn("@example", self.out.read_text())
        for title, row in rows.items():
            self.assertEqual(set(row), FIELDS)
            self.assertIs(row["active"], True)
            self.assertIs(row["verified"], False)
            # The gate can recompute every id from the title alone.
            tool, ident, text = re.fullmatch(
                r"(Lynis|OpenSCAP) ([^:]+): (.*)",
                title,
            ).groups()
            digest = hashlib.sha256(f"{tool}|{ident}|{text}".encode()).hexdigest()
            self.assertEqual(row["unique_id_from_tool"], f"workstation-{digest}")

    def test_no_report_exports_nothing(self):
        self.day("2026-11-26", {"lynis.txt": "no structured report\n"})
        result = self.run_export()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
