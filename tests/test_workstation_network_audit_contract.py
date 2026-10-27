"""Offline contract for the read-only, privacy-preserving network gate."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit-workstation-network.py"
PLAYBOOK = ROOT / "playbooks/audit-workstation-network.yml"
SPEC = importlib.util.spec_from_file_location("workstation_network_audit", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class WorkstationNetworkAuditContract(unittest.TestCase):
    def test_fixed_read_only_probes_without_root_or_docker_socket(self):
        self.assertEqual(set(AUDIT.COMMANDS), {"nft", "iptables", "ip6tables"})
        for name, argv in AUDIT.COMMANDS.items():
            with self.subTest(name=name):
                self.assertTrue(argv[0].startswith("/usr/sbin/"))
                self.assertTrue(all("docker" not in part for part in argv))
        source = SCRIPT.read_text()
        for forbidden in (
            "shell=True", "sudo ", "sudo -n", "subprocess.Popen", "os.system",
            "socket.connect", "/var/run/docker.sock", "docker info",
            "iptables -P", "nft add", "nft flush", "iptables -A",
            "write_text(", "write_bytes(", "chmod(", "mkdir(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_nft_aggregates_without_exposing_rules_or_names(self):
        raw = json.dumps({"nftables": [
            {"table": {"family": "ip", "name": "docker-bridges"}},
            {"chain": {"family": "inet", "table": "private_secret",
                       "name": "CUSTOM_PRIVATE", "type": "filter",
                       "hook": "forward", "policy": "drop"}},
            {"chain": {"family": "inet", "type": "nat", "hook": "prerouting",
                       "policy": "accept"}},
            {"rule": {"family": "ip", "table": "docker-bridges",
                      "expr": [{"match": {"right": "192.0.2.15"}}],
                      "comment": "MY_SECRET"}},
        ]})
        result = AUDIT.parse_nft(raw)
        self.assertEqual(result["total_rules_seen"], 1)
        self.assertTrue(result["docker_table_present"])
        self.assertEqual(result["filter_base_chains"], [
            {"family": "inet", "hook": "forward", "policy": "drop"}
        ])
        self.assertNotIn("MY_SECRET", json.dumps(result))
        self.assertNotIn("192.0.2.15", json.dumps(result))
        self.assertNotIn("CUSTOM_PRIVATE", json.dumps(result))

    def test_iptables_aggregates_without_exposing_address_or_port(self):
        raw = (
            "*filter\n:INPUT DROP [0:0]\n:FORWARD ACCEPT [0:0]\n"
            ":OUTPUT ACCEPT [0:0]\n:DOCKER-USER - [0:0]\n"
            "-A INPUT -s 192.0.2.33/32 -p tcp --dport 9999 -j ACCEPT\n"
            "COMMIT\n"
        )
        result = AUDIT.parse_iptables(raw)
        self.assertEqual(result["builtin_policies"]["INPUT"], "drop")
        self.assertTrue(result["docker_user_chain_present"])
        self.assertEqual(result["filter_rules_seen"], 1)
        self.assertNotIn("192.0.2.33", json.dumps(result))
        self.assertNotIn("9999", json.dumps(result))

    def test_explicit_verdict_counts_and_forward_docker_user_jump(self):
        raw = (
            "*filter\n:INPUT ACCEPT [0:0]\n:FORWARD ACCEPT [0:0]\n"
            ":OUTPUT ACCEPT [0:0]\n:DOCKER-USER - [0:0]\n"
            "-A FORWARD -j DOCKER-USER\n"
            "-A DOCKER-USER -s 192.0.2.42 -j DROP\n"
            "-A DOCKER-USER -j RETURN\n"
            '-A INPUT -m comment --comment "-j ACCEPT" -j REJECT\n'
            "COMMIT\n"
        )
        result = AUDIT.parse_iptables(raw)
        self.assertTrue(result["docker_user_chain_present"])
        self.assertTrue(result["docker_user_jump_in_forward"])
        self.assertEqual(result["filter_rules_seen"], 4)
        self.assertEqual(
            result["explicit_terminal_verdict_rules"],
            {"accept": 0, "drop": 1, "reject": 1},
        )
        self.assertEqual(
            result["docker_user_explicit_verdict_rules"],
            {"accept": 0, "drop": 1, "reject": 0},
        )
        self.assertNotIn("192.0.2.42", json.dumps(result))
        self.assertNotIn("-j ACCEPT", json.dumps(result))

    def test_defined_docker_user_chain_does_not_prove_jump(self):
        raw = (
            "*filter\n:INPUT ACCEPT [0:0]\n:FORWARD ACCEPT [0:0]\n"
            ":OUTPUT ACCEPT [0:0]\n:DOCKER-USER - [0:0]\n"
            "-A FORWARD -j DOCKER\nCOMMIT\n"
        )
        summary = AUDIT.parse_iptables(raw)
        self.assertTrue(summary["docker_user_chain_present"])
        self.assertFalse(summary["docker_user_jump_in_forward"])
        self.assertEqual(
            summary["docker_user_explicit_verdict_rules"],
            {"accept": 0, "drop": 0, "reject": 0},
        )

    def test_nft_direct_verdicts_do_not_disclose_rule_data(self):
        raw = json.dumps({"nftables": [
            {"rule": {"expr": [
                {"match": {"right": "192.0.2.101"}},
                {"drop": None},
            ], "comment": "SECRET_REMARK"}},
            {"rule": {"expr": [{"reject": {"type": "icmpx"}}]}},
            {"rule": {"expr": [{"accept": None}]}},
            {"rule": {"expr": [{"verdict": {"kind": "drop"}}]}},
        ]})
        result = AUDIT.parse_nft(raw)
        self.assertEqual(
            result["explicit_terminal_verdict_rules"],
            {"accept": 1, "drop": 2, "reject": 1},
        )
        self.assertEqual(result["total_rules_seen"], 4)
        self.assertNotIn("SECRET_REMARK", json.dumps(result))
        self.assertNotIn("192.0.2.101", json.dumps(result))

    def test_access_denied_does_not_mean_empty_firewall(self):
        with mock.patch.object(
            AUDIT, "forwarding_state", return_value="unknown"
        ):
            result = AUDIT.inspect(probe=lambda name: ("access_denied", ""))
        self.assertEqual(result["effective_filtering"], "not_verified")
        self.assertFalse(result["docker_socket_queried"])
        self.assertTrue(all(
            v["status"] == "access_denied" and v["summary"] is None
            for v in result["firewall_probes"].values()
        ))

    def test_missing_or_malformed_nft_data_is_not_a_success(self):
        self.assertIsNone(AUDIT.parse_nft(""))
        self.assertIsNone(AUDIT.parse_nft("{broken"))
        with mock.patch.object(AUDIT, "forwarding_state", return_value="enabled"):
            result = AUDIT.inspect(probe=lambda _: ("ok", ""))
        self.assertTrue(all(
            r["status"] == "error" and r["summary"] is None
            for r in result["firewall_probes"].values()
        ))

    def test_json_cli_only_contains_allowlisted_results(self):
        fixture = {
            "schema": AUDIT.SCHEMA,
            "ip_forward": {"ipv4": "enabled", "ipv6": "disabled"},
            "firewall_probes": {
                "nft": {"status": "access_denied", "summary": None},
                "iptables": {"status": "missing", "summary": None},
                "ip6tables": {"status": "missing", "summary": None},
            },
            "effective_filtering": "not_verified",
            "docker_socket_queried": False,
            "limitations": AUDIT.LIMITS,
        }
        with mock.patch.object(AUDIT, "inspect", return_value=fixture):
            with mock.patch("sys.argv", ["audit-network", "--format", "json"]):
                out = io.StringIO()
                with redirect_stdout(out):
                    AUDIT.main()
        self.assertEqual(json.loads(out.getvalue()), fixture)

    def test_ansible_wrapper_is_exactly_local_and_no_become(self):
        plays = yaml.safe_load(PLAYBOOK.read_text())
        self.assertEqual(len(plays), 1)
        play = plays[0]
        self.assertEqual(play["hosts"], "localhost")
        self.assertEqual(play["connection"], "local")
        self.assertIs(play["become"], False)
        self.assertIs(play["gather_facts"], False)
        self.assertEqual(
            play["vars"]["ansible_python_interpreter"],
            "{{ ansible_playbook_python }}",
        )
        tasks = play["tasks"]
        self.assertEqual(len(tasks), 2)
        cmd = tasks[0]
        self.assertEqual(
            cmd["ansible.builtin.command"]["argv"],
            [
                "{{ ansible_playbook_python }}", "-B",
                "{{ playbook_dir }}/../scripts/audit-workstation-network.py",
                "--format", "json",
            ],
        )
        self.assertIs(cmd["changed_when"], False)
        self.assertIs(cmd["no_log"], True)
        self.assertEqual(
            tasks[1]["ansible.builtin.debug"]["msg"],
            "{{ audit_network_result.stdout | from_json }}",
        )

    def test_forwarding_state_fails_closed(self):
        with mock.patch.object(AUDIT.Path, "read_text", return_value="2\n"):
            self.assertEqual(AUDIT.forwarding_state("/proc/does-not-matter"), "unknown")
        with mock.patch.object(AUDIT.Path, "read_text", side_effect=OSError):
            self.assertEqual(AUDIT.forwarding_state("/proc/does-not-matter"), "unknown")


if __name__ == "__main__":
    unittest.main()
