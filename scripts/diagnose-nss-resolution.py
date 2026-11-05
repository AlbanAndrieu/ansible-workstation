#!/usr/bin/env python3
"""Read-only differential diagnosis for glibc NSS vs systemd-resolved.

No changes to NetworkManager, NSS, systemd services or /etc/resolv.conf.
Every probe has a deadline; a fast resolvectl result does not imply NSS PASS.
"""

from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import re
import subprocess
import sys
import time
from dataclasses import dataclass

HOST = "defectdojo.int.albandrieu.com"
EDGE = "172.17.0.24"
STUB = "127.0.0.53"


@dataclass(frozen=True)
class Sample:
    status: str
    seconds: float


def run(argv: list[str], timeout: float) -> Sample:
    start = time.monotonic()
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return Sample("TIMEOUT", time.monotonic() - start)
    except OSError:
        return Sample("NOT_AVAILABLE", time.monotonic() - start)
    ips = set()
    for value in re.findall(
        r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])",
        result.stdout[:4096],
    ):
        try:
            ips.add(str(ipaddress.IPv4Address(value)))
        except ipaddress.AddressValueError:
            pass
    if result.returncode != 0:
        return Sample("NO_ANSWER", time.monotonic() - start)
    if ips == {EDGE}:
        return Sample("A_CONFIRMED", time.monotonic() - start)
    return Sample(
        "UNEXPECTED_ANSWER" if ips else "NO_A_ANSWER",
        time.monotonic() - start,
    )


