#!/usr/bin/env python3
"""Scoped runtime DNSSEC NTA experiment on the known workstation LAN link.

Read only by default. --apply changes only per-link NTA in systemd-resolved.
It does not edit DNSSEC settings, /etc/resolv.conf, or Unbound/pfSense.
This runtime setting is NOT persistent. Persist declaratively in Ansible only
after an operator verifies a validated lookup without --validate=no.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

IFACE = "eno1"
DOMAIN = "int.albandrieu.com"
HOST = "defectdojo.int.albandrieu.com"
EDGE = "172.17.0.24"
DNS = "172.17.0.1"
ACK = "I_APPROVE_SCOPED_PRIVATE_DNSSEC_NTA"


def call(argv: list[str], seconds: float = 5) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=seconds,
        )
    except subprocess.TimeoutExpired:
        return False, "", "TIMEOUT"
    except OSError:
        return False, "", "NOT_AVAILABLE"
    return (
        result.returncode == 0,
        result.stdout.strip()[:2000],
        "OK" if result.returncode == 0 else "FAILED",
    )


def link_nta() -> tuple[bool, list[str]]:
    ok, output, _ = call(["resolvectl", "nta", IFACE])
    if not ok:
        return False, []
    # Typical systemd output: "Link 2 (eno1): domain1 domain2".
    if ":" not in output:
        return False, []
    return True, output.split(":", 1)[1].strip().split()


def verified_profile() -> bool:
    ok, profile, _ = call(
        ["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", IFACE],
    )
    if not ok or profile.strip() != "Wired eno1":
        return False
    ok, dns, _ = call(
        ["nmcli", "-g", "ipv4.dns", "connection", "show", profile.strip()],
    )
    if not ok or dns.strip() != DNS:
        return False
    ok, linkdns, _ = call(["resolvectl", "dns", IFACE])
    if not ok or linkdns.split(":", 1)[-1].strip() != DNS:
        return False
    ok, routes, _ = call(["resolvectl", "domain", IFACE])
    return bool(ok and "~" + DOMAIN in routes.split())


def check_validated() -> tuple[bool, float]:
    start = time.monotonic()
    ok, output, _ = call(["resolvectl", "query", "-4", HOST], seconds=5)
    return bool(ok and EDGE in output), time.monotonic() - start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="read-only, default")
    modes.add_argument(
        "--apply",
        action="store_true",
        help="runtime NTA (explicit opt-in)",
    )
    modes.add_argument(
        "--remove",
        action="store_true",
        help="remove ONLY sole known runtime NTA",
    )
    parser.add_argument("--acknowledge", default="")
    args = parser.parse_args()
    if (args.apply or args.remove) and args.acknowledge != ACK:
        parser.error("Mutation requires --acknowledge " + ACK)
    if args.acknowledge and not (args.apply or args.remove):
        parser.error("acknowledge must accompany --apply or --remove")
    profile_ok = verified_profile()
    nta_ok, nta = link_nta()
    print("PRIVATE_DNSSEC_NTA v1")
    print(f"  profile_verified={str(profile_ok).lower()}")
    print("  nta_readable=" + str(nta_ok).lower())
    print(
        "  nta_state="
        + (
            "EXPECTED_ONLY"
            if nta == [DOMAIN]
            else "EMPTY"
            if not nta
            else "OTHER_OR_ADDITIONAL"
        ),
    )
    if not profile_ok or not nta_ok:
        print("  diagnosis=UNVERIFIED_WORKSTATION_NETWORK_OR_NTA")
        return 2
    if args.apply:
        if nta and nta != [DOMAIN]:
            print("  diagnosis=REFUSED_PREEXISTING_NTA_PRESERVE_EXISTING")
            return 2
        if not nta:
            ok, _, _ = call(["sudo", "resolvectl", "nta", IFACE, DOMAIN], 15)
            if not ok:
                print("  diagnosis=APPLY_FAILED")
                return 2
            print("  runtime_applied=true")
    elif args.remove:
        if nta != [DOMAIN]:
            print("  diagnosis=REFUSED_NTA_NOT_EXACT_EXPECTED")
            return 2
        ok, _, _ = call(["sudo", "resolvectl", "nta", IFACE, ""], 15)
        if not ok:
            print("  diagnosis=ROLLBACK_FAILED")
            return 2
        print("  runtime_rollback=true")
    if args.apply or args.remove:
        verified, nta = link_nta()
        if not verified or (args.apply and nta != [DOMAIN]) or (args.remove and nta):
            print("  diagnosis=NTA_POSTCHANGE_NOT_VERIFIED")
            return 2
    lookup, duration = check_validated()
    print(
        f"  validated_private={'A_CONFIRMED' if lookup else 'UNVERIFIED'} "
        f"({duration:.1f}s)",
    )
    print("  persistent=false")
    if args.remove:
        print(
            "  diagnosis=ROLLBACK_CONFIRMED; DNSSEC validation can "
            "fail on the private zone until NTA is re-added",
        )
        return 0
    print("  next=verify NSS and public DNSSEC; use Ansible for persistence")
    return 0 if lookup else 1


if __name__ == "__main__":
    sys.exit(main())
