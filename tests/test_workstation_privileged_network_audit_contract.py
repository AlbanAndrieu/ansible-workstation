"""Offline contracts: only immutable system reads may use elevated privileges."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/audit-workstation-network-privileged.py"
SPEC = importlib.util.spec_from_file_location("privileged_network_audit", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrivilegedNetworkAuditContract(unittest.TestCase):
    def test_no_writable_script_or_docker_command_can_run_as_root(self):
        self.assertEqual(MODULE.SUDO, "/usr/bin/sudo")
        source = SOURCE.read_text()
        for forbidden in (
            "shell=True", "Popen(", "os.system(", "os.exec", "os.seteuid",
            "sudoers.d", "docker.sock", "write_text(", "write_bytes(",
            "chmod(", "chown(", "systemctl", "nft add", "nft flush",
            "iptables -A", "iptables -P", "sudo -S", "sudo -i", "sudo su",
        ):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertEqual(
            set(MODULE.NETWORK.COMMANDS), {"nft", "iptables", "ip6tables"},
        )

    def test_exact_root_commands_and_no_raw_stdout(self):
        calls = []
        def stub(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="sensitive", stderr="")
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=1000),
            mock.patch.object(MODULE.Path, "is_file", return_value=True),
        ):
            for name in MODULE.NETWORK.COMMANDS:
                status, value = MODULE.privileged_probe(name, executor=stub)
                self.assertEqual((status, value), ("ok", "sensitive"))
        self.assertEqual(len(calls), 3)
        for (argv, opts), command in zip(calls, MODULE.NETWORK.COMMANDS.values()):
            self.assertEqual(argv, ["/usr/bin/sudo", "-n", "--", *command])
            self.assertIs(opts["capture_output"], True)
            self.assertIs(opts["check"], False)
            self.assertEqual(opts["input"], "")
            self.assertLessEqual(opts["timeout"], 5)
            self.assertNotIn("HOME", opts["env"])
            self.assertFalse(any("scripts/" in arg for arg in argv))

    def test_unknown_probe_is_refused_before_subprocess(self):
        with self.assertRaisesRegex(ValueError, "unapproved"):
            MODULE.privileged_probe("../arbitrary-script", executor=mock.Mock())

    def test_python_cannot_be_started_as_root(self):
        with mock.patch.object(MODULE.os, "geteuid", return_value=0):
            self.assertEqual(
                MODULE.privileged_probe("nft", executor=mock.Mock()), ("error", "")
            )

    def test_noninteractive_sudo_denial_is_unknown_not_empty_filter(self):
        response = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="secret-private-address",
            stderr="sudo: a password is required",
        )
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=1000),
            mock.patch.object(MODULE.Path, "is_file", return_value=True),
        ):
            self.assertEqual(
                MODULE.privileged_probe("nft", executor=lambda *a, **k: response),
                ("access_denied", ""),
            )

    def test_malformed_sudo_error_is_never_exposed(self):
        response = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="private-secret",
            stderr="username and serial / 192.0.2.1",
        )
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=1000),
            mock.patch.object(MODULE.Path, "is_file", return_value=True),
        ):
            self.assertEqual(
                MODULE.privileged_probe("iptables", executor=lambda *a, **k: response),
                ("error", ""),
            )

    def test_large_output_and_timeout_fail_closed(self):
        oversized = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="x" * (MODULE.MAX_RAW_BYTES + 1),
            stderr="",
        )
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=1000),
            mock.patch.object(MODULE.Path, "is_file", return_value=True),
        ):
            self.assertEqual(
                MODULE.privileged_probe("ip6tables", executor=lambda *a, **k: oversized),
                ("error", ""),
            )
            def timeout(*args, **kwargs):
                raise subprocess.TimeoutExpired("read", 5)
            self.assertEqual(
                MODULE.privileged_probe("nft", executor=timeout),
                ("timed_out", ""),
            )

    def test_cli_needs_explicit_acknowledgment(self):
        with mock.patch("sys.argv", ["audit"]):
            with self.assertRaises(SystemExit) as out:
                MODULE.main()
        self.assertEqual(out.exception.code, 2)

    def test_aggregated_output_keeps_effective_filtering_unverified(self):
        raw = json.dumps({"nftables": [
            {"chain": {"family": "inet", "type": "filter", "hook": "input",
                       "name": "secret-name", "policy": "drop"}},
            {"rule": {"comment": "VERY_PRIVATE", "source": "192.0.2.5"}},
        ]})
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=1000),
            mock.patch.object(MODULE.NETWORK, "forwarding_state", return_value="enabled"),
            mock.patch.object(MODULE, "privileged_probe",
                              side_effect=lambda name: ("ok", raw) if name == "nft"
                              else ("access_denied", "")),
        ):
            data = MODULE.NETWORK.inspect(probe=MODULE.privileged_probe)
        self.assertEqual(data["effective_filtering"], "not_verified")
        self.assertEqual(data["firewall_probes"]["nft"]["status"], "ok")
        self.assertNotIn("VERY_PRIVATE", json.dumps(data))
        self.assertNotIn("192.0.2.5", json.dumps(data))
        self.assertNotIn("secret-name", json.dumps(data))


if __name__ == "__main__":
    unittest.main()
