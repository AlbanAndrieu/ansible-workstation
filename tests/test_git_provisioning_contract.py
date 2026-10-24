#!/usr/bin/env python3
"""Offline assertions for opt-in SCM workstation provisioning."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GitProvisioningContract(unittest.TestCase):
    def test_default_registration_off(self):
        defaults = (ROOT / "defaults/main.yml").read_text()
        self.assertIn("workstation_myrepos_autoregister_enabled: false", defaults)

    def test_opt_in_is_guarded_and_non_root(self):
        tasks = (ROOT / "tasks/git.yml").read_text()
        self.assertIn("- workstation_myrepos_autoregister_enabled | bool", tasks)
        self.assertIn("root={{ workstation_myrepos_root | quote }}", tasks)
        self.assertIn("become: false", tasks)
        self.assertNotIn("{{ jenkins_user }}", tasks)
        self.assertNotIn("mr register $d/..", tasks)

    def test_homebrew_is_mac_only(self):
        tasks = (ROOT / "tasks/git.yml").read_text()
        section = tasks.split("- name: brew | Install hub (GitHub CLI)", 1)[1]
        section = section.split("- name: git | Install GitLab CLI", 1)[0]
        self.assertIn("ansible_system == 'Darwin'", section)
        self.assertIn("become: false", section)


if __name__ == "__main__":
    unittest.main()
