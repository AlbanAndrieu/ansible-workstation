"""Hermetic workstation Wi-Fi/DNS path diagnosis tests: no network required."""

import contextlib
import importlib.util
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/diagnose-wifi-path.py"
spec = importlib.util.spec_from_file_location("nabla_wifi_path", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(
    *,
    wifi=False,
    wifi_connected=True,
    pf_dns=True,
    public_dns=True,
    system_dns=True,
    private_sys=True,
    active="172.17.0.1",
    dhcp="172.17.0.1",
    profile_dns="172.17.0.1",
    ignore_auto="yes",
    lease_override=None,
    device_dns="172.17.0.1",
    private_pf=True,
):
    calls = []
    interface = "wlp2s0" if wifi else "eno1"

    def runner(args):
        args = tuple(args)
        calls.append(args)
        if args[:4] == ("ip", "-4", "route", "get"):
            return True, f"1.1.1.1 via 172.17.0.1 dev {interface} src 172.17.0.57"
        if args[0] == "nmcli":
            if "GENERAL.TYPE" in args:
                return True, "wifi" if wifi else "ethernet"
            if "DHCP4.OPTION" in args:
                return True, lease_override or (
                    "DHCP4.OPTION[3]: dhcp_server_identifier = 172.17.0.1\n"
                    f"DHCP4.OPTION[5]: domain_name_servers = {dhcp}\n"
                    "DHCP4.OPTION[6]: ip_address = 172.17.0.57\n"
                    "DHCP4.OPTION[7]: subnet_mask = 255.255.255.0"
                )
            if "IP4.DNS" in args:
                return True, device_dns
            if "GENERAL.CONNECTION" in args:
                return True, "Wired eno1"
            if "ipv4.dns,ipv4.ignore-auto-dns" in args:
                return True, (
                    f"ipv4.dns: {profile_dns}\nipv4.ignore-auto-dns: {ignore_auto}"
                )
        if args[0] == "resolvectl":
            return True, f"Link 2 ({interface}): {active}"
        if args[0] == "iw":
            return True, (
                "Connected to 02:01:02:03:04:05 (on wlp2s0)\n"
                "\tSSID: VERY_PRIVATE_WIFI_NAME\n\tsignal: -63 dBm\n\tfreq: 5180\n"
                if wifi_connected
                else "Not connected.\n"
            )
        if args[0] == "dig":
            dns = next((a[1:] for a in args if a.startswith("@")), None)
            name = args[-2]
            if name.endswith(".int.albandrieu.com"):
                return True, "172.17.0.24" if private_pf else ""
            if dns == "172.17.0.1":
                return pf_dns, "93.184.215.14" if pf_dns else ""
            if dns == "9.9.9.9":
                return public_dns, "93.184.215.14" if public_dns else ""
        if args[0] == "getent":
            if args[-1] == "sample.int.albandrieu.com":
                return private_sys, (
                    "172.17.0.24 STREAM sample.int.albandrieu.com"
                    if private_sys
                    else ""
                )
            return system_dns, "93.184.215.14 STREAM example.org" if system_dns else ""
        return False, ""

    return runner, calls


class WifiPathTest(unittest.TestCase):
    def test_wired_vantage_cannot_certify_phone_wifi(self):
        runner, calls = fixture()
        data = module.snapshot(runner=runner, connect=lambda *_: True)
        self.assertEqual(data["diagnosis"], "NO_FAILURE_DURING_SAMPLE")
        self.assertEqual(data["vantage"], "wired_or_unknown")
        self.assertTrue(data["wifi_client_not_tested"])
        self.assertEqual(data["wifi_radio"], "NOT_OBSERVED")
        self.assertFalse(any(command[0] == "iw" for command in calls))

    def test_confirmed_wifi_radio_disconnected(self):
        runner, _ = fixture(wifi=True, wifi_connected=False)
        data = module.snapshot(runner=runner, connect=lambda *_: True)
        self.assertEqual(data["diagnosis"], "WIFI_ASSOCIATION_LOST")
        self.assertEqual(data["wifi_radio"], "DISCONNECTED")

    def test_wifi_link_signal_suppresses_ssid_and_bssid(self):
        runner, _ = fixture(wifi=True)
        data = module.snapshot(runner=runner, connect=lambda *_: True)
        self.assertEqual(data["wifi_radio"], "ASSOCIATED")
        self.assertEqual(data["wifi_signal_dbm"], -63)
        self.assertEqual(data["wifi_frequency_mhz"], 5180)
        text = str(data)
        self.assertNotIn("VERY_PRIVATE_WIFI_NAME", text)
        self.assertNotIn("02:01:02:03:04:05", text)

    def test_control_dns_works_but_pfsense_dns_fails_with_ip_reachability(self):
        runner, _ = fixture(pf_dns=False)
        data = module.snapshot(
            runner=runner,
            connect=lambda host, port: host == "1.1.1.1",
        )
        self.assertEqual(data["diagnosis"], "PFSENSE_DNS_OR_WIFI_VLAN_POLICY")
        self.assertFalse(data["pfsense_dns_public"])
        self.assertTrue(data["control_dns_public"])
        self.assertTrue(data["external_tcp443"])
        self.assertFalse(data["pfsense_tcp53"])

    def test_dhcp_dns_and_active_dns_are_distinguished(self):
        runner, _ = fixture(active="9.9.9.9 149.112.112.112", dhcp="172.17.0.1")
        data = module.snapshot(runner=runner, connect=lambda *_: True)
        self.assertTrue(data["dns_override_suspected"])
        self.assertEqual(data["dhcp_advertised_dns"], ["172.17.0.1"])
        self.assertEqual(data["active_link_dns"], ["149.112.112.112", "9.9.9.9"])
        self.assertEqual(data["configured_profile_dns"], ["172.17.0.1"])
        self.assertTrue(data["profile_ignore_auto_dns"])
        self.assertTrue(data["profile_dns_runtime_drift"])
        self.assertEqual(data["nm_device_dns"], ["172.17.0.1"])
        self.assertEqual(data["runtime_dns_drift"], "NETWORKMANAGER_VS_RESOLVED")

    def test_system_resolver_failure_is_not_mislabeled_wifi_radio(self):
        runner, _ = fixture(system_dns=False)
        data = module.snapshot(runner=runner, connect=lambda *_: True)
        self.assertEqual(data["diagnosis"], "CLIENT_SYSTEM_DNS_PATH")
        self.assertEqual(data["wifi_radio"], "NOT_OBSERVED")

    def test_invalid_address_not_treated_as_dns_response(self):
        self.assertEqual(module.ipv4_addresses("999.777.123.88 garbage"), [])
        self.assertEqual(module.ipv4_addresses("an1 172.17.0.24:53"), ["172.17.0.24"])

    def test_invalid_arguments_fail_before_running_probes(self):
        for args in (
            ["--check", "--interface", "wlan0;rm"],
            ["--check", "--samples", "99"],
            ["--check", "--interval", "100"],
        ):
            with self.subTest(args=args):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), *args],
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
        help_result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0)

    def test_script_is_read_only_and_bounded(self):
        contents = SCRIPT.read_text()
        for forbidden in (
            "nmcli connection modify",
            "resolvectl dns eno1",
            "sudo ",
            "service unbound restart",
            "pfctl -F",
            "scan wifi",
            "nmcli device wifi rescan",
            "tcpdump",
            "shell=True",
        ):
            self.assertNotIn(forbidden, contents)
        self.assertIn("timeout=5", contents)
        self.assertIn("timeout=2", contents)

    def test_dhcp_lease_excludes_client_ipv4_and_netmask(self):
        lease = (
            "DHCP4.OPTION[3]: dhcp_server_identifier = 172.17.0.1\n"
            "DHCP4.OPTION[5]: domain_name_servers = 172.17.0.1\n"
            "DHCP4.OPTION[6]: ip_address = 172.17.0.57\n"
            "DHCP4.OPTION[7]: subnet_mask = 255.255.255.0\n"
            "DHCP4.OPTION[11]: requested_domain_name_servers = 1\n"
        )
        self.assertEqual(module.dhcp_dns_addresses(lease), ["172.17.0.1"])
        self.assertEqual(
            module.dhcp_dns_addresses(
                "DHCP4.OPTION[1]: domain_name_servers = 172.17.0.1 9.9.9.9\n",
            ),
            ["172.17.0.1", "9.9.9.9"],
        )
        self.assertEqual(
            module.dhcp_dns_addresses(
                "DHCP4.OPTION[2]: requested_domain_name_servers = 1\n",
            ),
            [],
        )

    def test_real_operator_snapshot_classifies_private_dns_failure(self):
        runner, _ = fixture(
            active="9.9.9.9 149.112.112.112",
            dhcp="172.17.0.1",
            private_sys=False,
            profile_dns="172.17.0.1",
            ignore_auto="yes",
        )
        data = module.snapshot(runner=runner, connect=lambda *_: True)
        self.assertEqual(data["dhcp_advertised_dns"], ["172.17.0.1"])
        self.assertTrue(data["pfsense_private_zone"])
        self.assertFalse(data["system_dns_private"])
        self.assertTrue(data["private_dns_warning"])
        self.assertTrue(data["profile_dns_runtime_drift"])
        self.assertEqual(data["diagnosis"], "CLIENT_PRIVATE_SPLIT_DNS_PATH")
        self.assertNotEqual(data["diagnosis"], "NO_FAILURE_DURING_SAMPLE")

    def test_profile_dns_parser_ignores_sensitive_non_dns_fields(self):
        profile = (
            "ipv4.dns: 172.17.0.1\n"
            "ipv4.ignore-auto-dns: yes\n"
            "connection.id: PRIVATE_PROFILE_IDENTIFIER\n"
            "ipv4.addresses: 172.17.0.57/24\n"
        )
        self.assertEqual(module.profile_dns_fields(profile), (["172.17.0.1"], True))
        runner, _ = fixture(active="9.9.9.9")
        data = module.snapshot(runner=runner, connect=lambda *_: True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            module.render(data)
        self.assertNotIn("Wired eno1", buf.getvalue())
        self.assertNotIn("PRIVATE_PROFILE_IDENTIFIER", buf.getvalue())
        self.assertIn("Runtime DNS also differs", buf.getvalue())

    def test_private_dns_failure_exit_code_without_network(self):
        data = {
            "diagnosis": "CLIENT_PRIVATE_SPLIT_DNS_PATH",
        }
        with mock.patch.object(module, "snapshot", return_value=data):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = module.main(["--check", "--json"])
        self.assertEqual(rc, 1)

    def test_dns_runtime_diff_is_not_blame_for_resolver(self):
        runner, _ = fixture(
            active="9.9.9.9 149.112.112.112",
            device_dns="172.17.0.1",
        )
        data = module.snapshot(runner=runner, connect=lambda *_: True)
        self.assertEqual(data["runtime_dns_drift"], "NETWORKMANAGER_VS_RESOLVED")
        self.assertEqual(data["nm_device_dns"], ["172.17.0.1"])
        self.assertEqual(data["active_link_dns"], ["149.112.112.112", "9.9.9.9"])

    def test_profile_differs_from_networkmanager_device_dns(self):
        runner, _ = fixture(
            active="9.9.9.9 149.112.112.112",
            device_dns="9.9.9.9 149.112.112.112",
            profile_dns="172.17.0.1",
        )
        data = module.snapshot(runner=runner, connect=lambda *_: True)
        self.assertEqual(
            data["runtime_dns_drift"],
            "PROFILE_VS_NETWORKMANAGER_DEVICE",
        )
        self.assertTrue(data["profile_dns_runtime_drift"])

    def test_private_zone_failure_is_not_reported_as_healthy(self):
        runner, _ = fixture(private_pf=False, private_sys=False)
        data = module.snapshot(runner=runner, connect=lambda *_: True)
        self.assertFalse(data["pfsense_private_zone"])
        self.assertEqual(data["diagnosis"], "PFSENSE_PRIVATE_ZONE_NOT_CONFIRMED")
        self.assertTrue(data["private_dns_warning"])

    def test_legacy_hide_location_quad9_candidate_without_causality(self):
        template = (
            "#!/bin/bash\n"
            'dns_new="9.9.9.9 149.112.112.112"\n'
            'net_interface="wlp0s20f3"\n'
            "if sudo resolvectl status | grep -q 172.17.0.24; then\n"
            "  sudo resolvectl dns $net_interface $dns_new\n"
            "fi\n"
            'SECRET_TOKEN="DO_NOT_PRINT"\n'
        )

        def systemctl(args):
            if args[0] == "systemctl":
                return True, (
                    "LoadState=loaded\n"
                    "UnitFileState=enabled\n"
                    "ActiveState=inactive\n"
                    "ExecMainStartTimestamp=Sun 2026-10-25 00:00:00 CET\n"
                    "Sensitive=DO_NOT_PRINT\n"
                )
            return False, ""

        probe = module.inspect_legacy_dns_hook(systemctl, "eno1", template)
        self.assertEqual(probe["unit_state"], "loaded")
        self.assertTrue(probe["hook_sets_quad9"])
        self.assertFalse(probe["hook_targets_current_interface"])
        self.assertTrue(probe["hook_contains_resolvectl_dns"])
        self.assertTrue(probe["unit_has_start_timestamp"])
        self.assertEqual(probe["causality"], "NOT_PROVEN")
        self.assertNotIn("DO_NOT_PRINT", str(probe))

    def test_legacy_hide_location_iface_match_and_missing_unit(self):
        body = (
            'dns_new="9.9.9.9 149.112.112.112"\n'
            'net_interface="eno1"\n'
            "sudo resolvectl dns $net_interface $dns_new\n"
        )

        def empty_runner(args):
            return (False, "")

        probe = module.inspect_legacy_dns_hook(empty_runner, "eno1", body)
        self.assertTrue(probe["hook_targets_current_interface"])
        self.assertEqual(probe["unit_state"], "unknown")
        self.assertEqual(probe["causality"], "NOT_PROVEN")
        absent = module.inspect_legacy_dns_hook(empty_runner, "eno1", None)
        self.assertFalse(absent["hook_present"])
        self.assertIsNone(absent["hook_targets_current_interface"])
        self.assertFalse(absent["hook_sets_quad9"])

    def test_runtime_hook_is_injected_not_read_during_fixtures(self):
        runner, calls = fixture(active="9.9.9.9", private_sys=False)
        injected = (
            'net_interface="eno1"\n'
            'dns_new="9.9.9.9 149.112.112.112"\n'
            "sudo resolvectl dns $net_interface $dns_new\n"
        )
        row = module.snapshot(
            runner=runner,
            connect=lambda *_: True,
            read_override=lambda: injected,
        )
        self.assertEqual(row["diagnosis"], "CLIENT_PRIVATE_SPLIT_DNS_PATH")
        self.assertTrue(row["legacy_dns_override"]["hook_sets_quad9"])
        self.assertTrue(row["legacy_dns_override"]["hook_targets_current_interface"])
        self.assertEqual(row["legacy_dns_override"]["causality"], "NOT_PROVEN")
        self.assertTrue(any(cmd[0] == "systemctl" for cmd in calls))


if __name__ == "__main__":
    unittest.main()
