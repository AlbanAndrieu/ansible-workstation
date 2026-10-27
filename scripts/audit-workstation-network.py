#!/usr/bin/env python3
"""Read-only, unprivileged packet-filter visibility audit for local Ubuntu.

Output contains only aggregate policies and observation statuses, never rules,
addresses, ports, interfaces, system identities or Docker socket information.
An unprivileged failure is UNKNOWN, not evidence of an empty firewall.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

SCHEMA = "workstation-network-filter-audit/v1"
COMMANDS = {
    "nft": ("/usr/sbin/nft", "-j", "list", "ruleset"),
    "iptables": ("/usr/sbin/iptables-save", "-t", "filter"),
    "ip6tables": ("/usr/sbin/ip6tables-save", "-t", "filter"),
}
POLICIES = {"accept", "drop", "reject"}
HOOKS = {"input", "forward", "output"}
FAMILIES = {"ip", "ip6", "inet"}
BUILTIN_CHAINS = ("INPUT", "FORWARD", "OUTPUT")
ERROR_STATUSES = {"access_denied", "missing", "timed_out", "error"}
LIMITS = [
    "Unprivileged probes may be access_denied; that is not an empty ruleset.",
    "No sudo, Docker socket, Docker daemon change or rule modification.",
    "No addresses, ports, interfaces, identities or raw rules are printed.",
    "A policy summary cannot prove exposure or effective firewall protection.",
    "Docker can use iptables or nftables; UFW/systemd state is insufficient.",
]


def forwarding_state(path):
    try:
        raw = Path(path).read_text(errors="replace").strip()
    except (OSError, ValueError):
        return "unknown"
    return {"0": "disabled", "1": "enabled"}.get(raw, "unknown")


def run_probe(name):
    argv = COMMANDS[name]
    if not Path(argv[0]).is_file():
        return "missing", ""
    try:
        result = subprocess.run(
            argv, input="", text=True, capture_output=True, timeout=4,
            check=False, env={"LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/bin"},
        )
    except subprocess.TimeoutExpired:
        return "timed_out", ""
    except (OSError, ValueError):
        return "error", ""
    if result.returncode == 0:
        return "ok", result.stdout[:1024 * 1024]
    error = (result.stderr + result.stdout[:256]).lower()
    denied = (
        "permission denied", "operation not permitted", "must be root",
        "requires root", "not permitted", "permission error",
        "you must be root",
    )
    return ("access_denied" if any(x in error for x in denied) else "error"), ""


def _policy(raw):
    value = str(raw).lower()
    return value if value in POLICIES else "unknown"


def parse_nft(raw):
    """Only output filter base-chain policies and aggregate rule counts."""
    try:
        root = json.loads(raw)
        objects = root["nftables"]
        if not isinstance(objects, list):
            raise ValueError("invalid nft result")
    except (ValueError, KeyError, TypeError):
        return None
    chains, rules = [], 0
    docker_tables = False
    for entry in objects:
        if not isinstance(entry, dict):
            continue
        table = entry.get("table")
        if isinstance(table, dict) and str(table.get("name", "")).startswith("docker"):
            docker_tables = True
        chain = entry.get("chain")
        if isinstance(chain, dict):
            family = chain.get("family")
            hook = chain.get("hook")
            if (
                chain.get("type") == "filter"
                and family in FAMILIES and hook in HOOKS
            ):
                chains.append({
                    "family": family, "hook": hook,
                    "policy": _policy(chain.get("policy", "unknown")),
                })
        if isinstance(entry.get("rule"), dict):
            rules += 1
    return {
        "filter_base_chains": sorted(
            chains, key=lambda x: (x["family"], x["hook"], x["policy"])
        )[:32],
        "total_rules_seen": rules,
        "docker_table_present": docker_tables,
        "truncated_policy_list": len(chains) > 32,
    }


def parse_iptables(raw):
    """Accept only builtin filter policies and Docker-chain presence."""
    policies = {name: "unknown" for name in BUILTIN_CHAINS}
    docker_user = docker_chain = False
    count = 0
    for line in raw.splitlines():
        match = re.fullmatch(r":(INPUT|FORWARD|OUTPUT) (ACCEPT|DROP|REJECT) \[\d+:\d+\]", line)
        if match:
            policies[match.group(1)] = _policy(match.group(2))
        if line.startswith(":DOCKER-USER ") or line.startswith("-N DOCKER-USER"):
            docker_user = True
        if line.startswith(":DOCKER ") or line.startswith("-N DOCKER"):
            docker_chain = True
        if line.startswith("-A "):
            count += 1
    if not raw.strip():
        return None
    return {
        "builtin_policies": policies,
        "filter_rules_seen": count,
        "docker_chain_present": docker_chain,
        "docker_user_chain_present": docker_user,
    }


def inspect(probe=run_probe):
    result = {
        "schema": SCHEMA,
        "ip_forward": {
            "ipv4": forwarding_state("/proc/sys/net/ipv4/ip_forward"),
            "ipv6": forwarding_state("/proc/sys/net/ipv6/conf/all/forwarding"),
        },
        "firewall_probes": {},
        "effective_filtering": "not_verified",
        "docker_socket_queried": False,
        "limitations": LIMITS,
    }
    for name in COMMANDS:
        state, output = probe(name)
        summary = parse_nft(output) if name == "nft" else parse_iptables(output)
        if state == "ok" and summary is None:
            state = "error"
        result["firewall_probes"][name] = {
            "status": state if state in ERROR_STATUSES | {"ok"} else "error",
            "summary": summary if state == "ok" else None,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "summary"), default="summary")
    args = parser.parse_args()
    data = inspect()
    if args.format == "json":
        print(json.dumps(data, indent=2, sort_keys=True))
        return
    print("NETWORK FILTER VISIBILITY — read only; effective filtering NOT VERIFIED")
    print("IP forwarding:", data["ip_forward"])
    for name, report in data["firewall_probes"].items():
        print(name + ":", report["status"])
        if report["summary"] is not None:
            print(json.dumps(report["summary"], sort_keys=True))
    print("No raw rules, addresses, ports, or Docker socket access.")


if __name__ == "__main__":
    main()
