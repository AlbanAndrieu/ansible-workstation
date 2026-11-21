"""Contract: only approved aggregate JSON may pass from NFS into local Apache."""
from pathlib import Path
import json
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "files/publish-ctem-web-mirror.py"
MOD = runpy.run_path(str(SCRIPT))
CATEGORIES = {category: 0 for category in MOD["CATALOG_CLASSES"]}


def report():
    return {
        "schema_version": 1, "report": "ctem-amass-aggregates",
        "observed_at": "2026-11-21T12:00:00+00:00",
        "status": "OBSERVED_NOT_CERTIFIED", "vantage": "truenas-internal",
        "domains_in_scope": 20, "candidate_count": 0,
        "catalog_categories": CATEGORIES.copy(),
        "interpretation": "ASSET_CANDIDATES_NOT_CONFIRMED_PUBLIC_EXPOSURES_OR_VULNERABILITIES",
    }


class WorkstationMirrorTest(unittest.TestCase):
    def test_valid_report_keeps_only_aggregate_counts(self):
        data = MOD["verified_public"](report())
        html = MOD["render"](data)
        self.assertIn("CTEM", html)
        self.assertNotIn("/mnt/cpool/ctem/amass/reports", html)
        self.assertNotIn("candidate-2026", html)
        self.assertNotIn("albandrieu.com", html)
        self.assertIn("noindex,nofollow", html)

    def test_reject_hostname_fields_and_nested_extras(self):
        for key, value in (
            ("candidates", [{"hostname": "secret.albandrieu.com"}]),
            ("raw_dns", {"A": "192.0.2.3"}),
            ("entityRef", "component:default/secret"),
        ):
            obj = report()
            obj[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                MOD["verified_public"](obj)
        obj = report()
        obj["catalog_categories"]["private_domain"] = 5
        with self.assertRaises(ValueError):
            MOD["verified_public"](obj)

    def test_reject_incomplete_or_inconsistent_data(self):
        for field, value in (
            ("status", "ENGINE_EXITED"),
            ("vantage", "external-github-hosted"),
            ("candidate_count", 4),
            ("domains_in_scope", -1),
        ):
            obj = report()
            obj[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                MOD["verified_public"](obj)

    def test_reject_symlinked_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.json"
            source.write_text(json.dumps(report()))
            self.assertEqual(MOD["load_source"](source)["report"], "ctem-amass-aggregates")
            symlink = Path(temp) / "alias.json"
            symlink.symlink_to(source)
            with self.assertRaises(ValueError):
                MOD["load_source"](symlink)

    def test_installation_remains_opt_in_and_reports_are_local(self):
        script = SCRIPT.read_text()
        playbook = (ROOT / "playbooks/security-scans.yml").read_text()
        conf = (ROOT / "files/etc/apache2/conf-available/nabla-lan-only.conf").read_text()
        self.assertIn("CTEM_WORKSTATION_MIRROR_APPROVED", script)
        self.assertIn("/media/www/reports/ctem/amass-summary.json", script)
        self.assertIn("/var/www/reports/ctem", script)
        self.assertIn("publish-ctem-web-mirror.py", playbook)
        self.assertIn("Alias /reports /var/www/reports", conf)
        self.assertNotIn("Alias /reports /media/www", conf)
        self.assertNotIn("systemd.timer", script)


if __name__ == "__main__":
    unittest.main()
