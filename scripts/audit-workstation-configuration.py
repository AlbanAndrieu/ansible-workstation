#!/usr/bin/env python3
"""Read-only, redacted workstation DNS/systemd/etc drift audit.

No sudo, no reading /etc file contents or systemd Environment/ExecStart,
no sockets besides opt-in DNS resolution via getent/dig.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ETC_PATHS = (
    "NetworkManager/NetworkManager.conf",
    "NetworkManager/conf.d",
    "NetworkManager/dispatcher.d",
    "systemd/resolved.conf",
    "systemd/resolved.conf.d",
    "systemd/system",
    "systemd/logind.conf",
    "systemd/journald.conf",
    "ssh/sshd_config",
    "ssh/sshd_config.d",
    "sysctl.conf",
    "sysctl.d",
    "modprobe.d",
    "modules-load.d",
    "nftables.conf",
    "ufw",
    "fail2ban",
    "apparmor.d",
    "apt/apt.conf.d",
    "sudoers.d",
    "fstab",
    "crypttab",
    "docker/daemon.json",
    "containerd/config.toml",
)
USER_UNITS = ("openclaw-gateway.service",)
SYSTEM_UNITS = (
    "NetworkManager.service", "systemd-resolved.service",
    "ssh.service", "docker.service", "containerd.service",
    "fail2ban.service", "ufw.service",
)
ALLOWED_SYSTEMD_KEYS = ("LoadState", "ActiveState", "UnitFileState")
PRIVATE_DOMAIN = "~int.albandrieu.com"
EXPECTED_DNS = "172.17.0.1"


def run(argv: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, check=False,
                           stdin=subprocess.DEVNULL, timeout=timeout)
        return p.returncode, p.stdout[:8192] if p.returncode == 0 else ""
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 127, ""


def inventory(root: Path) -> dict[str, str]:
    """Metadata only: never traverse or read potentially private configuration."""
    result = {}
    for name in ETC_PATHS:
        entry = root / name
        if entry.is_symlink():
            status = "symlink_review_required"
        elif entry.is_dir():
            status = "directory_present_review_required"
        elif entry.is_file():
            status = "file_present_review_required"
        else:
            status = "absent_or_inaccessible"
        result[name] = status
    return result


def unit_status(name: str, user: bool) -> dict[str, str]:
    argv = ["systemctl"] + (["--user"] if user else []) + ["show", name]
    for key in ALLOWED_SYSTEMD_KEYS:
        argv += ["-p", key]
    rc, output = run(argv)
    fields = {}
    if rc == 0:
        for line in output.splitlines():
            key, sep, value = line.partition("=")
            if sep and key in ALLOWED_SYSTEMD_KEYS and re.fullmatch(r"[a-z-]{1,40}", value):
                fields[key] = value
    return {key: fields.get(key, "unknown") for key in ALLOWED_SYSTEMD_KEYS}


def audit_dns(interface: str) -> dict[str, object]:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,32}", interface):
        raise ValueError("invalid interface")
    rc_dns, dns = run(["resolvectl", "dns", interface])
    rc_domain, domain = run(["resolvectl", "domain", interface])
    rc_nm, nm = run(["nmcli", "-g", "IP4.DNS", "device", "show", interface])
    # Token comparisons, not substring matching on arbitrary addresses.
    ip_tokens = re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", dns)
    domain_tokens = domain.split()
    effective = rc_dns == 0 and EXPECTED_DNS in ip_tokens and set(ip_tokens) == {EXPECTED_DNS}
    route_only = rc_domain == 0 and PRIVATE_DOMAIN in domain_tokens
    return {
        "interface": interface,
        "resolved_link_dns": "expected" if effective else "drift_or_unverified",
        "private_route_domain": "expected" if route_only else "drift_or_unverified",
        "networkmanager_dns": "observed" if rc_nm == 0 and bool(nm.strip()) else "unverified",
        "dns_resolution": "not_tested",
    }


def audit() -> dict[str, object]:
    home = Path.home()
    return {
        "schema": "workstation-configuration-drift/v1",
        "read_only": True,
        "etc": inventory(Path("/etc")),
        "system_units": {u: unit_status(u, False) for u in SYSTEM_UNITS},
        "user_units": {u: unit_status(u, True) for u in USER_UNITS},
        "openclaw_effective_execstart_alignment": "not_verified",
        "openclaw_legacy_template": "blocked_do_not_apply",
        "dns": audit_dns("eno1"),
        "etc_contents_captured": False,
        "credentials_read": False,
        "home_directory_inspected": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print redacted JSON report")
    args = parser.parse_args()
    result = audit()
    print(json.dumps(result, sort_keys=True, indent=2 if args.json else None))
    # Unknowns are informative; report is not a pass for DNS or runtime unit parity.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
