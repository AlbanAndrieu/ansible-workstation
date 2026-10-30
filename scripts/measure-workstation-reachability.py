#!/usr/bin/env python3
"""Bounded TCP reachability measurement from one explicitly declared observer.

No discovery, DNS, port sweep, subprocess, elevated privilege or persistence.
Targets/ports are private in an operator-owned 0600 JSON file outside Git.
Public output has counters only and NEVER proves the claimed observer location.
"""
import argparse
import errno
import ipaddress
import json
import os
from pathlib import Path
import socket
import stat
import sys

SCHEMA = "workstation-reachability-measurement/v1"
MANIFEST_SCHEMA = "workstation-connectivity-allowlist/v1"
OBSERVERS = ("local", "lan", "wan")
MAX_TARGETS = 12
TIMEOUT_SECONDS = 1.5
RFC1918 = tuple(ipaddress.ip_network(x) for x in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))
IPV6_ULA = ipaddress.ip_network("fc00::/7")
RESULT_KEYS = (
    "expected_allowed", "expected_denied", "unexpected_open",
    "unexpected_closed", "inconclusive",
)


class InvalidManifest(ValueError):
    """Manifest rejected; error text must not contain sensitive data."""


def validate_scope(address, observer):
    try:
        ip = ipaddress.ip_address(address)
    except (ValueError, TypeError):
        raise InvalidManifest("target address must be a numeric IP literal") from None
    if ip.is_multicast or ip.is_unspecified or ip.is_link_local:
        raise InvalidManifest("multicast, wildcard and link-local addresses are prohibited")
    if observer == "local":
        allowed = ip.is_loopback
    elif observer == "lan":
        allowed = (ip.version == 4 and any(ip in net for net in RFC1918)) or (
            ip.version == 6 and ip in IPV6_ULA
        )
    else:
        allowed = ip.is_global
    if not allowed:
        raise InvalidManifest("target address is not in the declared observer's address class")
    return ip


def read_manifest(path, observer, *, repo_root=None):
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.is_symlink():
        raise InvalidManifest("manifest must be an absolute, non-symlink file")
    try:
        real = candidate.resolve(strict=True)
        metadata = real.stat()
    except OSError:
        raise InvalidManifest("manifest is not accessible") from None
    root = (Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]).resolve()
    if real == root or root in real.parents:
        raise InvalidManifest("manifest must be outside the Git checkout")
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise InvalidManifest("manifest must be an operator-owned regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise InvalidManifest("manifest must not be accessible to group or others")
    if metadata.st_size > 16384:
        raise InvalidManifest("manifest size exceeds 16 KiB")
    try:
        config = json.loads(real.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise InvalidManifest("manifest cannot be read as valid JSON") from None
    if not isinstance(config, dict) or set(config) != {"schema", "targets"}:
        raise InvalidManifest("manifest requires only schema and targets")
    if config["schema"] != MANIFEST_SCHEMA:
        raise InvalidManifest("unsupported manifest version")
    values = config["targets"]
    if not isinstance(values, list) or len(values) > MAX_TARGETS:
        raise InvalidManifest("manifest target count exceeds bound")
    selected, seen = [], set()
    for row in values:
        if not isinstance(row, dict) or set(row) != {
            "observer", "address", "port", "expected"
        }:
            raise InvalidManifest("target has unexpected fields")
        site = row["observer"]
        if site not in OBSERVERS:
            raise InvalidManifest("observer must be local, lan or wan")
        address = row["address"]
        if not isinstance(address, str):
            raise InvalidManifest("address must be a numeric IP string")
        ip = validate_scope(address, site)
        port = row["port"]
        if type(port) is not int or not (1 <= port <= 65535):
            raise InvalidManifest("port must be an integer from 1 through 65535")
        if row["expected"] not in ("allow", "deny"):
            raise InvalidManifest("expected must be allow or deny")
        key = (site, ip.compressed, port)
        if key in seen:
            raise InvalidManifest("duplicate endpoint in manifest")
        seen.add(key)
        if site == observer:
            selected.append((ip, port, row["expected"]))
    if not selected:
        raise InvalidManifest("no allowlisted targets for the selected observer")
    return selected


def try_tcp(ip, port, timeout=TIMEOUT_SECONDS, connector=None):
    """One TCP handshake only; no application data or retry."""
    if connector is not None:
        return connector(ip, port, timeout)
    family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            result = client.connect_ex(
                (str(ip), port, 0, 0) if ip.version == 6 else (str(ip), port)
            )
    except (TimeoutError, socket.timeout):
        return "timed_out"
    except OSError:
        return "error"
    if result == 0:
        return "connected"
    if result == errno.ECONNREFUSED:
        return "refused"
    if result == errno.ETIMEDOUT:
        return "timed_out"
    if result in (errno.EHOSTUNREACH, errno.ENETUNREACH):
        return "unreachable"
    return "error"


def summarize(targets, observer, *, active=False, connector=None):
    outcomes = {name: 0 for name in RESULT_KEYS}
    observed = {name: 0 for name in (
        "connected", "refused", "timed_out", "unreachable", "error"
    )}
    for ip, port, expectation in targets if active else ():
        result = try_tcp(ip, port, connector=connector)
        observed[result if result in observed else "error"] += 1
        if result == "connected":
            status = "expected_allowed" if expectation == "allow" else "unexpected_open"
        elif result == "refused":
            status = "unexpected_closed" if expectation == "allow" else "expected_denied"
        else:
            status = "inconclusive"
        outcomes[status] += 1
    return {
        "schema": SCHEMA,
        "observer_claimed": observer,
        "observer_independence_verified": False,
        "measurement_performed": active,
        "protocol": "tcp_handshake_only",
        "targets_configured": len(targets),
        "attempts": sum(observed.values()),
        "outcomes": outcomes,
        "transport_observed": observed,
        "overall_reachability": "not_verified" if not active else
            ("unexpected_open" if outcomes["unexpected_open"] else
             "needs_review" if outcomes["unexpected_closed"] or outcomes["inconclusive"]
             else "matched_configured_expectations"),
        "limitations": [
            "Observer location is self-declared; do not run LAN/WAN on the target itself.",
            "Only explicit numerical-IP/port targets are tested once; no discovery or DNS.",
            "Refused is a denial; timeout/unreachable/error remain inconclusive.",
            "A TCP handshake does not verify TLS, authentication, application or UDP.",
            "Connected to a proxy/tunnel is not evidence of workstation reachability.",
            "Only aggregated counters are printed; no targets, ports, IDs or source IPs.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer", choices=OBSERVERS, required=True)
    parser.add_argument("--allowlist", required=True,
                        help="absolute path to private 0600 JSON file OUTSIDE Git")
    parser.add_argument("--confirm-connect", action="store_true",
                        help="explicit opt-in for at most 12 single TCP connections")
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        parser.error("never run this collector as root or with sudo")
    try:
        targets = read_manifest(args.allowlist, args.observer)
    except InvalidManifest as error:
        parser.error(str(error))
    output = summarize(targets, args.observer, active=args.confirm_connect)
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
