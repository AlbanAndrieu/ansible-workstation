"""Offline-only Docker metadata contracts; daemon is never contacted."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/measure-workstation-docker-publishing.py"
SPEC = importlib.util.spec_from_file_location("workstation_docker_publications", SOURCE)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class DockerPublicationsContract(unittest.TestCase):
    def test_docker_command_is_fixed_and_read_only(self):
        self.assertEqual(AUDIT.ARGV, (
            "/usr/bin/docker", "--host", "unix:///var/run/docker.sock",
            "container", "ls", "--format", "{{json .Ports}}",
        ))
        self.assertFalse(any(x in AUDIT.ARGV for x in
            ("run", "exec", "start", "stop", "inspect", "build", "rm")))
        source = SOURCE.read_text()
        for forbidden in ("sudo -", "shell=True", "write_text(",
                          "chmod(", "chown(", "groupadd", "usermod",
                          "docker.sock\", \"r", "subprocess.Popen"):
            self.assertNotIn(forbidden, source)

    def test_published_bind_scope_aggregates_only(self):
        output = "\n".join(json.dumps(x) for x in [
            "0.0.0.0:8080->80/tcp, [::]:8080->80/tcp",
            "127.0.0.1:3000->3000/tcp, 192.0.2.1:443->443/udp",
            "8000/tcp, 9000-9002/tcp",
            "",
        ])
        summary = AUDIT.summarize(output)
        self.assertEqual(summary["running_containers_reported"], 4)
        self.assertEqual(summary["published_binding_segments"], 4)
        self.assertEqual(summary["exposed_only_segments"], 2)
        self.assertEqual(summary["published_bindings"]["ipv4"]["tcp"]["wildcard"], 1)
        self.assertEqual(summary["published_bindings"]["ipv6"]["tcp"]["wildcard"], 1)
        self.assertEqual(summary["published_bindings"]["ipv4"]["tcp"]["loopback"], 1)
        self.assertEqual(summary["published_bindings"]["ipv4"]["udp"]["interface_specific"], 1)
        for secret in ("8080", "192.0.2.1", "3000", "443", "9000"):
            self.assertNotIn(secret, json.dumps(summary))

    def test_unknown_mapping_is_not_claimed_as_secure(self):
        result = AUDIT.summarize(
            json.dumps("192.0.2.1:bad->80/tcp") + "\n"
        )
        self.assertEqual(result["published_bindings"]["unknown"]["tcp"]["unknown"], 1)

    def test_invalid_json_fails_closed(self):
        self.assertIsNone(AUDIT.summarize("{bad"))
        self.assertIsNone(AUDIT.summarize(json.dumps({"Ports": "80/tcp"})))

    def test_root_is_refused_without_accessing_daemon(self):
        with mock.patch.object(AUDIT.os, "geteuid", return_value=0):
            data = AUDIT.inspect(executor=mock.Mock())
        self.assertEqual(data["status"], "refused_root")
        self.assertIsNone(data["summary"])

    def test_capture_only_fixed_docker_local_host(self):
        calls = []
        def executor(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(""), stderr="")
        with (
            mock.patch.object(AUDIT.os, "geteuid", return_value=1000),
            mock.patch.object(AUDIT.Path, "is_file", return_value=True),
        ):
            data = AUDIT.inspect(executor=executor)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["summary"]["running_containers_reported"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], AUDIT.ARGV)
        self.assertTrue(calls[0][1]["capture_output"])
        self.assertLessEqual(calls[0][1]["timeout"], 6)
        self.assertNotIn("DOCKER_HOST", calls[0][1]["env"])

    def test_permission_errors_are_sanitized(self):
        def denied(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 1, stdout="192.0.2.1:9999",
                stderr="permission denied for name secret token",
            )
        with (
            mock.patch.object(AUDIT.os, "geteuid", return_value=1000),
            mock.patch.object(AUDIT.Path, "is_file", return_value=True),
        ):
            data = AUDIT.inspect(executor=denied)
        self.assertEqual(data["status"], "access_denied")
        self.assertIsNone(data["summary"])
        self.assertNotIn("secret", json.dumps(data))
        self.assertEqual(data["effective_reachability"], "not_verified")

    def test_explicit_ack_required(self):
        with self.assertRaises(SystemExit) as context:
            AUDIT.main([])
        self.assertEqual(context.exception.code, 2)

    def test_ranges_are_segments_not_individual_ports(self):
        summary = AUDIT.summarize(json.dumps(
            "0.0.0.0:2000-2020->3000-3020/tcp"
        ))
        self.assertEqual(summary["published_binding_segments"], 1)
        self.assertIn("segments", summary["count_unit"])


if __name__ == "__main__":
    unittest.main()
