#!/usr/bin/env python3
"""Static, offline contracts. Never install packages or change host networking."""
from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ModernRuntimeSecurityContract(unittest.TestCase):
    def test_runtime_metadata(self):
        cfg = tomllib.loads((ROOT / "mise.toml").read_text())
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(cfg["tools"]["python"], "3.12")
        self.assertEqual(cfg["tools"]["node"], "24")
        self.assertIn("uv", cfg["tools"])
        self.assertFalse(cfg["settings"]["task"]["run_auto_install"])
        self.assertTrue(project["tool"]["uv"]["package"] is False)
        self.assertTrue(project["project"]["requires-python"].startswith(">=3.12"))
        self.assertTrue(
            any(
                d.startswith("ansible-core>=2.21")
                for d in project["project"]["dependencies"]
            )
        )

    def test_no_direnv_downloads(self):
        envrc = (ROOT / ".envrc").read_text()
        for forbidden in (
            "curl ", "pip install", "pyenv install",
            "source .env.secrets", "unset PS1", "nvm install",
        ):
            self.assertNotIn(forbidden, envrc)

    def test_ansible_defaults_fail_safe(self):
        defaults = (ROOT / "defaults/main.yml").read_text()
        for value in (
            "tailscale_enabled: false",
            "workstation_tailscale_disable_existing: true",
            "workstation_cloudflared_manage_existing: false",
            "workstation_firewall_manage_enabled: false",
            "workstation_legacy_asdf_enabled: false",
            "workstation_legacy_python_enabled: false",
            "workstation_mise_uv_provision_enabled: false",
            "workstation_split_dns_enabled: false",
        ):
            with self.subTest(default=value):
                self.assertIn(value, defaults)

    def test_non_destructive_vpn_management(self):
        security = (ROOT / "tasks/security.yml").read_text()
        self.assertIn("state: stopped", security)
        self.assertIn("enabled: false", security)
        self.assertIn("not (tailscale_enabled | bool)", security)
        self.assertIn("'tailscaled.service' in ansible_facts.services", security)
        self.assertNotIn(
            "state: absent", security[security.index("# Tailscale is retained"):]
        )
        self.assertIn("workstation_firewall_manage_enabled | bool", security)
        self.assertIn("workstation_cloudflared_manage_existing | bool", security)
        self.assertNotIn("cloudflared service install", security)

    def test_legacy_python_global_pip_disabled(self):
        main = (ROOT / "tasks/workstation.yml").read_text()
        self.assertIn("workstation_legacy_python_enabled | bool", main)
        self.assertIn("workstation_legacy_asdf_enabled | bool", main)
        self.assertIn("runtime_mise_uv.yml", main)
        dev = (ROOT / "tasks/dev.yml").read_text()
        self.assertNotIn("curl -o- https://raw.githubusercontent.com/nvm-sh/", dev)

    def test_dns_reconciliation_preserved(self):
        network = (ROOT / "tasks/network.yml").read_text()
        self.assertIn("network_split_dns.yml", network)
        assert (ROOT / "tasks/network_split_dns.yml").exists()


if __name__ == "__main__":
    unittest.main()
