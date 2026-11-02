"""Hermetic split-DNS recovery contracts: no host access or sudo is executed."""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/homelab-split-dns.py"
spec = importlib.util.spec_from_file_location("homelab_split_dns", SCRIPT)
assert spec and spec.loader
dns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dns)


def good_profile() -> dict[str, str]:
    return {
        "name": "Wired eno1",
        "device_dns": "172.17.0.1",
        "profile_dns": "172.17.0.1",
        "profile_auto": "yes",
        "profile_domains": "~int.albandrieu.com,example.net",
        "link_dns": "Link 2 (eno1): 172.17.0.1",
        "link_domains": "Link 2 (eno1): ~int.albandrieu.com",
    }


def good_state() -> dict[str, str]:
    return {
        "udp": "A_CONFIRMED",
        "tcp": "A_CONFIRMED",
        "udp_sec": "0.1",
        "tcp_sec": "0.1",
        "nss": "A_CONFIRMED",
        "nss_sec": "0.2",
        "hide-location.timer": "disabled",
        "hide-location.service": "disabled",
    }


class HomelabSplitDNSRecoveryTest(unittest.TestCase):
    def test_all_layers_verified(self):
        self.assertEqual(dns.verdict(good_profile(), good_state()), "PASS")

    def test_missing_nm_domain_is_not_hidden_by_transient_resolvectl(self):
        cfg = good_profile()
        cfg["profile_domains"] = "example.net"
        self.assertEqual(dns.verdict(cfg, good_state()), "PRIVATE_ROUTE_NOT_PERSISTED")

    def test_udp_timeout_is_not_hidden_by_cached_nss_or_tcp_success(self):
        state = good_state()
        state["udp"] = "NO_RESPONSE"
        self.assertEqual(dns.verdict(good_profile(), state), "PFSENSE_UDP53_UNVERIFIED")

    def test_tcp_failure_is_distinct_from_udp_failure(self):
        state = good_state()
        state["tcp"] = "NO_RESPONSE"
        self.assertEqual(dns.verdict(good_profile(), state), "PFSENSE_TCP53_UNVERIFIED")

    def test_unresolved_client_is_failure(self):
        state = good_state()
        state["nss"] = "UNRESOLVED"
        self.assertEqual(
            dns.verdict(good_profile(), state),
            "CLIENT_PRIVATE_SPLIT_DNS_PATH",
        )

    def test_quad9_drift_is_not_masked_by_pf_dns(self):
        cfg = good_profile()
        cfg["link_dns"] = "Link 2 (eno1): 9.9.9.9 149.112.112.112"
        self.assertEqual(dns.verdict(cfg, good_state()), "RESOLVED_LINK_DNS_DRIFT")

    def test_active_legacy_timer_is_failure(self):
        state = good_state()
        state["hide-location.timer"] = "enabled"
        self.assertEqual(
            dns.verdict(good_profile(), state),
            "LEGACY_DNS_OVERRIDE_ENABLED",
        )

    def test_repair_refuses_upstream_udp_timeout_without_any_mutations(self):
        state = good_state()
        state["udp"] = "NO_RESPONSE"
        with (
            mock.patch.object(dns, "call") as calls,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(dns.apply(good_profile(), state), 2)
            calls.assert_not_called()

    def test_repair_refuses_unknown_interface_and_profile(self):
        cfg = good_profile()
        cfg["name"] = "VPN profile"
        with (
            mock.patch.object(dns, "call") as calls,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(dns.apply(cfg, good_state()), 2)
            calls.assert_not_called()

    def test_repair_only_changes_local_nm_and_legacy_timer(self):
        cfg = good_profile()
        cfg["profile_domains"] = "example.net"
        state = good_state()
        state["hide-location.timer"] = "enabled"
        actions = []

        def fake_call(argv, timeout=5):
            actions.append(list(argv))
            return True, "", 0.01

        with mock.patch.object(dns, "call", side_effect=fake_call):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(dns.apply(cfg, state), 0)
        self.assertEqual(
            actions,
            [
                [
                    "systemctl",
                    "--user",
                    "disable",
                    "--now",
                    "hide-location.timer",
                    "hide-location.service",
                ],
                [
                    "sudo",
                    "nmcli",
                    "connection",
                    "modify",
                    "Wired eno1",
                    "+ipv4.dns-search",
                    "~int.albandrieu.com",
                ],
                ["sudo", "nmcli", "device", "reapply", "eno1"],
                ["sudo", "resolvectl", "flush-caches"],
            ],
        )
        self.assertFalse(
            any(
                action[:2] == ["sudo", "resolvectl"] and "dns" in action
                for action in actions
            ),
        )

    def test_repair_does_not_duplicate_existing_search_route(self):
        actions = []
        with mock.patch.object(
            dns,
            "call",
            side_effect=lambda argv, timeout=5: (
                actions.append(argv) or True,
                "",
                0.01,
            ),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(dns.apply(good_profile(), good_state()), 0)
        self.assertEqual(
            actions,
            [
                ["sudo", "nmcli", "device", "reapply", "eno1"],
                ["sudo", "resolvectl", "flush-caches"],
            ],
        )

    def test_slow_nss_is_warned_without_misclassifying_upstream(self):
        state = good_state()
        state["nss_sec"] = "11.5"
        with contextlib.redirect_stdout(io.StringIO()) as out:
            dns.display(good_profile(), state, dns.verdict(good_profile(), state))
        self.assertIn("diagnosis=PASS", out.getvalue())
        self.assertIn("WARN: NSS query slow", out.getvalue())

    def test_check_mode_calls_no_mutation(self):
        import sys

        with mock.patch.object(sys, "argv", [str(SCRIPT), "--check"]):
            with mock.patch.object(
                dns,
                "read",
                return_value=(good_profile(), good_state()),
            ):
                with mock.patch.object(dns, "apply") as repair:
                    with contextlib.redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(dns.main(), 0)
                    repair.assert_not_called()
                    self.assertIn("diagnosis=PASS", output.getvalue())

    def test_cli_apply_requires_exact_ack_before_any_probe(self):
        import sys

        with mock.patch.object(sys, "argv", [str(SCRIPT), "--apply"]):
            with mock.patch.object(dns, "read") as read:
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        dns.main()
                self.assertEqual(error.exception.code, 2)
                read.assert_not_called()

    def test_dig_distinguishes_udp_timeout_and_tcp_success(self):
        def fake_call(argv, timeout=5):
            if "+tcp" in argv:
                return True, "172.17.0.24\n", 0.2
            return False, "", 3.0

        with mock.patch.object(dns, "call", side_effect=fake_call):
            self.assertEqual(dns.dig(False), ("NO_RESPONSE", 3.0))
            self.assertEqual(dns.dig(True), ("A_CONFIRMED", 0.2))

    def test_readonly_contract_does_not_edit_configuration(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "resolv.conf.d/base",
            "resolv.conf.d/head",
            "nmcli device disconnect",
            "nmcli connection up",
            "systemctl restart systemd-resolved",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
