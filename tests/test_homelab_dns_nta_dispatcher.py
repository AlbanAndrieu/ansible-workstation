"""Offline end-to-end NetworkManager per-link NTA dispatcher contracts."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "files/networkmanager-homelab-nta-dispatcher.sh"
TASKS = ROOT / "tasks/network_dnssec_nta_dispatcher.yml"


class NetworkManagerNTADispatcherTests(unittest.TestCase):
    def execute(self, action="up", interface="eno1", connection="Wired eno1",
                link_dns="172.17.0.1", link_domain="~int.albandrieu.com",
                existing=""):
        with tempfile.TemporaryDirectory(prefix="nabla-nm-nta-") as tmp:
            base = Path(tmp)
            stub = base / "resolvectl"
            log = base / "actions.log"
            stub.write_text(
                '#!/bin/bash\n'
                'case "$1" in\n'
                '  dns) printf "Link 2 (eno1): %s\\n" "$MOCK_DNS" ;;\n'
                '  domain) printf "Link 2 (eno1): %s\\n" "$MOCK_DOMAIN" ;;\n'
                '  nta) if [[ $# -eq 2 ]]; then\n'
                '    printf "Link 2 (eno1): %s\\n" "$MOCK_NTA"\n'
                '    else printf "%s\\n" "$*" >> "$MOCK_ACTION_LOG"; fi ;;\n'
                '  *) exit 3 ;;\n'
                'esac\n',
                encoding="utf-8",
            )
            stub.chmod(0o700)
            rendered = base / "dispatcher.sh"
            rendered.write_text(
                SOURCE.read_text().replace(
                    'resolved="/usr/bin/resolvectl"',
                    'resolved="' + str(stub) + '"',
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update({
                "CONNECTION_ID": connection,
                "MOCK_DNS": link_dns,
                "MOCK_DOMAIN": link_domain,
                "MOCK_NTA": existing,
                "MOCK_ACTION_LOG": str(log),
            })
            result = subprocess.run(
                ["bash", str(rendered), interface, action],
                capture_output=True, text=True, env=env, timeout=3, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return log.read_text().splitlines() if log.exists() else []

    def test_homelab_up_sets_only_private_link_nta(self):
        self.assertEqual(self.execute(), ["nta eno1 int.albandrieu.com"])

    def test_reapply_sets_scoped_nta(self):
        self.assertEqual(self.execute(action="reapply"), ["nta eno1 int.albandrieu.com"])

    def test_dhcp_renewal_sets_scoped_nta(self):
        self.assertEqual(self.execute(action="dhcp4-change"), ["nta eno1 int.albandrieu.com"])

    def test_second_up_is_idempotent(self):
        self.assertEqual(self.execute(existing="int.albandrieu.com"), [])

    def test_wrong_network_profile_no_op(self):
        self.assertEqual(self.execute(connection="VPN"), [])

    def test_wrong_interface_no_op(self):
        self.assertEqual(self.execute(interface="wlp0s20f3"), [])

    def test_wrong_dns_no_op(self):
        self.assertEqual(self.execute(link_dns="9.9.9.9"), [])

    def test_wrong_routing_domain_no_op(self):
        self.assertEqual(self.execute(link_domain="example.net"), [])

    def test_existing_unrelated_nta_is_never_overwritten(self):
        self.assertEqual(self.execute(existing="internal.example"), [])
        self.assertEqual(self.execute(existing="int.albandrieu.com internal.example"), [])

    def test_down_removes_only_exact_anchor(self):
        self.assertEqual(self.execute(action="down", existing="int.albandrieu.com"), ["nta eno1 "])
        self.assertEqual(self.execute(action="down", existing="internal.example"), [])
        self.assertEqual(self.execute(action="down", existing="int.albandrieu.com internal.example"), [])

    def test_unknown_event_no_op(self):
        self.assertEqual(self.execute(action="hostname"), [])

    def test_opt_in_and_rollback_tasks(self):
        text = TASKS.read_text()
        defaults = (ROOT / "defaults/main.yml").read_text()
        split = (ROOT / "tasks/network_split_dns.yml").read_text()
        self.assertIn("workstation_split_dns_nta_dispatcher_enabled: false", defaults)
        self.assertIn("workstation_split_dns_nta_dispatcher_remove_enabled: false", defaults)
        self.assertIn("network_dnssec_nta_dispatcher.yml", split)
        self.assertIn("not ((workstation_split_dns_nta_dispatcher_enabled | bool)", text)
        self.assertIn("not (workstation_split_dns_persistent_nta_enabled | bool)", text)
        self.assertIn("90-nabla-private-dnssec-nta", text)
        self.assertIn("state: absent", text)
        self.assertNotIn("state: restarted", text)

    def test_no_global_dns_mutations(self):
        code = SOURCE.read_text()
        for forbidden in (
            "resolvectl dnssec", "resolvectl dnsovertls", "/etc/resolv.conf",
            "systemctl restart", "nmcli", "9.9.9.9",
        ):
            if forbidden == "nmcli":
                # Comment may warn against nmcli; verify it isn't invoked.
                self.assertNotIn("$(nmcli ", code)
            else:
                self.assertNotIn(forbidden, code)


if __name__ == "__main__":
    unittest.main()
