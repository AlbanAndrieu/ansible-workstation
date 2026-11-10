"""Offline contracts for scripts/audit_common.py and the scripts that load it.

The per-script forbidden-token tests only read each script's own source, so
the shared runner gets the union of those tokens here. No command, sudo,
socket or Docker access: every execution uses a stub executor.
"""

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
COMMON_PATH = ROOT / "scripts/audit_common.py"
SPEC = importlib.util.spec_from_file_location("audit_common", COMMON_PATH)
COMMON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMMON)

# Scripts that execute fixed commands must do it through run_fixed only.
RUNNERS = (
    "audit-openclaw-source.py",
    "audit-workstation-configuration.py",
    "audit-workstation-listeners.py",
    "audit-workstation-network.py",
    "audit-workstation-network-privileged.py",
    "measure-workstation-docker-publishing.py",
)


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


class SharedRunnerSource(unittest.TestCase):
    def test_no_shell_write_privilege_or_socket_primitive(self):
        source = COMMON_PATH.read_text()
        for token in (
            "shell=True",
            "Popen",
            "os.system",
            "os.exec",
            "os.environ",
            "seteuid",
            "setuid",
            "/usr/bin/sudo",
            '"sudo"',
            "import socket",
            "socket.",
            "docker.sock",
            "write_text(",
            "write_bytes(",
            "open(",
            "chmod(",
            "chown(",
            "mkdir(",
            "unlink(",
            "sys.path",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_scripts_load_runner_by_path_and_never_spawn_directly(self):
        for name in RUNNERS:
            source = (ROOT / "scripts" / name).read_text()
            with self.subTest(script=name):
                self.assertIn('with_name("audit_common.py")', source)
                for token in ("import subprocess", "subprocess.", "sys.path"):
                    self.assertFalse(token in source, f"{name}: {token}")

    def test_reachability_stays_free_of_any_command_runner(self):
        source = (ROOT / "scripts/measure-workstation-reachability.py").read_text()
        for token in ("audit_common", "import subprocess", "subprocess."):
            self.assertFalse(token in source, token)


class RunFixed(unittest.TestCase):
    def run_with(self, response, **kwargs):
        calls = []

        def executor(argv, **opts):
            calls.append((argv, opts))
            if isinstance(response, BaseException):
                raise response
            return response

        with mock.patch.object(COMMON.Path, "is_file", return_value=True):
            result = COMMON.run_fixed(
                ("/usr/bin/tool", "--flag"),
                timeout=3,
                max_bytes=16,
                executor=executor,
                **kwargs,
            )
        return result, calls

    def test_fixed_call_options(self):
        result, calls = self.run_with(completed(stdout="fine"))
        self.assertEqual(result, ("ok", "fine"))
        argv, opts = calls[0]
        self.assertEqual(argv, ("/usr/bin/tool", "--flag"))
        self.assertEqual(opts["input"], "")
        self.assertIs(opts["capture_output"], True)
        self.assertIs(opts["check"], False)
        self.assertEqual(opts["timeout"], 3)
        self.assertEqual(opts["env"], COMMON.FIXED_ENV)
        self.assertNotIn("HOME", opts["env"])

    def test_inherited_environment_only_when_requested(self):
        _, calls = self.run_with(completed(stdout="x"), env=None)
        self.assertIsNone(calls[0][1]["env"])

    def test_oversize_is_refused_not_truncated(self):
        result, _ = self.run_with(completed(stdout="x" * 17))
        self.assertEqual(result, ("oversize", ""))

    def test_failures_never_return_output_or_stderr(self):
        cases = {
            "access_denied": completed(1, "private-rule", "Permission denied"),
            "failed": completed(2, "private-rule", "unexpected private-detail"),
            "timed_out": subprocess.TimeoutExpired("tool", 3),
            "error": OSError("private-detail"),
        }
        for status, response in cases.items():
            with self.subTest(status=status):
                result, _ = self.run_with(response)
                self.assertEqual(result, (status, ""))

    def test_missing_absolute_binary_is_not_executed(self):
        executor = mock.Mock()
        with mock.patch.object(COMMON.Path, "is_file", return_value=False):
            result = COMMON.run_fixed(
                ("/usr/bin/absent",),
                timeout=1,
                max_bytes=1,
                executor=executor,
            )
        self.assertEqual(result, ("missing", ""))
        executor.assert_not_called()

    def test_public_status_collapses_internal_states(self):
        for status in ("failed", "oversize", "error", "anything"):
            self.assertEqual(COMMON.public_status(status), "error")
        for status in ("ok", "missing", "timed_out", "access_denied"):
            self.assertEqual(COMMON.public_status(status), status)


class BindScope(unittest.TestCase):
    def test_scopes(self):
        cases = {
            "0.0.0.0": "wildcard",  # nosec B104 - parser fixture
            "::": "wildcard",
            "::ffff:0.0.0.0": "wildcard",
            "127.0.0.1": "loopback",
            "::1": "loopback",
            "::ffff:127.0.0.1": "loopback",
            "192.0.2.10": "interface_specific",
            "2001:db8::1": "interface_specific",
        }
        for address, scope in cases.items():
            with self.subTest(address=address):
                self.assertEqual(COMMON.bind_scope(address), scope)

    def test_invalid_address_raises(self):
        with self.assertRaises(ValueError):
            COMMON.bind_scope("not-an-ip")


class NetworkProbeSizing(unittest.TestCase):
    def test_network_probe_refuses_oversized_ruleset(self):
        spec = importlib.util.spec_from_file_location(
            "network_audit",
            ROOT / "scripts/audit-workstation-network.py",
        )
        network = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(network)
        big = completed(stdout="-A INPUT -j ACCEPT\n" * 70000)
        with (
            mock.patch.object(network.common.Path, "is_file", return_value=True),
            mock.patch.object(network.common.subprocess, "run", return_value=big),
        ):
            self.assertEqual(network.run_probe("iptables"), ("error", ""))


if __name__ == "__main__":
    unittest.main()
