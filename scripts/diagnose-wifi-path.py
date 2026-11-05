#!/usr/bin/env python3
"""Read-only workstation Wi-Fi / routing / DNS path diagnostic.

A wired workstation cannot establish Wi-Fi association or radio quality on a phone.
This tool makes that limitation explicit. It never scans SSIDs or logs BSSIDs.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

Runner = Callable[[Sequence[str]], tuple[bool, str]]
Connect = Callable[[str, int], bool]
IPV4_RE = re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")
DEVICE_RE = re.compile(r"\bdev\s+([A-Za-z0-9_.:-]+)")


def run_readonly(argv: Sequence[str]) -> tuple[bool, str]:
    """All commands have bounded duration; stderr and secrets are not reported."""
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return completed.returncode == 0, completed.stdout[:4096]


def tcp_probe(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def ipv4_addresses(value: str) -> list[str]:
    addresses: set[str] = set()
    for match in IPV4_RE.findall(value):
        try:
            addresses.add(str(ipaddress.IPv4Address(match)))
        except ipaddress.AddressValueError:
            pass
    return sorted(addresses)


def dhcp_dns_addresses(output: str) -> list[str]:
    """Read only the explicitly named DHCP DNS option, not IP/netmask fields."""
    found: set[str] = set()
    for line in output.splitlines():
        match = re.fullmatch(
            r"\s*(?:DHCP4\.OPTION(?:\[\d+\])?:\s*)?"
            r"domain_name_servers\s*=\s*(.*?)\s*",
            line,
        )
        if not match:
            continue
        # Only accept separate IPv4 values within the same named DHCP option.
        for token in re.split(r"[\s,;]+", match.group(1)):
            try:
                found.add(str(ipaddress.IPv4Address(token)))
            except ipaddress.AddressValueError:
                continue
    return sorted(found)


def profile_dns_fields(output: str) -> tuple[list[str], bool | None]:
    """Only NetworkManager IPv4 DNS and ignore-auto-dns; never show profile data."""
    dns: list[str] = []
    ignored: bool | None = None
    for line in output.splitlines():
        match = re.match(r"^\s*ipv4\.(dns|ignore-auto-dns)\s*:\s*(.*?)\s*$", line)
        if not match:
            continue
        if match.group(1) == "dns":
            dns = ipv4_addresses(match.group(2))
        elif match.group(2).lower() in ("yes", "true", "1"):
            ignored = True
        elif match.group(2).lower() in ("no", "false", "0"):
            ignored = False
    return dns, ignored


def read_installed_dns_hook() -> str | None:
    """Inspect a tiny regular file; do not follow a link or print its contents."""
    hook = Path("/opt/script/hide-location.sh")
    try:
        if not hook.is_file() or hook.is_symlink() or hook.stat().st_size > 16384:
            return None
        return hook.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def inspect_legacy_dns_hook(
    runner: Runner,
    interface: str | None,
    source: str | None,
) -> dict[str, object]:
    """Classify the installed Ansible DNS override; never run it."""
    service_ok, service_text = runner(
        (
            "systemctl",
            "--user",
            "show",
            "hide-location.service",
            "--property=LoadState,UnitFileState,ActiveState,ExecMainStartTimestamp",
            "--no-pager",
        ),
    )
    # The service status proves only unit configuration, not who wrote DNS.
    allowed_fields = {
        "LoadState",
        "UnitFileState",
        "ActiveState",
        "ExecMainStartTimestamp",
    }
    fields: dict[str, str] = {}
    if service_ok:
        for line in service_text.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in allowed_fields:
                fields[key] = value
    state = fields.get("LoadState", "unknown")
    started = fields.get("ExecMainStartTimestamp", "")
    template = source or ""
    target_match = re.search(
        r'^net_interface="([A-Za-z0-9_.:-]{1,32})"$',
        template,
        re.MULTILINE,
    )
    dns_match = re.search(
        r'^dns_new="([0-9. ]{3,64})"$',
        template,
        re.MULTILINE,
    )
    target = target_match.group(1) if target_match else None
    configured = ipv4_addresses(dns_match.group(1)) if dns_match else []
    # Do not disclose the installed script's contents or any other variables.
    return {
        "unit_state": state,
        "unit_file_state": fields.get("UnitFileState", "unknown"),
        "unit_active_state": fields.get("ActiveState", "unknown"),
        "unit_has_start_timestamp": bool(started and started != "n/a"),
        "hook_present": source is not None,
        "hook_contains_resolvectl_dns": bool(
            re.search(
                r"^\s*(?:sudo\s+)?resolvectl\s+dns\s+",
                template,
                re.MULTILINE,
            ),
        ),
        "hook_sets_quad9": configured == ["149.112.112.112", "9.9.9.9"],
        "hook_targets_current_interface": (
            None if target is None or interface is None else target == interface
        ),
        # This is an investigation candidate, never a proof of execution.
        "causality": "NOT_PROVEN",
    }


def query_a(runner: Runner, dns: str, name: str) -> bool:
    success, value = runner(
        ("dig", "+time=2", "+tries=1", "+short", f"@{dns}", name, "A"),
    )
    return success and bool(ipv4_addresses(value))


def snapshot(
    runner: Runner = run_readonly,
    connect: Connect = tcp_probe,
    iface: str | None = None,
    read_override: Callable[[], str | None] | None = None,
) -> dict[str, object]:
    route_ok, route = runner(("ip", "-4", "route", "get", "1.1.1.1"))
    if not iface:
        match = DEVICE_RE.search(route) if route_ok else None
        iface = match.group(1) if match else None
    result: dict[str, object] = {
        "scope": "workstation_only",
        "interface": iface or "unknown",
        "wifi_radio": "NOT_OBSERVED",
        "wifi_signal_dbm": None,
        "wifi_frequency_mhz": None,
        "default_ipv4_route": "OK" if route_ok else "UNKNOWN",
    }
    # Never run a Wi-Fi scan; 'iw link' reads current association only.
    if iface:
        type_ok, dev_type = runner(
            ("nmcli", "-g", "GENERAL.TYPE", "device", "show", iface),
        )
        wifi = type_ok and (
            "wifi" in dev_type.lower() or "wireless" in dev_type.lower()
        )
        result["vantage"] = "wifi" if wifi else "wired_or_unknown"
        if wifi:
            iw_ok, iw_link = runner(("iw", "dev", iface, "link"))
            if iw_ok and "Not connected." in iw_link:
                result["wifi_radio"] = "DISCONNECTED"
            elif iw_ok and "Connected to " in iw_link:
                result["wifi_radio"] = "ASSOCIATED"
                signal = re.search(r"\bsignal:\s*(-?\d+)\s*dBm", iw_link)
                freq = re.search(r"\bfreq:\s*(\d+)", iw_link)
                if signal:
                    result["wifi_signal_dbm"] = int(signal.group(1))
                if freq:
                    result["wifi_frequency_mhz"] = int(freq.group(1))
            else:
                result["wifi_radio"] = "UNKNOWN"
        dns_ok, dns_text = runner(("resolvectl", "dns", iface))
        result["active_link_dns"] = ipv4_addresses(dns_text) if dns_ok else []
        device_ok, device_dns_text = runner(
            (
                "nmcli",
                "-g",
                "IP4.DNS",
                "device",
                "show",
                iface,
            ),
        )
        result["nm_device_dns"] = ipv4_addresses(device_dns_text) if device_ok else []
        nm_ok, lease = runner(("nmcli", "-f", "DHCP4.OPTION", "device", "show", iface))
        result["dhcp_advertised_dns"] = dhcp_dns_addresses(lease) if nm_ok else []
        profile_ok, profile_name = runner(
            ("nmcli", "-g", "GENERAL.CONNECTION", "device", "show", iface),
        )
        result["configured_profile_dns"] = []
        result["profile_ignore_auto_dns"] = None
        if profile_ok and profile_name.strip() not in ("", "--"):
            fields_ok, fields = runner(
                (
                    "nmcli",
                    "-f",
                    "ipv4.dns,ipv4.ignore-auto-dns",
                    "connection",
                    "show",
                    profile_name.strip(),
                ),
            )
            if fields_ok:
                configured, ignore_dhcp = profile_dns_fields(fields)
                result["configured_profile_dns"] = configured
                result["profile_ignore_auto_dns"] = ignore_dhcp
    else:
        result["vantage"] = "unknown"
        result["active_link_dns"] = []
        result["nm_device_dns"] = []
        result["dhcp_advertised_dns"] = []
        result["configured_profile_dns"] = []
        result["profile_ignore_auto_dns"] = None

    # Two independent public DNS endpoints and DNS access to the LAN gateway.
    result["pfsense_dns_public"] = query_a(runner, "172.17.0.1", "example.org")
    result["control_dns_public"] = query_a(runner, "9.9.9.9", "example.org")
    result["pfsense_private_zone"] = False
    ok, answer = runner(
        (
            "dig",
            "+time=2",
            "+tries=1",
            "+short",
            "@172.17.0.1",
            "sample.int.albandrieu.com",
            "A",
        ),
    )
    result["pfsense_private_zone"] = ok and "172.17.0.24" in ipv4_addresses(answer)
    sys_ok, host = runner(("getent", "ahostsv4", "example.org"))
    result["system_dns_public"] = sys_ok and bool(ipv4_addresses(host))
    private_ok, private_host = runner(
        (
            "getent",
            "ahostsv4",
            "sample.int.albandrieu.com",
        ),
    )
    result["system_dns_private"] = private_ok and "172.17.0.24" in ipv4_addresses(
        private_host,
    )
    result["pfsense_tcp53"] = connect("172.17.0.1", 53)
    result["external_tcp443"] = connect("1.1.1.1", 443)

    active_dns = result["active_link_dns"]
    advertised_dns = result["dhcp_advertised_dns"]
    override = (
        bool(advertised_dns)
        and "172.17.0.1" in advertised_dns
        and bool(active_dns)
        and "172.17.0.1" not in active_dns
    )
    configured_dns = result["configured_profile_dns"]
    profile_drift = (
        "172.17.0.1" in configured_dns
        and bool(active_dns)
        and "172.17.0.1" not in active_dns
    )
    if result["wifi_radio"] == "DISCONNECTED":
        diagnosis = "WIFI_ASSOCIATION_LOST"
    elif (
        result["external_tcp443"]
        and result["control_dns_public"]
        and not result["pfsense_dns_public"]
    ):
        diagnosis = "PFSENSE_DNS_OR_WIFI_VLAN_POLICY"
    elif (
        result["external_tcp443"]
        and result["pfsense_dns_public"]
        and not result["system_dns_public"]
    ):
        diagnosis = "CLIENT_SYSTEM_DNS_PATH"
    elif (
        result["pfsense_private_zone"] and not result["system_dns_private"] and route_ok
    ):
        diagnosis = "CLIENT_PRIVATE_SPLIT_DNS_PATH"
    elif route_ok and not result["pfsense_private_zone"]:
        diagnosis = "PFSENSE_PRIVATE_ZONE_NOT_CONFIRMED"
    elif not route_ok:
        diagnosis = "IPV4_ROUTE_NOT_CONFIRMED"
    elif (
        not result["external_tcp443"]
        and not result["pfsense_dns_public"]
        and not result["control_dns_public"]
    ):
        diagnosis = "NETWORK_OR_POLICY_UNDETERMINED"
    elif (
        result["external_tcp443"]
        and result["pfsense_dns_public"]
        and result["system_dns_public"]
    ):
        diagnosis = "NO_FAILURE_DURING_SAMPLE"
    else:
        diagnosis = "INCONCLUSIVE_CHECK_MORE_CLIENTS"
    result["diagnosis"] = diagnosis
    nm_device_dns = result["nm_device_dns"]
    if nm_device_dns and active_dns and set(nm_device_dns) != set(active_dns):
        result["runtime_dns_drift"] = "NETWORKMANAGER_VS_RESOLVED"
    elif configured_dns and nm_device_dns and set(configured_dns) != set(nm_device_dns):
        result["runtime_dns_drift"] = "PROFILE_VS_NETWORKMANAGER_DEVICE"
    elif profile_drift:
        result["runtime_dns_drift"] = "PROFILE_VS_ACTIVE_RESOLVER"
    else:
        result["runtime_dns_drift"] = "NONE_CONFIRMED"
    result["dns_override_suspected"] = override
    result["profile_dns_runtime_drift"] = profile_drift
    result["private_dns_warning"] = (
        not result["pfsense_private_zone"] or not result["system_dns_private"]
    )
    result["wifi_client_not_tested"] = result["vantage"] != "wifi"
    result["legacy_dns_override"] = inspect_legacy_dns_hook(
        runner,
        iface,
        read_override() if read_override is not None else None,
    )
    return result


def render(result: dict[str, object]) -> None:
    def mark(value: object) -> str:
        if value is True or value in ("OK", "ASSOCIATED"):
            return "✅"
        if value is False or value == "DISCONNECTED":
            return "⚠️"
        return "ℹ️"

    print("🔎 Workstation link and DNS path (read-only)")
    print(
        f"  vantage={result['vantage']} interface={result['interface']} "
        f"wifi_radio={result['wifi_radio']}",
    )
    if result["wifi_signal_dbm"] is not None:
        print(
            f"  signal_dbm={result['wifi_signal_dbm']} "
            f"frequency_mhz={result['wifi_frequency_mhz']}",
        )
    print("  DHCP DNS =", ",".join(result["dhcp_advertised_dns"]) or "not_observed")
    print("  active DNS =", ",".join(result["active_link_dns"]) or "not_observed")
    print(
        "  NetworkManager device DNS =",
        ",".join(result["nm_device_dns"]) or "not_observed",
    )
    print(
        "  profile DNS =",
        ",".join(result["configured_profile_dns"]) or "not_observed",
    )
    print("  profile ignore-auto-dns =", result["profile_ignore_auto_dns"])
    for label, key in (
        ("IPv4 route", "default_ipv4_route"),
        ("LAN TCP/53", "pfsense_tcp53"),
        ("Internet TCP/443 by IP", "external_tcp443"),
        ("pfSense public DNS", "pfsense_dns_public"),
        ("Quad9 control DNS", "control_dns_public"),
        ("System public DNS", "system_dns_public"),
        ("pfSense private DNS", "pfsense_private_zone"),
        ("System private-name resolution", "system_dns_private"),
    ):
        print(f"  {mark(result[key])} {label}: {result[key]}")
    print("📋 diagnosis=" + str(result["diagnosis"]))
    if result["dns_override_suspected"]:
        print("⚠️ Active link DNS differs from pfSense advertised by DHCP.")
    if result["profile_dns_runtime_drift"]:
        print("⚠️ Runtime DNS also differs from the active NetworkManager profile.")
        print("ℹ️ Inspect resolved/VPN/global DNS ownership; do not change DHCP.")
    if result["runtime_dns_drift"] != "NONE_CONFIRMED":
        print("📍 DNS difference layer=" + str(result["runtime_dns_drift"]))
    if result["wifi_client_not_tested"]:
        print(
            "ℹ️ Workstation is not a confirmed Wi-Fi client: AP/phone radio not tested.",
        )
    legacy = result["legacy_dns_override"]
    if legacy["hook_present"] or legacy["unit_state"] == "loaded":
        print("🔎 Legacy Ansible hide-location DNS hook (read-only)")
        print(
            "  unit_state="
            + str(legacy["unit_state"])
            + " enabled="
            + str(legacy["unit_file_state"])
            + " started_recorded="
            + str(legacy["unit_has_start_timestamp"]),
        )
        print(
            "  sets_quad9="
            + str(legacy["hook_sets_quad9"])
            + " targets_interface="
            + str(legacy["hook_targets_current_interface"])
            + " resolvectl_dns="
            + str(legacy["hook_contains_resolvectl_dns"]),
        )
        print("  ⚠️ Hook existence is not evidence it changed this link's DNS.")
    print("Evidence from this instant only; do not infer a pfSense restart cause.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--interface", help="interface already in use, no scans")
    parser.add_argument("--json", action="store_true", help="machine-readable only")
    parser.add_argument("--samples", type=int, default=1, help="1..12")
    parser.add_argument("--interval", type=int, default=2, help="0..60 seconds")
    args = parser.parse_args(argv)
    if args.interface and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,32}", args.interface):
        parser.error("invalid interface")
    if not 1 <= args.samples <= 12 or not 0 <= args.interval <= 60:
        parser.error("samples must be 1..12 and interval 0..60")
    rows: list[dict[str, object]] = []
    for index in range(args.samples):
        if index:
            time.sleep(args.interval)
        row = snapshot(
            iface=args.interface,
            read_override=read_installed_dns_hook,
        )
        row["sample_number"] = index + 1
        rows.append(row)
        if not args.json:
            if index:
                print()
            render(row)
    if args.json:
        print(
            json.dumps(
                {"schema": "nabla.workstation.network-path.v1", "samples": rows},
                indent=2,
                sort_keys=True,
            ),
        )
    # A read-only probe never claims that a short healthy sample closed an incident.
    verified_failures = {
        "WIFI_ASSOCIATION_LOST",
        "PFSENSE_DNS_OR_WIFI_VLAN_POLICY",
        "CLIENT_SYSTEM_DNS_PATH",
        "CLIENT_PRIVATE_SPLIT_DNS_PATH",
        "PFSENSE_PRIVATE_ZONE_NOT_CONFIRMED",
    }
    return 1 if any(row["diagnosis"] in verified_failures for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
