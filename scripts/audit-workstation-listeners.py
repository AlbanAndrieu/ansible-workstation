#!/usr/bin/env python3
"""Privacy-preserving read-only count of TCP/UDP listening bindings.

No sudo, no container API, no port/address/process output; not an exposure
test. Docker DNAT-published ports may not appear as host listening sockets.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import subprocess

SCHEMA = "workstation-listener-visibility/v1"
COMMANDS = {
    "tcp": ("/usr/bin/ss", "-H", "-lnt"),
    "udp": ("/usr/bin/ss", "-H", "-lnu"),
}
SCOPES = ("wildcard", "loopback", "interface_specific", "unknown")
MAX_BYTES = 512 * 1024


def binding_scope(address):
    """Classify only the bind scope, never return the endpoint itself."""
    if not isinstance(address, str) or ":" not in address:
        return "unknown"
    host, _, port = address.rpartition(":")
    if not port or not host:
        return "unknown"
    host = host.removeprefix("[").removesuffix("]").split("%", 1)[0]
    if host == "*":
        return "wildcard"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "unknown"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_unspecified:
        return "wildcard"
    return "loopback" if ip.is_loopback else "interface_specific"


def summarize_ss(output):
    counts = {scope: 0 for scope in SCOPES}
    # Only these two fixed categories are exposed; NEVER expose raw endpoints.
    unknown_reasons = {"malformed_row": 0, "unparsed_local_endpoint": 0}
    total = 0
    for line in output.splitlines():
        values = line.split()
        if len(values) < 5 or values[0] not in ("LISTEN", "UNCONN"):
            counts["unknown"] += 1
            unknown_reasons["malformed_row"] += 1
            total += 1
            continue
        # ss -H -ln[t|u]: State Recv-Q Send-Q Local:Port Peer:Port.
        # Index 3 is LOCAL; index 4 is PEER (often 0.0.0.0:*).
        # Never infer wildcard from the peer address.
        scope = binding_scope(values[3])
        counts[scope] += 1
        if scope == "unknown":
            unknown_reasons["unparsed_local_endpoint"] += 1
        total += 1
    return {
        "count": total,
        "bind_scopes": counts,
        "unknown_reasons": unknown_reasons,
    }


def probe(protocol, executor=None):
    if protocol not in COMMANDS:
        raise ValueError("unexpected listener protocol")
    argv = COMMANDS[protocol]
    if not Path(argv[0]).is_file():
        return {"status": "missing", "summary": None}
    if executor is None:
        executor = subprocess.run
    try:
        result = executor(
            argv, capture_output=True, text=True, input="", timeout=4,
            check=False, env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
    except subprocess.TimeoutExpired:
        return {"status": "timed_out", "summary": None}
    except (OSError, ValueError):
        return {"status": "error", "summary": None}
    if result.returncode != 0:
        return {"status": "access_denied" if "permission denied" in
                (result.stderr or "").lower() else "error", "summary": None}
    raw = result.stdout or ""
    if len(raw.encode("utf-8")) > MAX_BYTES:
        return {"status": "error", "summary": None}
    return {"status": "ok", "summary": summarize_ss(raw)}


def inspect():
    return {
        "schema": SCHEMA,
        "tcp": probe("tcp"),
        "udp": probe("udp"),
        "effective_reachability": "not_verified",
        "docker_socket_queried": False,
        "limitations": [
            "Wildcard binding alone does not prove LAN or WAN reachability.",
            "Docker DNAT published ports may not create host listening sockets.",
            "No ports, IPs, PIDs, service names or socket paths are reported.",
            "No sudo, Docker socket, network connection or system mutation.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "summary"), default="summary")
    args = parser.parse_args()
    report = inspect()
    if args.format == "json":
        print(json.dumps(report, sort_keys=True, indent=2))
        return
    print("LISTENER BINDING VISIBILITY (read only; reachability NOT VERIFIED)")
    for proto in COMMANDS:
        print(proto + ":", report[proto]["status"])
        if report[proto]["summary"] is not None:
            print(json.dumps(report[proto]["summary"], sort_keys=True))
    print("No addresses, ports, processes, containers or endpoints reported.")


if __name__ == "__main__":
    main()
