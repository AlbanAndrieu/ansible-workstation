"""Fail-closed DNS playbook discovery tests; no Ansible or network execution."""
from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
from unittest import mock
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "scripts/check_homelab_dns_gate.py"
spec = importlib.util.spec_from_file_location("workstation_dns_gate", FILE)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)


class DNSGateTests(unittest.TestCase):
    def test_targets_dns_only_role_entrypoint(self):
        content = (ROOT / "playbooks/homelab-dns.yml").read_text()
        self.assertIn("tasks_from: network_split_dns", content)
        self.assertIn("import_role:", content)
        self.assertIn("workstation_split_dns_enabled | bool", content)
        self.assertIn("tags: [dns]", content)
        self.assertNotIn("tasks_from: workstation", content)
        self.assertNotIn("gather_facts: true", content)

    def test_test_suite_minima(self):
        self.assertEqual(gate.TEST_SUITES, (
            ("test_homelab_dns_guard_contract.py", 8),
            ("test_homelab_dns_nta_dispatcher.py", 17),
        ))

    def test_zero_discovered_tests_is_a_failure_even_with_exit_zero(self):
        with mock.patch.object(
            gate, "execute", return_value=(0, "\nRan 0 tests in 0.000s\n\nOK\n")
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(gate.run_suite("test_homelab_dns_guard_contract.py", 8))

    def test_wrong_role_checkout_must_be_rejected(self):
        with mock.patch.object(gate.PLAYBOOK, "is_file", return_value=False):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(gate.verify_workspace())

    def test_unexpected_remote_must_be_rejected(self):
        with mock.patch.object(
            gate, "execute", return_value=(0, "git@github.com:OtherProject/foo.git\n")
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(gate.verify_workspace())

    def test_correct_remote_accepts_ssh_https_git(self):
        with mock.patch.object(
            gate, "execute", return_value=(0, "git@github.com:AlbanAndrieu/ansible-workstation.git\n")
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(gate.verify_workspace())

    def test_empty_ansible_list_is_failure(self):
        output = "playbook: playbooks/workstation.yml\nplay #1 localhost: tasks:\n"
        with mock.patch.object(gate, "execute", return_value=(0, output)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(gate.task_list())

    def test_incomplete_task_list_is_failure(self):
        output = "workstation | Read active NetworkManager profile\n"
        with mock.patch.object(gate, "execute", return_value=(0, output)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(gate.task_list())

    def test_real_dns_list_is_required(self):
        output = "\n".join(gate.REQUIRED_TASKS)
        with mock.patch.object(gate, "execute", return_value=(0, output)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(gate.task_list())

    def test_dry_run_rejects_facts_only(self):
        output = "PLAY [Install default]\nTASK [Gathering Facts]\nok: [localhost]\n"
        with mock.patch.object(gate, "execute", return_value=(0, output)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(gate.dry_run())

    def test_an_ansible_role_prefix_is_accepted_in_check(self):
        output = (
            "PLAY [Inspect]\n"
            "TASK [../ : workstation | Validate opt-in split DNS parameters]\n"
            "TASK [../ : workstation | Read active NetworkManager profile]\n"
        )
        with mock.patch.object(gate, "execute", return_value=(0, output)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(gate.dry_run())

    def test_command_restricts_to_localhost_dns_only_and_check_mode(self):
        for mode in ("list", "check"):
            cmd = gate.command(mode)
            self.assertIn("localhost,", cmd)
            self.assertIn("--tags", cmd)
            self.assertIn("dns", cmd)
            self.assertIn("playbooks/homelab-dns.yml", " ".join(cmd))
            self.assertIn("workstation_split_dns_nta_dispatcher_enabled=true", cmd)
            self.assertIn("workstation_split_dns_persistent_nta_enabled=false", cmd)
            self.assertNotIn("--limit", cmd)
        self.assertIn("--check", gate.command("check"))
        self.assertIn("--diff", gate.command("check"))
        self.assertNotIn("--check", gate.command("list"))

    def test_main_aborts_after_failed_suite_without_ansible(self):
        with mock.patch.object(gate, "verify_workspace", return_value=True):
            with mock.patch.object(gate, "run_suite", return_value=False):
                with mock.patch.object(gate, "task_list") as list_tasks:
                    with mock.patch.object(sys, "argv", [str(FILE)]):
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(gate.main(), 1)
                    list_tasks.assert_not_called()


if __name__ == "__main__":
    unittest.main()
