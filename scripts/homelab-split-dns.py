#!/usr/bin/env python3
"""Workstation-only split-DNS recovery for the known pfSense LAN.

--check is read-only; --apply needs an exact acknowledgement.
No /etc/resolv.conf edits, WAN exposure, pfSense mutations, network reconnect,
DNS fallback to public resolvers or GitHub Actions.
"""

from __future__ import annotations

import argparse
import ipaddress
import re
import subprocess
import sys
import time

INTERFACE = "eno1"
RESOLVER = "172.17.0.1"
ZONE = "~int.albandrieu.com"
HOST = "defectdojo.int.albandrieu.com"
EDGE = "172.17.0.24"
ACK = "I_APPROVE_WORKSTATION_SPLIT_DNS_REPAIR"
QUAD9 = {"9.9.9.9", "149.112.112.112"}


def call(argv: list[str], timeout: int = 5) -> tuple[bool, str, float]:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, "", time.monotonic() - start
    return proc.returncode == 0, proc.stdout.strip()[:4096], time.monotonic() - start


def addresses(value: str) -> set[str]:
    found = set()
    for candidate in re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", value):
        try:
            found.add(str(ipaddress.IPv4Address(candidate)))
        except ipaddress.AddressValueError:
            continue
    return found


def dig(tcp: bool) -> tuple[str, float]:
    args = ["dig", "+short", "+time=2", "+tries=1"]
    if tcp:
        args.append("+tcp")
    args += [f"@{RESOLVER}", HOST, "A"]
    ok, data, duration = call(args, timeout=4)
    if not ok:
        return "NO_RESPONSE", duration
    ips = addresses(data)
    if ips == {EDGE}:
        return "A_CONFIRMED", duration
    return ("UNEXPECTED_ANSWER" if ips else "NO_A_ANSWER"), duration


def nss() -> str:
    ok, out, _ = call(["getent", "ahostsv4", HOST], timeout=14)
    if not ok or not out:
        return "UNRESOLVED"
    lines = [line.split() for line in out.splitlines() if line.strip()]
    return (
        "A_CONFIRMED"
        if lines and all(line[0] == EDGE for line in lines)
        else "UNEXPECTED_ANSWER"
    )


def profile() -> dict[str, str]:
    fields = {
        "name": ["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", INTERFACE],
        "device_dns": ["nmcli", "-g", "IP4.DNS", "device", "show", INTERFACE],
        "profile_dns": None,
        "profile_auto": None,
        "profile_domains": None,
        "link_dns": ["resolvectl", "dns", INTERFACE],
        "link_domains": ["resolvectl", "domain", INTERFACE],
    }
    values = {}
    ok, name, _ = call(fields["name"])
    values["name"] = name if ok else ""
    if values["name"] and values["name"] != "--":
        fields["profile_dns"] = ["nmcli", "-g", "ipv4.dns", "connection", "show", name]
        fields["profile_auto"] = [
            "nmcli",
            "-g",
            "ipv4.ignore-auto-dns",
            "connection",
            "show",
            name,
        ]
        fields["profile_domains"] = [
            "nmcli",
            "-g",
            "ipv4.dns-search",
            "connection",
            "show",
            name,
        ]
    for key, cmd in fields.items():
        if key == "name":
            continue
        ok, value, _ = call(cmd) if cmd else (False, "", 0)
        values[key] = value if ok else ""
    return values


def profile_routes(value: str) -> set[str]:
    return {v.strip() for v in re.split(r"[,;\s]+", value) if v.strip()}


def read() -> tuple[dict[str, str], dict[str, str]]:
    cfg = profile()
    udp, udps = dig(False)
    tcp, tcps = dig(True)
    nss_start = time.monotonic()
    sysname = nss()
    nss_sec = time.monotonic() - nss_start
    units = {}
    for unit in ("hide-location.timer", "hide-location.service"):
        ok, val, _ = call(["systemctl", "--user", "is-enabled", unit])
        units[unit] = val.strip() if val else "unknown"
    state = {
        "udp": udp,
        "tcp": tcp,
        "udp_sec": f"{udps:.1f}",
        "tcp_sec": f"{tcps:.1f}",
        "nss": sysname,
        "nss_sec": f"{nss_sec:.1f}",
        **units,
    }
    return cfg, state


def verdict(cfg: dict[str, str], state: dict[str, str]) -> str:
    if (
        state["hide-location.timer"] == "enabled"
        or state["hide-location.service"] == "enabled"
    ):
        return "LEGACY_DNS_OVERRIDE_ENABLED"
    if cfg["profile_dns"].strip() != RESOLVER or cfg["device_dns"].strip() != RESOLVER:
        return "NETWORKMANAGER_PROFILE_OR_DEVICE_DRIFT"
    if cfg["profile_auto"].strip().lower() not in ("yes", "true"):
        return "DHCP_DNS_OVERRIDE_POLICY_DRIFT"
    if ZONE not in profile_routes(cfg["profile_domains"]):
        return "PRIVATE_ROUTE_NOT_PERSISTED"
    if RESOLVER not in addresses(cfg["link_dns"]) or addresses(cfg["link_dns"]) & QUAD9:
        return "RESOLVED_LINK_DNS_DRIFT"
    if ZONE not in cfg["link_domains"].split():
        return "RESOLVED_PRIVATE_ROUTE_DRIFT"
    if state["udp"] != "A_CONFIRMED":
        return "PFSENSE_UDP53_UNVERIFIED"
    if state["tcp"] != "A_CONFIRMED":
        return "PFSENSE_TCP53_UNVERIFIED"
    if state["nss"] != "A_CONFIRMED":
        return "CLIENT_PRIVATE_SPLIT_DNS_PATH"
    return "PASS"


