"""Offline privacy/security contracts for the host listening bind-scope audit."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/audit-workstation-listeners.py"
PLAYBOOK = ROOT / "playbooks/audit-workstation-listeners.yml"
SPEC = importlib.util.spec_from_file_location("workstation_listener_audit", SOURCE)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class ListenerAuditContract(unittest.TestCase):
    def test_scope_parsing_classifies_wildcard_loopback_interface(self):
        examples = {
            "0.0.0.0:1234": "wildcard",
            "[::]:4242": "wildcard",
            "*:53": "wildcard",
            "127.0.0.1:1234": "loopback",
            "[::1]:443": "loopback",
            "[::ffff:127.0.0.1]:8000": "loopback",
            "192.0.2.33:8080": "interface_specific",
            "[2001:db8::14]:9090": "interface_specific",
            "[fe80::23%eth0]:5353": "interface_specific",
            "hostname.internal:9200": "unknown",
            "not-an-endpoint": "unknown",
        }
        for value, expected in examples.items():
            with self.subTest(endpoint=value):
                self.assertEqual(AUDIT.binding_scope(value), expected)

    def test_tcp_and_udp_counts_are_anonymized(self):
        fixture = (
            "LISTEN 0 128 0.0.0.0:2200 0.0.0.0:*\n"
            "LISTEN 0 128 127.0.0.1:8000 0.0.0.0:*\n"
            "UNCONN 0 0 [::1]:5353 [::]:*\n"
            "LISTEN 0 128 [2001:db8::7]:9999 [::]:*\n"
        )
        data = AUDIT.summarize_ss(fixture)
        self.assertEqual(data["count"], 4)
        self.assertEqual(
            data["bind_scopes"],
            {"wildcard": 1, "loopback": 2, "interface_specific": 1, "unknown": 0},
        )
        for secret in ("2200", "8000", "5353", "9999", "2001:db8"):
            self.assertNotIn(secret, json.dumps(data))

    def test_ss_peer_wildcards_must_not_override_local_binding(self):
        # In ss -H, the Peer Address:Port field is index 4 and is commonly
        # 0.0.0.0:* even when the LOCAL bind is strictly loopback.
        fixture = (
            "LISTEN 0 128 127.0.0.1:8080 0.0.0.0:*\n"
            "LISTEN 0 128 [::1]:8443 [::]:*\n"
            "UNCONN 0 0 192.0.2.42:5353 0.0.0.0:*\n"
            "LISTEN 0 128 0.0.0.0:1234 127.0.0.1:*\n"
        )
        summary = AUDIT.summarize_ss(fixture)
        self.assertEqual(summary["count"], 4)
        self.assertEqual(summary["bind_scopes"], {
            "wildcard": 1,
            "loopback": 2,
            "interface_specific": 1,
            "unknown": 0,
        })
        self.assertNotIn("192.0.2.42", json.dumps(summary))
        self.assertNotIn("8443", json.dumps(summary))

    def test_local_field_malformed_stays_unknown_even_if_peer_is_wildcard(self):
        summary = AUDIT.summarize_ss(
            "LISTEN 0 128 not-an-address 0.0.0.0:*\n"
        )
        self.assertEqual(summary["bind_scopes"], {
            "wildcard": 0,
            "loopback": 0,
            "interface_specific": 0,
            "unknown": 1,
        })

    def test_unknown_malformed_line_never_defaults_to_wildcard(self):
        data = AUDIT.summarize_ss("unexpected malformed row\n")
        self.assertEqual(data["bind_scopes"]["unknown"], 1)
        self.assertEqual(data["bind_scopes"]["wildcard"], 0)

    def test_aggregate_unknown_reasons_no_local_metadata(self):
        # This fixture intentionally includes an unparseable local token that
        # looks like a private hostname, and a malformed short ss record.
        fixture = (
            "UNCONN 0 0 private-host.example:5353 0.0.0.0:*\n"
            "UNCONN 0 0 127.0.0.1:5353 0.0.0.0:*\n"
            "broken row\n"
        )
        data = AUDIT.summarize_ss(fixture)
        self.assertEqual(data["count"], 3)
        self.assertEqual(data["bind_scopes"]["unknown"], 2)
        self.assertEqual(data["bind_scopes"]["loopback"], 1)
        self.assertEqual(data["unknown_reasons"], {
            "malformed_row": 1,
            "unparsed_local_endpoint": 1,
        })
        self.assertEqual(
            sum(data["unknown_reasons"].values()),
            data["bind_scopes"]["unknown"],
        )
        self.assertNotIn("private-host.example", json.dumps(data))
        self.assertNotIn("5353", json.dumps(data))

    def test_no_unknown_reasons_when_all_local_fields_are_valid(self):
        data = AUDIT.summarize_ss(
            "LISTEN 0 128 0.0.0.0:80 0.0.0.0:*\n"
            "UNCONN 0 0 [::1]:53 [::]:*\n"
        )
        self.assertEqual(data["unknown_reasons"], {
            "malformed_row": 0,
            "unparsed_local_endpoint": 0,
        })
        self.assertEqual(data["bind_scopes"]["unknown"], 0)

    def test_fixed_local_ss_args_no_privileges_or_docker(self):
        self.assertEqual(
            AUDIT.COMMANDS,
            {
                "tcp": ("/usr/bin/ss", "-H", "-lnt"),
                "udp": ("/usr/bin/ss", "-H", "-lnu"),
            },
        )
        script = SOURCE.read_text()
        for disallowed in (
            "sudo ", "shell=True", "docker.sock", "socket.connect",
            "subprocess.Popen", "ss -p", "write_text(", "write_bytes(",
            "chmod(", "ip addr", "os.environ", "subprocess.call",
        ):
            self.assertNotIn(disallowed, script)

    def test_capture_only_and_fixed_args(self):
        calls = []
        def executor(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        with mock.patch.object(AUDIT.Path, "is_file", return_value=True):
            result = AUDIT.probe("tcp", executor=executor)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(calls), 1)
        argv, opts = calls[0]
        self.assertEqual(argv, AUDIT.COMMANDS["tcp"])
        self.assertTrue(opts["capture_output"])
        self.assertFalse(opts["check"])
        self.assertEqual(opts["input"], "")
        self.assertLessEqual(opts["timeout"], 4)

    def test_failure_or_oversize_never_leaks(self):
        denied = subprocess.CompletedProcess(
            [], 1, stdout="192.0.2.22:6543", stderr="permission denied"
        )
        huge = subprocess.CompletedProcess(
            [], 0, stdout="x" * (AUDIT.MAX_BYTES + 1), stderr=""
        )
        with mock.patch.object(AUDIT.Path, "is_file", return_value=True):
            a = AUDIT.probe("tcp", executor=lambda *args, **kw: denied)
            b = AUDIT.probe("udp", executor=lambda *args, **kw: huge)
        self.assertEqual(a, {"status": "access_denied", "summary": None})
        self.assertEqual(b, {"status": "error", "summary": None})
        self.assertNotIn("192.0.2.22", json.dumps(a))

    def test_json_response_keeps_reachability_unverified(self):
        fixture = {
            "schema": AUDIT.SCHEMA,
            "tcp": {"status": "ok", "summary": {"count": 2, "bind_scopes": {}}},
            "udp": {"status": "missing", "summary": None},
            "effective_reachability": "not_verified",
            "docker_socket_queried": False,
            "limitations": [],
        }
        with mock.patch.object(AUDIT, "inspect", return_value=fixture):
            with mock.patch("sys.argv", ["listeners", "--format", "json"]):
                out = io.StringIO()
                with redirect_stdout(out):
                    AUDIT.main()
        self.assertEqual(json.loads(out.getvalue()), fixture)

    def test_ansible_wrapper_local_no_sudo_and_no_raw_printing(self):
        plays = yaml.safe_load(PLAYBOOK.read_text())
        self.assertEqual(len(plays), 1)
        play = plays[0]
        self.assertIs(play["become"], False)
        self.assertEqual(play["hosts"], "localhost")
        self.assertEqual(play["connection"], "local")
        self.assertIs(play["gather_facts"], False)
        self.assertEqual(
            play["vars"]["ansible_python_interpreter"],
            "{{ ansible_playbook_python }}",
        )
        tasks = play["tasks"]
        self.assertEqual(len(tasks), 2)
        self.assertEqual(
            tasks[0]["ansible.builtin.command"]["argv"],
            [
                "{{ ansible_playbook_python }}", "-B",
                "{{ playbook_dir }}/../scripts/audit-workstation-listeners.py",
                "--format", "json",
            ],
        )
        self.assertIs(tasks[0]["changed_when"], False)
        self.assertIs(tasks[0]["no_log"], True)
        self.assertEqual(
            tasks[1]["ansible.builtin.debug"]["msg"],
            "{{ audit_listener_result.stdout | from_json }}",
        )


if __name__ == "__main__":
    unittest.main()
