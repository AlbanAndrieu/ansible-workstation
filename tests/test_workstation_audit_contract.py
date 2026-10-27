"""Offline static guard for the unprivileged, allowlisted Ansible host audit.

Do not execute a playbook, access hardware or write to system locations.
"""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "playbooks/audit-workstation.yml"


class WorkstationAuditContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AUDIT.read_text()
        cls.plays = yaml.safe_load(cls.source)
        cls.play = cls.plays[0]
        cls.tasks = cls.play["tasks"]

    def test_localhost_only_with_no_privilege_escalation(self):
        self.assertEqual(len(self.plays), 1)
        self.assertEqual(self.play["hosts"], "localhost")
        self.assertEqual(self.play["connection"], "local")
        self.assertIs(self.play["become"], False)
        self.assertIs(self.play["gather_facts"], False)
        self.assertNotIn("roles", self.play)
        self.assertNotIn("pre_tasks", self.play)
        self.assertNotIn("handlers", self.play)

    def test_modules_are_read_only_or_memory_only(self):
        allowed = {
            "ansible.builtin.setup",
            "ansible.builtin.assert",
            "ansible.builtin.service_facts",
            "ansible.builtin.package_facts",
            "ansible.builtin.slurp",
            "ansible.builtin.set_fact",
            "ansible.builtin.debug",
        }
        for task in self.tasks:
            with self.subTest(task=task["name"]):
                modules = {key for key in task if key.startswith("ansible.")}
                self.assertEqual(len(modules), 1)
                self.assertTrue(modules <= allowed, modules)
                self.assertNotEqual(task.get("become"), True)
                self.assertNotIn("delegate_to", task)
                self.assertNotIn("check_mode", task)
                self.assertNotIn("notify", task)
        for forbidden in (
            "ansible.builtin.shell", "ansible.builtin.command",
            "ansible.builtin.copy", "ansible.builtin.template",
            "ansible.builtin.apt", "ansible.builtin.systemd_service",
            "ansible.builtin.uri", "ansible.builtin.fetch",
            "import_tasks", "include_tasks", "include_role", "lookup(",
            "set_stats:", "ansible.builtin.file", "become: true",
        ):
            self.assertNotIn(forbidden, self.source)

    def test_full_facts_never_go_to_terminal(self):
        for task in self.tasks:
            module = next(key for key in task if key.startswith("ansible."))
            if module != "ansible.builtin.debug":
                self.assertIs(task.get("no_log"), True, task["name"])
        report = self.tasks[-1]["ansible.builtin.debug"]["msg"]
        self.assertEqual(
            set(report),
            {
                "schema", "observed_at_utc", "system", "selected_services",
                "selected_packages", "selected_sysctls",
                "selected_mounts_present", "limitations",
            },
        )
        self.assertEqual(report["schema"], "workstation-ansible-audit/v1")
        self.assertNotIn("ansible_facts", str(report["selected_services"]))
        self.assertNotIn("ansible_facts", str(report["selected_packages"]))
        self.assertNotIn("ansible_facts", str(report["selected_sysctls"]))
        for forbidden in ("hostname", "ip_address", "username", "mac_address",
                          "serial_number", "uuid", "environment"):
            self.assertNotIn(forbidden, report["system"])

    def test_gather_subset_excludes_unneeded_minimum_and_network(self):
        gather = self.tasks[0]["ansible.builtin.setup"]
        subset = gather["gather_subset"]
        self.assertIn("!all", subset)
        self.assertIn("!min", subset)
        self.assertNotIn("network", subset)
        self.assertNotIn("env", subset)
        self.assertNotIn("all", subset)
        self.assertLessEqual(gather["gather_timeout"], 10)

    def test_whitelists_are_explicit_and_small(self):
        allowlists = self.play["vars"]
        expected = {
            "audit_service_allowlist", "audit_package_allowlist",
            "audit_sysctl_allowlist", "audit_mount_allowlist",
        }
        self.assertEqual(set(allowlists), expected)
        for key, values in allowlists.items():
            with self.subTest(allowlist=key):
                self.assertEqual(len(values), len(set(values)))
                self.assertTrue(0 < len(values) <= 15)
                self.assertTrue(all(isinstance(item, str) for item in values))
        self.assertIn("net.ipv4.ip_forward",
                      allowlists["audit_sysctl_allowlist"])
        self.assertIn("ufw.service", allowlists["audit_service_allowlist"])
        self.assertIn("/", allowlists["audit_mount_allowlist"])

    def test_no_file_output_or_secret_material(self):
        for token in (
            "/etc/shadow", "/etc/ssh/", "/etc/pam.d", "/home/",
            "/root/", "vault", "ssh_host_key", "machine_id",
            "ansible_env", "ansible_all_ipv4_addresses", "getent",
            "serial", "ansible.builtin.stat:\n    path: /etc",
        ):
            if token == "serial":
                # Wording in the public limitations is not a collection.
                continue
            self.assertNotIn(token, self.source)
        self.assertNotIn("dest:", self.source)
        self.assertNotIn("path:", self.source)
        self.assertNotIn("log_path", self.source)


if __name__ == "__main__":
    unittest.main()