def stub_dns_probe(timeout: float) -> Sample:
    """Preserve DNS RCODE: dig +short alone hides SERVFAIL/NXDOMAIN/NODATA."""
    command = [
        "dig",
        "+nocmd",
        "+noall",
        "+comments",
        "+answer",
        "+time=2",
        "+tries=1",
        f"@{STUB}",
        HOST,
        "A",
    ]
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=min(4, timeout),
        )
    except subprocess.TimeoutExpired:
        return Sample("TIMEOUT", time.monotonic() - start)
    except OSError:
        return Sample("NOT_AVAILABLE", time.monotonic() - start)
    response = proc.stdout[:4096]
    match = re.search(r"\bstatus:\s*([A-Z]+)", response)
    if not match:
        return Sample(
            "NO_DNS_RESPONSE" if proc.returncode else "UNKNOWN_DNS_RESPONSE",
            time.monotonic() - start,
        )
    if match.group(1) != "NOERROR":
        return Sample("RCODE_" + match.group(1), time.monotonic() - start)
    answers = re.findall(
        r"^" + re.escape(HOST) + r"\.?\s+\d+\s+IN\s+A\s+(\d{1,3}(?:\.\d{1,3}){3})\s*$",
        response,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    ips = set()
    for candidate in answers:
        try:
            ips.add(str(ipaddress.IPv4Address(candidate)))
        except ipaddress.AddressValueError:
            continue
    state = (
        "A_CONFIRMED"
        if ips == {EDGE}
        else "UNEXPECTED_ANSWER"
        if ips
        else "NO_A_ANSWER"
    )
    return Sample(state, time.monotonic() - start)


def probe(timeout: float) -> dict[str, Sample]:
    # Sequential: avoid changing timings by saturating stub or NSS concurrently.
    # Forced NSS modules reveal where the default hosts: chain diverges.
    return {
        "resolved_native": run(
            ["resolvectl", "query", "-4", HOST],
            timeout,
        ),
        "stub_udp": stub_dns_probe(timeout),
        "nss_dns": run(
            ["getent", "-s", "hosts:dns", "ahostsv4", HOST],
            timeout,
        ),
        "nss_resolve": run(
            ["getent", "-s", "hosts:resolve", "ahostsv4", HOST],
            timeout,
        ),
        "nss_default": run(
            ["getent", "ahostsv4", HOST],
            timeout,
        ),
    }


def classify(samples: dict[str, Sample], slow_seconds: float = 5.0) -> str:
    native = samples["resolved_native"]
    stub = samples["stub_udp"]
    dns = samples["nss_dns"]
    default = samples["nss_default"]

    def successful(x):
        return x.status == "A_CONFIRMED" and x.seconds <= slow_seconds

    if not successful(native):
        return "RESOLVED_NATIVE_SLOW_OR_UNVERIFIED"
    if not successful(default):
        if successful(dns):
            return "NSS_DEFAULT_CHAIN_SLOW_OR_BROKEN"
        if not successful(stub):
            return "RESOLVED_STUB_UDP_SLOW_OR_BROKEN"
        return "NSS_DNS_PATH_SLOW_OR_BROKEN"
    # A good default-chain result cannot mask another failed probe.
    if not successful(stub):
        return "RESOLVED_STUB_UDP_SLOW_OR_BROKEN"
    if not successful(dns):
        return "NSS_DNS_PATH_SLOW_OR_BROKEN"
    return "PASS"


def hosts_chain() -> str:
    try:
        for line in Path("/etc/nsswitch.conf").read_text(encoding="utf-8").splitlines():
            if re.match(r"^\s*hosts\s*:", line):
                # Names and actions only: this system file has no credentials.
                return line.strip()[:250]
    except OSError:
        pass
    return "UNAVAILABLE"


def stub_config() -> str:
    try:
        target = Path("/etc/resolv.conf").resolve(strict=True)
        stub = Path("/run/systemd/resolve/stub-resolv.conf")
        return "SYSTEMD_STUB" if target == stub else "OTHER"
    except OSError:
        return "UNKNOWN"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="read only (default)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=6.0,
        help="Per probe deadline in seconds (default 6)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=1,
        help="Sequential samples (1-3, default 1); read-only",
    )
    args = parser.parse_args()
    if not 1 <= args.timeout <= 12:
        parser.error("--timeout must be between 1 and 12")
    if not 1 <= args.samples <= 3:
        parser.error("--samples must be between 1 and 3")
    readings = [probe(args.timeout) for _ in range(args.samples)]
    verdicts = [classify(observed) for observed in readings]
    if all(v == "PASS" for v in verdicts):
        result = "PASS"
    elif "PASS" in verdicts:
        result = "INTERMITTENT_RESOLUTION"
    elif len(set(verdicts)) > 1:
        result = "MULTI_LAYER_RESOLUTION_UNVERIFIED"
    else:
        result = verdicts[0]
    samples = readings[-1]
    print("WORKSTATION_NSS_PATH v2")
    print(f"  hosts_chain={hosts_chain()}")
    print(f"  resolv_conf={stub_config()}")
    for index, observed in enumerate(readings, start=1):
        prefix = f"sample_{index}." if args.samples > 1 else ""
        for name, sample in observed.items():
            print(f"  {prefix}{name}={sample.status} ({sample.seconds:.1f}s)")
        signals = [
            f"{name}:{item.status}"
            for name, item in observed.items()
            if name != "nss_resolve"
            and (item.status != "A_CONFIRMED" or item.seconds > 5)
        ]
        print(f"  {prefix}signals=" + (",".join(signals) if signals else "none"))
        if args.samples > 1:
            print(f"  {prefix}diagnosis={verdicts[index - 1]}")
    print(f"  diagnosis={result}")
    if result == "NSS_DEFAULT_CHAIN_SLOW_OR_BROKEN":
        print(
            "  NEXT: native resolver and forced nss-dns work; inspect "
            "hosts: ordering, mdns4_minimal and other NSS modules, "
            "do not modify pfSense",
        )
    elif result == "RESOLVED_STUB_UDP_SLOW_OR_BROKEN":
        print(
            "  NEXT: native resolvectl is fast but stub UDP 127.0.0.53 "
            "is not; inspect stub listener and glibc resolver path",
        )
    elif result == "NSS_DNS_PATH_SLOW_OR_BROKEN":
        print(
            "  NEXT: stub responds but forced nss-dns is slow; compare "
            "glibc resolver options and hosts: ordering",
        )
    elif result == "RESOLVED_NATIVE_SLOW_OR_UNVERIFIED":
        print(
            "  NEXT: native resolved is slow/unverified; compare "
            "stub DNS RCODE and direct pfSense UDP/TCP, then inspect "
            "DoT/DNSSEC negotiation read-only",
        )
    elif result in ("INTERMITTENT_RESOLUTION", "MULTI_LAYER_RESOLUTION_UNVERIFIED"):
        print(
            "  NEXT: several layers fluctuate; use per-sample signals "
            "and systemd-resolved logs before any DNS or NSS change",
        )
    if samples["nss_resolve"].status in ("NO_ANSWER", "NOT_AVAILABLE"):
        print(
            "  NOTE: forced nss-resolve did not answer; module may "
            "be absent or not configured, not a reason to edit nsswitch "
            "blindly",
        )
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
