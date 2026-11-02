#!/usr/bin/env python3
"""Read-only by default; explicitly exercise NetworkManager reapply -> link NTA.

--exercise temporarily clears only an existing, single, known private NTA and
asks NetworkManager to reapply eno1. If NetworkManager does not restore that
NTA, restore it (only while the vetted LAN configuration is still intact).
No reboot, global DNSSEC change, daemon restart, or automatic retries.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

IFACE = "eno1"
PROFILE = "Wired eno1"
DOMAIN = "int.albandrieu.com"
DNS = "172.17.0.1"
NAME = "defectdojo.int.albandrieu.com"
ADDR = "172.17.0.24"
PUBLIC = "cloudflare.com"
ACK = "I_APPROVE_NTA_REAPPLY_SMOKE"
DISPATCHER = Path("/etc/NetworkManager/dispatcher.d/90-nabla-private-dnssec-nta")
RESOLVECTL = "/usr/bin/resolvectl"
NMCLI = "/usr/bin/nmcli"


def run(argv: list[str], timeout: float = 8) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return proc.returncode == 0, proc.stdout[:4000]


def link_nta() -> tuple[bool, list[str]]:
    ok, out = run([RESOLVECTL, "nta", IFACE])
    if not ok or ":" not in out:
        return False, []
    return True, out.split(":", 1)[1].strip().split()


def expected_network() -> bool:
    ok, profile = run([NMCLI, "-g", "GENERAL.CONNECTION", "device", "show", IFACE])
    if not ok or profile.strip() != PROFILE:
        return False
    ok, link_dns = run([RESOLVECTL, "dns", IFACE])
    if not ok or ":" not in link_dns or link_dns.split(":", 1)[1].split() != [DNS]:
        return False
    ok, route = run([RESOLVECTL, "domain", IFACE])
    return bool(
        ok and ":" in route and ("~" + DOMAIN) in route.split(":", 1)[1].split(),
    )


def expected_dispatcher() -> bool:
    try:
        meta = DISPATCHER.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(meta.st_mode)
        and meta.st_uid == 0
        and meta.st_gid == 0
        and bool(meta.st_mode & stat.S_IXUSR)
        and not bool(meta.st_mode & 0o077)
    )


def probe_dns() -> tuple[bool, bool]:
    private_ok, private_out = run([RESOLVECTL, "query", "-4", NAME], timeout=6)
    public_ok, public_out = run([RESOLVECTL, "query", "-4", PUBLIC], timeout=6)
    private = private_ok and bool(
        re.search(r"\b" + re.escape(ADDR) + r"\b", private_out),
    )
    public = public_ok and "Data is authenticated: yes" in public_out
    return private, public


def preflight() -> bool:
    network = expected_network()
    dispatcher = expected_dispatcher()
    ok, ntas = link_nta()
    print("PRIVATE_NTA_DISPATCHER_ACCEPTANCE v1")
    print("  lan_profile=" + ("MATCH" if network else "UNVERIFIED"))
    print("  dispatcher=" + ("ROOT_EXECUTABLE" if dispatcher else "NOT_VERIFIED"))
    print(
        "  link_nta="
        + ("EXPECTED_ONLY" if ok and ntas == [DOMAIN] else "OTHER_OR_MISSING"),
    )
    return bool(network and dispatcher and ok and ntas == [DOMAIN])


def restore_on_failure() -> bool:
    # Never write a private NTA onto an unknown link/profile or overwrite others.
    if not expected_network():
        print("  rollback=REFUSED_PROFILE_OR_DNS_CHANGED")
        return False
    ok, ntas = link_nta()
    if not ok or ntas not in ([], [DOMAIN]):
        print("  rollback=REFUSED_OTHER_NTA")
        return False
    if ntas == [DOMAIN]:
        print("  rollback=ALREADY_PRESENT")
        return True
    success, _ = run([RESOLVECTL, "nta", IFACE, DOMAIN], timeout=6)
    print("  rollback=" + ("RESTORED_PRIVATE_NTA" if success else "FAILED"))
    return success


def acceptance(exercise: bool) -> int:
    if not preflight():
        print("  diagnosis=BLOCKED_PREFLIGHT_NO_MUTATION")
        return 2
    if not exercise:
        private, public = probe_dns()
        print("  private_dns=" + ("PASS" if private else "FAIL"))
        print("  public_dnssec=" + ("AUTHENTICATED" if public else "UNVERIFIED"))
        print("  mode=READ_ONLY")
        return 0 if private and public else 1

    if os.geteuid() != 0:
        print("  diagnosis=BLOCKED_ROOT_REQUIRED")
        return 2

    ok, _ = run([RESOLVECTL, "nta", IFACE, ""], timeout=6)
    if not ok:
        print("  diagnosis=BLOCKED_CLEAR_FAILED")
        return 2
    ok, ntas = link_nta()
    if not ok or ntas:
        print("  diagnosis=BLOCKED_CLEAR_UNVERIFIED")
        restore_on_failure()
        return 2
    print("  private_nta_temporarily_cleared=true")

    applied, _ = run([NMCLI, "--wait", "15", "device", "reapply", IFACE], timeout=20)
    restored_by_nm = False
    if applied:
        for _ in range(12):
            if not expected_network():
                break
            valid, actual = link_nta()
            if valid and actual == [DOMAIN]:
                restored_by_nm = True
                break
            if not valid or actual:
                break
            time.sleep(0.5)
    print("  nm_reapply=" + ("PASS" if applied else "FAILED"))
    print("  nta_restored_by_event=" + ("PASS" if restored_by_nm else "FAIL"))
    if not restored_by_nm:
        restore_on_failure()
        print("  diagnosis=FAIL_DISPATCHER_REAPPLY_NOT_CONFIRMED")
        return 1

    private, public = probe_dns()
    print("  private_dns=" + ("PASS" if private else "FAIL"))
    print("  public_dnssec=" + ("AUTHENTICATED" if public else "UNVERIFIED"))
    result = private and public and expected_network()
    print(
        "  diagnosis="
        + ("PASS_REAPPLY_PERSISTENCE" if result else "FAIL_DNS_VALIDATION"),
    )
    return 0 if result else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="read-only (default)")
    parser.add_argument(
        "--exercise",
        action="store_true",
        help="clear NTA then NM reapply",
    )
    parser.add_argument("--acknowledge", default="")
    opts = parser.parse_args()
    if opts.check and opts.exercise:
        parser.error("--check and --exercise are mutually exclusive")
    if opts.exercise and opts.acknowledge != ACK:
        parser.error("--exercise requires --acknowledge " + ACK)
    if opts.acknowledge and not opts.exercise:
        parser.error("acknowledge requires --exercise")
    return acceptance(opts.exercise)


if __name__ == "__main__":
    sys.exit(main())
