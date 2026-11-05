#!/usr/bin/env python3
"""Read-only DNSSEC chain triage for workstation -> pfSense Unbound.

No global DNSSEC/DNS-over-TLS changes: --validate=no applies to one query.
No edit, restart, sudo, packet capture, credentials, or public DNS fallback.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import ipaddress
import re
import subprocess
import sys
import time

DNS = "172.17.0.1"
PRIVATE = "defectdojo.int.albandrieu.com"
PRIVATE_A = "172.17.0.24"
SIGNED = "cloudflare.com"
INVALID = "dnssec-failed.org"


@dataclass(frozen=True)
class Result:
    state: str
    elapsed: float
    rrsig: bool = False
    ad: bool = False


def command(argv: list[str], deadline: float) -> tuple[int | None, str, float]:
    start = time.monotonic()
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=deadline,
        )
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT", time.monotonic() - start
    except OSError:
        return None, "NOT_AVAILABLE", time.monotonic() - start
    return done.returncode, done.stdout[:10000], time.monotonic() - start


def v4_answers(text: str) -> set[str]:
    found = set()
    for word in re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", text):
        try:
            found.add(str(ipaddress.IPv4Address(word)))
        except ipaddress.AddressValueError:
            pass
    return found


def resolved(host: str, bypass: bool, timeout: float) -> Result:
    argv = ["resolvectl", "query", "-4"]
    if bypass:
        argv.append("--validate=no")
    argv.append(host)
    rc, out, duration = command(argv, timeout)
    if rc is None:
        return Result(out, duration)
    if rc != 0:
        return Result("FAILED", duration)
    answers = v4_answers(out)
    if host == PRIVATE:
        return Result(
            "A_CONFIRMED" if answers == {PRIVATE_A} else "UNEXPECTED_A",
            duration,
        )
    return Result("A_CONFIRMED" if answers else "NO_A", duration)


def upstream(name: str, rtype: str, timeout: float) -> Result:
    argv = [
        "dig",
        "+nocmd",
        "+noall",
        "+comments",
        "+answer",
        "+dnssec",
        "+time=2",
        "+tries=1",
        f"@{DNS}",
        name,
        rtype,
    ]
    rc, out, duration = command(argv, min(timeout, 4))
    if rc is None:
        return Result(out, duration)
    header = re.search(r"\bstatus:\s*([A-Z]+)", out)
    if not header:
        return Result("NO_DNS_RESPONSE", duration)
    rcode = header.group(1)
    signature = bool(re.search(r"^\S+\s+\d+\s+IN\s+RRSIG\s+", out, re.MULTILINE))
    ad = bool(re.search(r"\bflags:\s*[^\n;]*\bad\b", out))
    if rcode != "NOERROR":
        return Result("RCODE_" + rcode, duration, signature, ad)
    # For signed test, require the expected RR type in the response.
    answer = bool(
        re.search(
            r"^\S+\s+\d+\s+IN\s+" + re.escape(rtype) + r"\s+",
            out,
            re.MULTILINE,
        ),
    )
    return Result(
        "ANSWER" if answer else "NO_" + rtype + "_ANSWER",
        duration,
        signature,
        ad,
    )


def sample(timeout: float) -> dict[str, Result]:
    # Order deliberately alternates validated/bypassed lookups, then upstream.
    # The A/B contrast is a clue, not conclusive proof if the fault is intermittent.
    return {
        "private_validated": resolved(PRIVATE, False, timeout),
        "private_no_validation": resolved(PRIVATE, True, timeout),
        "public_validated": resolved(SIGNED, False, timeout),
        "public_no_validation": resolved(SIGNED, True, timeout),
        "pfsense_signed_a": upstream(SIGNED, "A", timeout),
        "pfsense_parent_ds": upstream("com", "DS", timeout),
        "pfsense_dnssec_bogus": upstream(INVALID, "A", timeout),
    }


def signals(values: dict[str, Result]) -> list[str]:
    result = []
    for name, item in values.items():
        if name.startswith("pfsense_"):
            if name == "pfsense_dnssec_bogus":
                if item.state != "RCODE_SERVFAIL":
                    result.append(name + ":" + item.state)
            elif item.state != "ANSWER" or not item.rrsig:
                result.append(
                    name
                    + ":"
                    + item.state
                    + ":RRSIG_"
                    + ("YES" if item.rrsig else "NO"),
                )
        elif item.state != "A_CONFIRMED":
            result.append(name + ":" + item.state)
        if item.elapsed > 3:
            result.append(name + ":SLOW")
    return result


def verdict(readings: list[dict[str, Result]]) -> str:
    if all(not signals(reading) for reading in readings):
        return "PASS"
    # Consistent per-query bypass advantage points to local DNSSEC validation,
    # but still does not identify why signatures are missing.
    for prefix in ("private", "public"):
        if all(
            reading[prefix + "_validated"].state != "A_CONFIRMED"
            and reading[prefix + "_no_validation"].state == "A_CONFIRMED"
            for reading in readings
        ):
            return "CLIENT_DNSSEC_VALIDATION_PATH_SUSPECTED"
    if any(
        r["pfsense_signed_a"].state == "ANSWER"
        and not r["pfsense_signed_a"].rrsig
        or r["pfsense_parent_ds"].state == "ANSWER"
        and not r["pfsense_parent_ds"].rrsig
        for r in readings
    ):
        return "PFSENSE_DNSSEC_SIGNATURES_NOT_CONFIRMED"
    return "DNSSEC_PATH_UNVERIFIED_OR_INTERMITTENT"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="read only (default)")
    parser.add_argument(
        "--samples",
        type=int,
        default=1,
        help="1 or 2 sequential cycles",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=4.0,
        help="per-probe deadline 1-8s",
    )
    opts = parser.parse_args()
    if opts.samples not in (1, 2) or not 1 <= opts.timeout <= 8:
        parser.error("samples must be 1-2 and timeout 1-8")
    readings = [sample(opts.timeout) for _ in range(opts.samples)]
    summary = verdict(readings)
    print("WORKSTATION_DNSSEC_CHAIN v1")
    print("  mode=READ_ONLY per_query_bypass=true global_dnssec_unchanged=true")
    for index, reading in enumerate(readings, start=1):
        prefix = f"sample_{index}." if opts.samples > 1 else ""
        for name, item in reading.items():
            suffix = ""
            if name.startswith("pfsense_"):
                rrsig = "yes" if item.rrsig else "no"
                ad = "yes" if item.ad else "no"
                suffix = f" rrsig={rrsig} ad={ad}"
            print(f"  {prefix}{name}={item.state} ({item.elapsed:.1f}s){suffix}")
        print(f"  {prefix}signals=" + (",".join(signals(reading)) or "none"))
    print(f"  diagnosis={summary}")
    if summary == "CLIENT_DNSSEC_VALIDATION_PATH_SUSPECTED":
        print(
            "  NEXT: validated DNS fails while --validate=no succeeds "
            "in every sample; investigate upstream RRSIG/DS availability "
            "and resolved DNSSEC journal; do not change global DNSSEC "
            "yet",
        )
    elif summary == "PFSENSE_DNSSEC_SIGNATURES_NOT_CONFIRMED":
        print(
            "  NEXT: DO=1 request did not confirm RRSIG from pfSense; "
            "inspect Unbound DNSSEC/forwarders and intervening DNS "
            "policies, do not conclude pfSense is DOWN",
        )
    elif summary != "PASS":
        print(
            "  NEXT: compare per-query results and pfSense RRSIG/AD/SERVFAIL; "
            "an intermittent failure cannot be attributed to DNSSEC "
            "validation alone",
        )
    return 0 if summary == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