def display(cfg: dict[str, str], state: dict[str, str], result: str) -> None:
    # Avoid printing raw command output, profile name, or DNS names from env.
    nm = (
        "MATCH"
        if cfg["profile_dns"].strip() == RESOLVER
        and cfg["device_dns"].strip() == RESOLVER
        else "DRIFT"
    )
    link = "MATCH" if addresses(cfg["link_dns"]) == {RESOLVER} else "DRIFT"
    route = (
        "PERSISTED"
        if ZONE in profile_routes(cfg["profile_domains"])
        else "NOT_PERSISTED"
    )
    domain = "ROUTED" if ZONE in cfg["link_domains"].split() else "MISSING"
    print("WORKSTATION_SPLIT_DNS v1")
    print(
        f"  nm_profile={nm} private_route={route} resolved_link={link} "
        f"resolved_domain={domain}",
    )
    print(
        f"  pfsense_udp={state['udp']} ({state['udp_sec']}s) "
        f"pfsense_tcp={state['tcp']} "
        f"({state['tcp_sec']}s)",
    )
    print(
        f"  client_nss={state['nss']} ({state['nss_sec']}s) "
        f"legacy_timer={state['hide-location.timer']} "
        f"legacy_service={state['hide-location.service']}",
    )
    print(f"  diagnosis={result}")
    if state["udp"] != "A_CONFIRMED":
        print(
            "  NEXT: pfSense Unbound UDP/53 direct did not confirm; "
            "inspect DNS Resolver, firewall, packet loss or intermittent "
            "service, NOT just local split-DNS",
        )
    if state["udp"] != state["tcp"]:
        print(
            "  NEXT: UDP/TCP answers differ; investigate protocol-specific "
            "transport or DNS listener",
        )
    if state["nss"] != "A_CONFIRMED":
        print(
            "  NEXT: compare getent, /etc/nsswitch.conf and systemd-resolved; "
            "--resolve HTTPS is not DNS proof",
        )
    elif float(state["nss_sec"]) > 5:
        print(
            "  WARN: NSS query slow despite success; run 'mise run "
            "workstation-nss-path' to isolate glibc NSS vs 127.0.0.53 "
            "stub (do not restart pfSense)",
        )
    if result == "PRIVATE_ROUTE_NOT_PERSISTED":
        print(
            "  NEXT: persist ~int.albandrieu.com in NetworkManager "
            "(do not edit resolv.conf)",
        )


def apply(cfg: dict[str, str], state: dict[str, str]) -> int:
    if cfg["name"] != "Wired eno1" or cfg["device_dns"].strip() != RESOLVER:
        print(
            "REFUSED: workstation profile/device do not match approved eno1 LAN",
            file=sys.stderr,
        )
        return 2
    if cfg["profile_dns"].strip() != RESOLVER or cfg[
        "profile_auto"
    ].strip().lower() not in ("yes", "true"):
        print(
            "REFUSED: stored NetworkManager policy differs; inspect before modifying",
            file=sys.stderr,
        )
        return 2
    if state["udp"] != "A_CONFIRMED":
        print(
            "REFUSED: pfSense UDP/53 did not return the expected "
            "private A; do not hide an upstream failure with local "
            "overrides",
            file=sys.stderr,
        )
        return 2
    actions = []
    if (
        state["hide-location.timer"] == "enabled"
        or state["hide-location.service"] == "enabled"
    ):
        actions.append(
            [
                "systemctl",
                "--user",
                "disable",
                "--now",
                "hide-location.timer",
                "hide-location.service",
            ],
        )
    if ZONE not in profile_routes(cfg["profile_domains"]):
        actions.append(
            [
                "sudo",
                "nmcli",
                "connection",
                "modify",
                cfg["name"],
                "+ipv4.dns-search",
                ZONE,
            ],
        )
    actions += [
        ["sudo", "nmcli", "device", "reapply", INTERFACE],
        ["sudo", "resolvectl", "flush-caches"],
    ]
    for argv in actions:
        success, _, _ = call(argv, timeout=20)
        if not success:
            print(
                "APPLY_FAILED: action failed; inspect NetworkManager "
                "and systemd user units",
                file=sys.stderr,
            )
            return 2
    print("APPLY_ATTEMPTED: local profile reapplied; verifying DNS without overrides")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--check", action="store_true", help="read-only (default)")
    options.add_argument(
        "--apply",
        action="store_true",
        help="write only workstation NM/systemd config",
    )
    parser.add_argument("--acknowledge", default="")
    args = parser.parse_args()
    if args.apply and args.acknowledge != ACK:
        parser.error(f"--apply requires --acknowledge {ACK}")
    if args.acknowledge and not args.apply:
        parser.error("--acknowledge is only valid with --apply")
    cfg, state = read()
    if args.apply:
        status = apply(cfg, state)
        if status:
            display(cfg, state, verdict(cfg, state))
            return status
        cfg, state = read()
    result = verdict(cfg, state)
    display(cfg, state, result)
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
