"""Offline safety checks for the Ansible DNS hook and split-DNS reconciliation.

No sudo, DNS calls, Ansible apply or real workstation interface is used.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "templates/hide-location.sh-Ubuntu.j2"
SPLIT = ROOT / "tasks/network_split_dns.yml"


def stub(path: Path, contents: str) -> None:
    path.write_text("#!/bin/bash\nset -euo pipefail\n" + contents, encoding="utf-8")
    path.chmod(0o700)


class HomelabDNSGuardContract(unittest.TestCase):
    def run_hook(self, *, nm_dns: str, domain: str, link_dns: str,
                 expected_override: bool) -> None:
        with tempfile.TemporaryDirectory(prefix="homelab-dns-fixture-") as folder:
            root = Path(folder)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            rendered = HOOK.read_text(encoding="utf-8")
            for key, value in (
                ("{{ dns_default }}", "172.17.0.24"),
                ("{{ dns_new }}", "9.9.9.9 149.112.112.112"),
                ("{{ net_interface }}", "eno1"),
                ("{{ workstation_split_dns_resolver | default('172.17.0.1') }}",
                 "172.17.0.1"),
                ("{{ workstation_split_dns_domain | default('int.albandrieu.com') }}",
                 "int.albandrieu.com"),
            ):
                self.assertIn(key, rendered)
                rendered = rendered.replace(key, value)
            self.assertNotIn("{{", rendered)
            script = root / "hide-location.sh"
            stub(script, rendered.removeprefix("#!/bin/bash\n"))

            stub(bin_dir / "nmcli", 'printf "%s\\n" "${MOCK_NM_DNS}"\n')
            stub(
                bin_dir / "resolvectl",
                'case "$1" in\n'
                '  domain) printf "Link 2 (eno1): %s\\n" "${MOCK_DOMAIN}" ;;\n'
                '  dns) printf "Link 2 (eno1): %s\\n" "${MOCK_LINK_DNS}" ;;\n'
                '  *) exit 2 ;;\n'
                'esac\n',
            )
            stub(bin_dir / "sudo", 'printf "%s\\n" "$*" >> "$MOCK_SUDO_LOG"\n')
            env = os.environ.copy()
            env.update({
                "PATH": str(bin_dir) + os.pathsep + env.get("PATH", ""),
                "MOCK_NM_DNS": nm_dns,
                "MOCK_DOMAIN": domain,
                "MOCK_LINK_DNS": link_dns,
                "MOCK_SUDO_LOG": str(root / "sudo.log"),
            })
            p = subprocess.run(
                ["bash", str(script)], cwd=root, env=env,
                text=True, capture_output=True, timeout=10, check=False,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            action_log = root / "sudo.log"
            if expected_override:
                self.assertTrue(action_log.exists())
                self.assertEqual(
                    action_log.read_text().strip(),
                    "resolvectl dns eno1 9.9.9.9 149.112.112.112",
                )
            else:
                self.assertFalse(action_log.exists(), p.stdout + p.stderr)

    def test_homelab_nm_dns_prevents_override_despite_resolved_drift(self):
        self.run_hook(nm_dns="172.17.0.1", domain="",
                      link_dns="172.17.0.24", expected_override=False)

    def test_homelab_route_domain_prevents_override(self):
        self.run_hook(nm_dns="9.9.9.9", domain="~int.albandrieu.com",
                      link_dns="172.17.0.24", expected_override=False)

    def test_homelab_search_domain_prevents_override(self):
        self.run_hook(nm_dns="9.9.9.9", domain="int.albandrieu.com",
                      link_dns="172.17.0.24", expected_override=False)

    def test_non_lan_dns_override_is_preserved(self):
        self.run_hook(nm_dns="9.9.9.9", domain="example.org",
                      link_dns="172.17.0.24", expected_override=True)

    def test_other_links_dns_cannot_trigger_override(self):
        self.run_hook(nm_dns="9.9.9.9", domain="example.org",
                      link_dns="9.9.9.9", expected_override=False)

    def test_ansible_reapplies_resolved_if_profile_already_correct(self):
        contents = SPLIT.read_text(encoding="utf-8")
        self.assertIn("workstation_dns_effective_before", contents)
        self.assertIn("workstation_dns_update is changed", contents)
        self.assertIn("workstation_dns_domain_update is changed", contents)
        self.assertIn("+ipv4.dns-search", contents)
        self.assertIn("when: not ansible_check_mode", contents)
        self.assertIn("workstation_split_dns_resolver not in", contents)
        self.assertIn('or \'9.9.9.9\' in workstation_dns_effective_before.stdout',
                      contents)
        self.assertIn('~{{ workstation_split_dns_domain }}', contents)
        self.assertIn("argv: [nmcli, device, reapply", contents)
        self.assertNotIn("command: > /etc/resolv.conf", contents)
        self.assertNotIn("argv: [tee, /etc/resolv.conf", contents)


if __name__ == "__main__":
    unittest.main()
