#!/usr/bin/env python3
"""Explicit, non-root, local Docker publication visibility: counters only.

WARNING: Access to Docker daemon grants root-equivalent control on many hosts.
Runs only a fixed read command after explicit acknowledgment. Never enables
Docker privileges, starts/stops containers, or prints any port/address/name.
"""
import argparse
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re

_COMMON = importlib.util.spec_from_file_location(
    "audit_common", Path(__file__).with_name("audit_common.py"))
common = importlib.util.module_from_spec(_COMMON)
_COMMON.loader.exec_module(common)

SCHEMA = "workstation-docker-publications/v1"
DOCKER = "/usr/bin/docker"
ARGV = (
    DOCKER, "--host", "unix:///var/run/docker.sock",
    "container", "ls", "--format", "{{json .Ports}}",
)
MAX_BYTES = 262144
PROTOCOLS = ("tcp", "udp", "other")
SCOPES = ("wildcard", "loopback", "interface_specific", "unknown")


def scope_for_segment(segment):
    if not isinstance(segment, str) or "->" not in segment:
        return None
    host_endpoint, container_endpoint = segment.split("->", 1)
    # Don't allow malformed host/port reports to masquerade as safe.
    if not re.fullmatch(r"\d+(?:-\d+)?/(tcp|udp)", container_endpoint):
        return ("other", "unknown", "unknown")
    protocol = container_endpoint.rsplit("/", 1)[-1]
    host, separator, port = host_endpoint.rpartition(":")
    if not separator or not re.fullmatch(r"\d+(?:-\d+)?", port):
        return (protocol, "unknown", "unknown")
    host = host.removeprefix("[").removesuffix("]")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return (protocol, "unknown", "unknown")
    family = "ipv4" if ip.version == 4 else "ipv6"
    return (protocol, family, common.bind_scope(ip))


def summarize(lines):
    bindings = {
        family: {
            protocol: {scope: 0 for scope in SCOPES}
            for protocol in PROTOCOLS
        }
        for family in ("ipv4", "ipv6", "unknown")
    }
    containers, mapped, exposed_only = 0, 0, 0
    for line in lines.splitlines():
        containers += 1
        try:
            ports = json.loads(line)
        except (ValueError, TypeError):
            return None
        if not isinstance(ports, str):
            return None
        for part in ports.split(", "):
            if not part:
                continue
            parsed = scope_for_segment(part)
            if parsed is None:
                exposed_only += 1
                continue
            protocol, family, scope = parsed
            bindings[family][protocol][scope] += 1
            mapped += 1
    return {
        "running_containers_reported": containers,
        "published_binding_segments": mapped,
        "exposed_only_segments": exposed_only,
        "published_bindings": bindings,
        "count_unit": "docker_ps_formatted_segments_not_distinct_port_numbers",
    }


def inspect(executor=None):
    result = {
        "schema": SCHEMA,
        "daemon_access_requested": True,
        "status": "error",
        "summary": None,
        "effective_reachability": "not_verified",
        "limitations": [
            "Docker daemon access is root-equivalent on many hosts.",
            "This fixed Docker CLI command reads local container metadata only.",
            "No Docker container names, identifiers, host IPs or port numbers"
            " are reported.",
            "Docker formatted port ranges count as segments, not unique ports.",
            "Published ports alone do not prove LAN/WAN reachability.",
            "No Docker privileges, group membership or sudoers were modified.",
        ],
    }
    if os.geteuid() == 0:
        result["status"] = "refused_root"
        return result
    # The fixed environment carries no DOCKER_HOST: only ARGV selects the daemon.
    status, raw = common.run_fixed(ARGV, timeout=6, max_bytes=MAX_BYTES,
                                   executor=executor)
    if status != "ok":
        result["status"] = "unavailable" if status == "failed" else (
            common.public_status(status))
        return result
    summary = summarize(raw)
    if summary is not None:
        result["status"] = "ok"
        result["summary"] = summary
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ack-docker-socket-read", action="store_true",
                        help="explicitly permit the root-equivalent local daemon query")
    args = parser.parse_args(argv)
    if not args.ack_docker_socket_read:
        parser.error("explicit --ack-docker-socket-read required")
    if os.geteuid() == 0:
        parser.error("never run this Python script with root or sudo")
    common.emit(inspect())


if __name__ == "__main__":
    main()
