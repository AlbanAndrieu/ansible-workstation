"""Offline contract: only private allowlisted, bounded TCP measurements."""
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/measure-workstation-reachability.py"
SPEC = importlib.util.spec_from_file_location("workstation_path_measure", SOURCE)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def target(observer, address, port, expected):
    return {
        "observer": observer,
        "address": address,
        "port": port,
        "expected": expected,
    }


class WorkstationReachabilityContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private-allowlist.json"

    def save(self, targets, mode=0o600):
        self.path.write_text(json.dumps({
            "schema": AUDIT.MANIFEST_SCHEMA, "targets": targets
        }))
        self.path.chmod(mode)

    def read(self, observer):
        return AUDIT.read_manifest(str(self.path), observer, repo_root=ROOT)

    def test_valid_private_local_lan_and_wan_allowlist(self):
        self.save([
            target("local", "127.0.0.1", 1234, "allow"),
            target("lan", "172.17.0.57", 2345, "deny"),
            target("lan", "fd00::123", 2346, "allow"),
            target("wan", "1.1.1.1", 1234, "deny"),
        ])
        selected = self.read("lan")
        self.assertEqual(len(selected), 2)
        self.assertEqual([x[2] for x in selected], ["deny", "allow"])
        self.assertIsInstance(selected[0][0], ipaddress.IPv4Address)

    def test_no_files_inside_repository_or_symlinks(self):
        self.save([target("local", "127.0.0.1", 8080, "allow")])
        inside = self.temp.name  # Pretend checkout root equals enclosing dir.
        with self.assertRaisesRegex(AUDIT.InvalidManifest, "outside"):
            AUDIT.read_manifest(self.path, "local", repo_root=inside)
        symlink = Path(self.temp.name) / "link.json"
        symlink.symlink_to(self.path)
        with self.assertRaisesRegex(AUDIT.InvalidManifest, "symlink"):
            AUDIT.read_manifest(symlink, "local")

    def test_enforce_private_permissions(self):
        self.save([target("local", "127.0.0.1", 8080, "allow")], mode=0o644)
        with self.assertRaisesRegex(AUDIT.InvalidManifest, "group or others"):
            self.read("local")

    def test_scope_limited_no_wildcards_dns_multicast_or_public_lan(self):
        for bad in ("0.0.0.0", "example.com", "224.0.0.1",
                    "1.1.1.1", "169.254.1.9", "127.0.0.1"):
            with self.subTest(ip=bad):
                self.save([target("lan", bad, 443, "allow")])
                with self.assertRaises(AUDIT.InvalidManifest):
                    self.read("lan")
        self.save([target("wan", "172.17.0.57", 443, "allow")])
        with self.assertRaises(AUDIT.InvalidManifest):
            self.read("wan")

    def test_no_unbounded_multi_target_scan(self):
        self.save([
            target("lan", f"192.168.10.{i}", 8000+i, "deny")
            for i in range(1, AUDIT.MAX_TARGETS + 2)
        ])
        with self.assertRaisesRegex(AUDIT.InvalidManifest, "bound"):
            self.read("lan")

    def test_port_duplicate_and_boolean_protection(self):
        self.save([target("local", "127.0.0.1", True, "allow")])
        with self.assertRaisesRegex(AUDIT.InvalidManifest, "port"):
            self.read("local")
        item = target("lan", "172.17.0.57", 2345, "deny")
        self.save([item, item])
        with self.assertRaisesRegex(AUDIT.InvalidManifest, "duplicate"):
            self.read("lan")

    def test_dry_run_never_opens_a_socket(self):
        targets = [(ipaddress.ip_address("127.0.0.1"), 9999, "allow")]
        with mock.patch.object(AUDIT, "try_tcp", side_effect=AssertionError):
            output = AUDIT.summarize(targets, "local", active=False)
        self.assertIs(output["measurement_performed"], False)
        self.assertEqual(output["attempts"], 0)
        self.assertEqual(output["overall_reachability"], "not_verified")
        self.assertIs(output["observer_independence_verified"], False)

    def test_fail_closed_results_and_no_endpoint_leak(self):
        targets = [
            (ipaddress.ip_address("172.17.0.57"), 20501, "deny"),
            (ipaddress.ip_address("172.17.0.58"), 20502, "allow"),
            (ipaddress.ip_address("172.17.0.59"), 20503, "deny"),
            (ipaddress.ip_address("172.17.0.60"), 20504, "allow"),
            (ipaddress.ip_address("172.17.0.61"), 20505, "deny"),
        ]
        observations = iter([
            "connected", "refused", "refused", "timed_out", "unreachable"
        ])
        outcome = AUDIT.summarize(
            targets, "lan", active=True,
            connector=lambda *args: next(observations),
        )
        self.assertEqual(outcome["attempts"], 5)
        self.assertEqual(outcome["outcomes"], {
            "expected_allowed": 0, "expected_denied": 1,
            "unexpected_open": 1, "unexpected_closed": 1,
            "inconclusive": 2,
        })
        self.assertEqual(outcome["overall_reachability"], "unexpected_open")
        summary = json.dumps(outcome)
        for secret in ("172.17.0.", "20501", "20502", "20503", "20504", "20505"):
            self.assertNotIn(secret, summary)

    def test_tcp_handshake_no_shell_dns_or_privilege(self):
        source = SOURCE.read_text()
        for forbidden in (
            "subprocess.", "shell=True", "os.system(", "getaddrinfo(",
            "gethostbyname(", "socket.AF_PACKET", "sudo -", "docker.sock",
            "write_text(", "write_bytes(", "mkdir(",
        ):
            self.assertNotIn(forbidden, source)
        self.assertEqual(AUDIT.MAX_TARGETS, 12)
        self.assertLessEqual(AUDIT.TIMEOUT_SECONDS, 2)

    def test_wan_run_is_explicitly_self_declared(self):
        self.save([target("wan", "1.1.1.1", 443, "deny")])
        report = AUDIT.summarize(self.read("wan"), "wan", active=False)
        self.assertEqual(report["observer_claimed"], "wan")
        self.assertIs(report["observer_independence_verified"], False)
        self.assertEqual(report["attempts"], 0)

    def test_missing_observer_scope_is_rejected(self):
        self.save([target("local", "::1", 80, "allow")])
        with self.assertRaisesRegex(AUDIT.InvalidManifest, "no allowlisted"):
            self.read("lan")


if __name__ == "__main__":
    unittest.main()
