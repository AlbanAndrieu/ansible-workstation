"""Offline regression contracts for redacted workstation configuration audit."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "scripts/audit-workstation-configuration.py"
spec = importlib.util.spec_from_file_location("workstation_config_audit", PATH)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class TestConfigurationAudit(unittest.TestCase):
    def test_inventory_never_reads_contents(self):
        with patch.object(Path, "is_symlink", return_value=False), \
             patch.object(Path, "is_dir", return_value=False), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "read_text", side_effect=AssertionError("content read")):
            result = audit.inventory(Path("/etc"))
        self.assertEqual(result["ssh/sshd_config"], "file_present_review_required")

    def test_symlinks_not_followed(self):
        with patch.object(Path, "is_symlink", return_value=True):
            result = audit.inventory(Path("/etc"))
        self.assertEqual(result["fstab"], "symlink_review_required")

    def test_dns_expected(self):
        def fake(argv, timeout=5):
            if argv[:2] == ["resolvectl", "dns"]:
                return 0, "Link 2 (eno1): 172.17.0.1"
            if argv[:2] == ["resolvectl", "domain"]:
                return 0, "Link 2 (eno1): ~int.albandrieu.com"
            return 0, "172.17.0.1"
        with patch.object(audit, "run", side_effect=fake):
            status = audit.audit_dns("eno1")
        self.assertEqual(status["resolved_link_dns"], "expected")
        self.assertEqual(status["private_route_domain"], "expected")

    def test_dns_unexpected_extra_resolver(self):
        with patch.object(audit, "run", side_effect=[
            (0, "Link 2: 172.17.0.1 9.9.9.9"),
            (0, "Link 2: ~int.albandrieu.com"),
            (0, "172.17.0.1"),
        ]):
            status = audit.audit_dns("eno1")
        self.assertEqual(status["resolved_link_dns"], "drift_or_unverified")

    def test_unit_environment_never_requested(self):
        with patch.object(audit, "run", return_value=(0, "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n")) as run:
            status = audit.unit_status("openclaw-gateway.service", True)
        self.assertEqual(status["ActiveState"], "active")
        args = run.call_args.args[0]
        self.assertNotIn("Environment", str(args))
        self.assertNotIn("ExecStart", str(args))
        self.assertIn("--user", args)

    def test_invalid_interface(self):
        with self.assertRaises(ValueError):
            audit.audit_dns("eno1;echo secret")


if __name__ == "__main__":
    unittest.main()
