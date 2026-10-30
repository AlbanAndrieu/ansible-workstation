#!/usr/bin/env python3
"""Explicit, non-root, local Docker publication visibility: counters only.

WARNING: Access to Docker daemon grants root-equivalent control on many hosts.
Runs only a fixed read command after explicit acknowledgment. Never enables
Docker privileges, starts/stops containers, or prints any port/address/name.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess

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
    if ip.is_unspecified:
        scope = "wildcard"
    elif ip.is_loopback:
        scope = "loopback"
    else:
        scope = "interface_specific"
    return (protocol, family, scope)


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
            "No Docker container names, identifiers, host IPs or port numbers are reported.",
            "Docker formatted port ranges count as segments, not unique ports.",
            "Published ports alone do not prove LAN/WAN reachability.",
            "No Docker privileges, group membership or sudoers were modified.",
        ],
    }
    if os.geteuid() == 0:
        result["status"] = "refused_root"
        return result
    if not Path(DOCKER).is_file():
        result["status"] = "missing"
        return result
    if executor is None:
        executor = subprocess.run
    try:
        response = executor(
            ARGV, input="", capture_output=True, text=True,
            timeout=6, check=False,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
    except subprocess.TimeoutExpired:
        result["status"] = "timed_out"
        return result
    except (OSError, ValueError):
        return result
    if response.returncode:
        info = (response.stderr or "").lower()
        result["status"] = "access_denied" if (
            "permission denied" in info or "connect: permission" in info
        ) else "unavailable"
        return result
    raw = response.stdout or ""
    if len(raw.encode("utf-8")) > MAX_BYTES:
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
    print(json.dumps(inspect(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
