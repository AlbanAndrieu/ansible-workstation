"""Offline regression contracts for redacted workstation configuration audit."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/audit-workstation-configuration.py"
spec = importlib.util.spec_from_file_location("workstation_config_audit", PATH)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def matching_report(policy):
    """Synthetic observation that satisfies every non-review expectation."""
    def units(section):
        return {
            unit: {
                "LoadState": "loaded",
                "ActiveState": entry.get("active_state", "inactive"),
                "UnitFileState": entry.get("unit_file_state", "disabled"),
            }
            for unit, entry in policy[section].items()
        }
    return {
        "etc": {
            path: audit.ETC_KINDS[entry.get("expect", "absent")]
            for path, entry in policy["etc_paths"].items()
        },
        "system_units": units("system_units"),
        "user_units": units("user_units"),
        "dns": {
            "resolved_link_dns": "expected",
            "private_route_domain": "expected",
            "link_probes": {"dns": "ok", "domain": "ok"},
        },
    }


class TestDeclaredPolicy(unittest.TestCase):
    def setUp(self):
        self.policy = audit.load_policy(audit.DEFAULT_POLICY)

    def test_repository_policy_covers_exactly_the_probes(self):
        self.assertEqual(set(self.policy["etc_paths"]), set(audit.ETC_PATHS))
        self.assertEqual(set(self.policy["system_units"]), set(audit.SYSTEM_UNITS))
        self.assertEqual(set(self.policy["user_units"]), set(audit.USER_UNITS))

    def test_policy_dns_matches_ansible_defaults(self):
        defaults = yaml.safe_load((ROOT / "defaults/main.yml").read_text())
        dns = self.policy["dns"]
        self.assertEqual(dns["interface"], defaults["workstation_split_dns_interface"])
        self.assertEqual(dns["resolver"], defaults["workstation_split_dns_resolver"])
        domain = defaults["workstation_split_dns_domain"]
        self.assertEqual(dns["route_domain"], "~" + domain)
        task = (ROOT / "tasks/network_split_dns.yml").read_text()
        self.assertIn(f"workstation_split_dns_resolver == '{dns['resolver']}'", task)

    def test_policy_cannot_widen_or_skip_probes(self):
        widened = copy.deepcopy(self.policy)
        widened["etc_paths"]["shadow"] = {"level": "review"}
        skipped = copy.deepcopy(self.policy)
        del skipped["system_units"]["ufw.service"]
        for policy in (widened, skipped):
            with self.assertRaises(audit.PolicyError):
                audit.validate_policy(policy)

    def test_never_capture_paths_are_not_audited(self):
        self.assertIn("shadow", self.policy["never_capture"])
        self.assertIn("NetworkManager/system-connections", self.policy["never_capture"])
        overlapping = copy.deepcopy(self.policy)
        overlapping["never_capture"].append("ssh/sshd_config")
        with self.assertRaises(audit.PolicyError):
            audit.validate_policy(overlapping)

    def test_expectations_require_evidence_and_review_has_none(self):
        no_evidence = copy.deepcopy(self.policy)
        del no_evidence["etc_paths"]["fstab"]["evidence"]
        review_with_expect = copy.deepcopy(self.policy)
        review_with_expect["etc_paths"]["sudoers.d"]["expect"] = "directory"
        bad_state = copy.deepcopy(self.policy)
        bad_state["system_units"]["fail2ban.service"]["active_state"] = "active; id"
        list_expect = copy.deepcopy(self.policy)
        list_expect["etc_paths"]["fstab"]["expect"] = ["file"]
        for policy in (no_evidence, review_with_expect, bad_state, list_expect):
            with self.assertRaises(audit.PolicyError):
                audit.validate_policy(policy)

    def test_dns_contract_cannot_be_redirected(self):
        redirected = copy.deepcopy(self.policy)
        redirected["dns"]["resolver"] = "9.9.9.9"
        with self.assertRaises(audit.PolicyError):
            audit.validate_policy(redirected)

    def test_matching_observation_conforms(self):
        result = audit.compare(matching_report(self.policy), self.policy)
        self.assertEqual(result["status"], "conforms_to_declared_policy")
        self.assertNotIn("required_drift", result["counts"])
        sudoers = result["findings"]["etc/sudoers.d"]
        self.assertEqual(sudoers["outcome"], "review_required")

    def test_required_drift_is_non_compliant(self):
        report = matching_report(self.policy)
        report["system_units"]["fail2ban.service"]["ActiveState"] = "inactive"
        result = audit.compare(report, self.policy)
        self.assertEqual(result["status"], "non_compliant")
        fail2ban = result["findings"]["system_units/fail2ban.service"]
        self.assertEqual(fail2ban["outcome"], "drift")

    def test_failed_dns_probe_is_unknown_not_expected(self):
        report = matching_report(self.policy)
        report["dns"]["link_probes"]["dns"] = "failed"
        result = audit.compare(report, self.policy)
        self.assertEqual(result["findings"]["dns/resolver"]["outcome"], "unknown")
        self.assertEqual(result["status"], "incomplete")

    def test_symlink_is_unknown_and_missing_unit_is_drift(self):
        report = matching_report(self.policy)
        report["etc"]["crypttab"] = "symlink_review_required"
        report["system_units"]["ufw.service"]["LoadState"] = "not-found"
        result = audit.compare(report, self.policy)
        self.assertEqual(result["findings"]["etc/crypttab"]["outcome"], "unknown")
        ufw = result["findings"]["system_units/ufw.service"]
        self.assertEqual(ufw["outcome"], "drift")

    def test_baseline_change_is_not_non_compliance(self):
        report = matching_report(self.policy)
        report["user_units"]["openclaw-gateway.service"]["ActiveState"] = "inactive"
        result = audit.compare(report, self.policy)
        self.assertEqual(result["status"], "changed_since_baseline")

    def test_report_carries_outcomes_not_policy_values(self):
        text = str(audit.compare(matching_report(self.policy), self.policy))
        self.assertNotIn(audit.EXPECTED_DNS, text)
        self.assertNotIn("evidence", text)
        self.assertNotIn("docs/", text)

    def test_invalid_policy_errors_never_echo_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "policy.yml"
            bad.write_text("schema: [unclosed\ncanary: do-not-echo-canary\n")
            broken = audit.evaluate_policy({}, bad)
            bad.write_text("schema: workstation-os-policy/v1\ndo-not-echo-canary: 1\n")
            unknown = audit.evaluate_policy({}, bad)
        for result in (broken, unknown):
            self.assertEqual(result["status"], "invalid_policy")
            self.assertNotIn("do-not-echo-canary", str(result))


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
        self.assertEqual(status["link_probes"], {"dns": "ok", "domain": "ok"})

    def test_dns_probe_failure_is_reported_separately_from_drift(self):
        with patch.object(audit, "run", return_value=(127, "")):
            status = audit.audit_dns("eno1")
        self.assertEqual(status["resolved_link_dns"], "drift_or_unverified")
        self.assertEqual(status["link_probes"], {"dns": "failed", "domain": "failed"})

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

    def test_user_unit_fragment_and_dropins_are_redacted(self):
        private = "/home/example/.config/systemd/user"
        output = (
            "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"
            f"FragmentPath={private}/openclaw-gateway.service\n"
            f"DropInPaths={private}/openclaw-gateway.service.d/override.conf\n"
        )
        with patch.object(Path, "home", return_value=Path("/home/example")), \
             patch.object(audit, "run", return_value=(0, output)) as runner:
            result = audit.unit_status("openclaw-gateway.service", True)
        self.assertEqual(result["fragment_source"], "user_config")
        self.assertEqual(result["dropins"], "present_review_required")
        self.assertEqual(result["effective_execstart_alignment"], "not_verified")
        self.assertNotIn("/home/example", str(result))
        command = runner.call_args.args[0]
        self.assertIn("FragmentPath", command)
        self.assertIn("DropInPaths", command)
        self.assertNotIn("ExecStart", command)
        self.assertNotIn("Environment", command)

    def test_system_unit_source_is_classified_without_raw_path(self):
        with patch.object(audit, "run", return_value=(
            0, "FragmentPath=/etc/systemd/system/hide-mac.service\nDropInPaths=\n"
        )):
            status = audit.unit_status("hide-mac.service", False)
        self.assertEqual(status["fragment_source"], "etc")
        self.assertEqual(status["dropins"], "none")
        self.assertNotIn("/etc/systemd/system", str(status))

    def test_unavailable_unit_metadata_remains_unknown(self):
        with patch.object(audit, "run", return_value=(1, "")):
            status = audit.unit_status("openclaw-gateway.service", True)
        self.assertEqual(status["fragment_source"], "unknown")
        self.assertEqual(status["dropins"], "unknown")

    def test_invalid_interface(self):
        with self.assertRaises(ValueError):
            audit.audit_dns("eno1;echo secret")


if __name__ == "__main__":
    unittest.main()
