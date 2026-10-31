#!/usr/bin/env python3
"""Read-only, redacted workstation DNS/systemd/etc drift audit.

No sudo, no reading /etc file contents or systemd Environment/ExecStart,
no sockets besides opt-in DNS resolution via getent/dig. Observations are
compared to the declared policies/home-desktop.yml; only outcomes are printed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
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
USER_UNITS = ("openclaw-gateway.service", "litellm.service", "reactive.service")
SYSTEM_UNITS = (
    "NetworkManager.service", "systemd-resolved.service",
    "ssh.service", "docker.service", "containerd.service",
    "fail2ban.service", "ufw.service",
    "boot-ip.service", "boot-update.service", "hide-location.service",
    "hide-mac.service", "conky.service", "maj0.service",
)
ALLOWED_SYSTEMD_KEYS = ("LoadState", "ActiveState", "UnitFileState")
METADATA_SYSTEMD_KEYS = ("FragmentPath", "DropInPaths")
PRIVATE_DOMAIN = "~int.albandrieu.com"
EXPECTED_DNS = "172.17.0.1"
DNS_INTERFACE = "eno1"

POLICY_SCHEMA = "workstation-os-policy/v1"
DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "policies/home-desktop.yml"
POLICY_KEYS = {"schema", "profile", "dns", "etc_paths", "system_units",
               "user_units", "never_capture"}
LEVELS = ("required", "baseline", "review")
# Policy kinds map onto inventory() statuses; symlinks are never followed.
ETC_KINDS = {
    "file": "file_present_review_required",
    "directory": "directory_present_review_required",
    "absent": "absent_or_inaccessible",
}
STATE = re.compile(r"[a-z-]{1,40}")


class PolicyError(ValueError):
    """Fixed-text policy failure: never echoes file content."""


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


def _source_category(fragment: str, user: bool) -> str:
    """Allowlist source *categories*, not paths or systemd Environment values."""
    if not fragment or "\n" in fragment or "\r" in fragment:
        return "unknown"
    if user and fragment.startswith(str(Path.home() / ".config/systemd/user") + "/"):
        return "user_config"
    prefixes = (
        ("/etc/systemd/user/" if user else "/etc/systemd/system/", "etc"),
        ("/run/systemd/user/" if user else "/run/systemd/system/", "runtime"),
        ("/usr/lib/systemd/user/" if user else "/usr/lib/systemd/system/", "vendor"),
        ("/lib/systemd/user/" if user else "/lib/systemd/system/", "vendor"),
    )
    for prefix, category in prefixes:
        if fragment.startswith(prefix):
            return category
    return "other_review_required"


def unit_status(name: str, user: bool) -> dict[str, str]:
    # Never request ExecStart, Environment or EnvironmentFile.
    argv = ["systemctl"] + (["--user"] if user else []) + ["show", name]
    for key in ALLOWED_SYSTEMD_KEYS + METADATA_SYSTEMD_KEYS:
        argv += ["-p", key]
    rc, output = run(argv)
    fields: dict[str, str] = {}
    if rc == 0:
        for line in output.splitlines():
            key, sep, value = line.partition("=")
            if not sep or key not in ALLOWED_SYSTEMD_KEYS + METADATA_SYSTEMD_KEYS:
                continue
            if key in ALLOWED_SYSTEMD_KEYS:
                if re.fullmatch(r"[a-z-]{1,40}", value):
                    fields[key] = value
            else:
                # Values are kept in memory only, never returned to the caller.
                fields[key] = value
    result = {key: fields.get(key, "unknown") for key in ALLOWED_SYSTEMD_KEYS}
    result["fragment_source"] = (
        _source_category(fields.get("FragmentPath", ""), user) if rc == 0 else "unknown"
    )
    result["dropins"] = (
        ("present_review_required" if fields["DropInPaths"] else "none")
        if rc == 0 and "DropInPaths" in fields else "unknown"
    )
    result["effective_execstart_alignment"] = "not_verified"
    return result


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
        # Separates a failed probe (unknown) from an observed drift.
        "link_probes": {
            "dns": "ok" if rc_dns == 0 else "failed",
            "domain": "ok" if rc_domain == 0 else "failed",
        },
    }


def _entries(policy: dict, section: str, allowed: tuple[str, ...]) -> dict:
    entries = policy.get(section)
    if not isinstance(entries, dict) or set(entries) != set(allowed):
        # Exact coverage: a policy can neither skip nor add a probe.
        raise PolicyError(f"{section}: must list exactly the audited probes")
    for entry in entries.values():
        if not isinstance(entry, dict) or entry.get("level") not in LEVELS:
            raise PolicyError(f"{section}: invalid level")
        if entry["level"] != "review" and not (
            isinstance(entry.get("evidence"), str) and entry["evidence"].strip()
        ):
            raise PolicyError(f"{section}: non-review entry without evidence")
    return entries


def validate_policy(policy: object) -> dict:
    if not isinstance(policy, dict) or policy.get("schema") != POLICY_SCHEMA:
        raise PolicyError("unexpected policy schema")
    if not set(policy) <= POLICY_KEYS:
        raise PolicyError("unknown top-level policy key")
    dns = policy.get("dns")
    if not isinstance(dns, dict) or dns.get("level") not in LEVELS[:2] or (
        dns.get("interface"), dns.get("resolver"), dns.get("route_domain")
    ) != (DNS_INTERFACE, EXPECTED_DNS, PRIVATE_DOMAIN):
        raise PolicyError("dns: differs from the pinned LAN contract")
    for entry in _entries(policy, "etc_paths", ETC_PATHS).values():
        expect = entry.get("expect")
        known_kind = isinstance(expect, str) and expect in ETC_KINDS
        if (entry["level"] == "review") != (expect is None) or (
            expect is not None and not known_kind
        ):
            raise PolicyError("etc_paths: expect is required unless level is review")
    for section, units in (("system_units", SYSTEM_UNITS), ("user_units", USER_UNITS)):
        for entry in _entries(policy, section, units).values():
            states = [entry.get("active_state"), entry.get("unit_file_state")]
            if entry["level"] == "review":
                valid = states == [None, None]
            else:
                valid = isinstance(states[0], str) and bool(STATE.fullmatch(states[0]))
                valid = valid and (states[1] is None or (
                    isinstance(states[1], str) and bool(STATE.fullmatch(states[1]))
                ))
            if not valid:
                raise PolicyError(f"{section}: invalid expected unit state")
    never = policy.get("never_capture")
    if not isinstance(never, list) or not never or not all(
        isinstance(item, str) and item for item in never
    ):
        raise PolicyError("never_capture: must be a non-empty list")
    if any(path.startswith(prefix) for path in ETC_PATHS for prefix in never):
        raise PolicyError("never_capture: an audited path is forbidden")
    return policy


def load_policy(path: Path) -> dict:
    try:
        import yaml  # project .venv dependency; absent PyYAML fails closed
    except ImportError as exc:
        raise PolicyError("PyYAML unavailable; use the project .venv") from exc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PolicyError("policy unreadable or invalid YAML") from exc
    return validate_policy(data)


def _outcome(level: str, known: bool, matches: bool) -> str:
    if level == "review":
        return "review_required"
    if not known:
        return "unknown"
    return "expected" if matches else "drift"


def compare(report: dict, policy: dict) -> dict[str, object]:
    """Classify observations against the declared policy; outcomes only."""
    findings: dict[str, dict[str, str]] = {}
    for path, entry in policy["etc_paths"].items():
        observed = report["etc"].get(path, "unknown")
        known = observed in ETC_KINDS.values()
        matches = known and ETC_KINDS.get(entry.get("expect")) == observed
        findings[f"etc/{path}"] = {"level": entry["level"],
                                   "outcome": _outcome(entry["level"], known, matches)}
    for section in ("system_units", "user_units"):
        for unit, entry in policy[section].items():
            observed = report[section].get(unit, {})
            wanted = {"LoadState": "loaded", "ActiveState": entry.get("active_state")}
            if entry.get("unit_file_state") is not None:
                wanted["UnitFileState"] = entry["unit_file_state"]
            known = all(observed.get(key, "unknown") != "unknown" for key in wanted)
            matches = all(observed.get(key) == value for key, value in wanted.items())
            findings[f"{section}/{unit}"] = {
                "level": entry["level"],
                "outcome": _outcome(entry["level"], known, matches),
            }
    dns = report["dns"]
    probes = dns.get("link_probes", {})
    for name, field, probe in (("resolver", "resolved_link_dns", "dns"),
                               ("route_domain", "private_route_domain", "domain")):
        findings[f"dns/{name}"] = {
            "level": policy["dns"]["level"],
            "outcome": _outcome(policy["dns"]["level"], probes.get(probe) == "ok",
                                dns.get(field) == "expected"),
        }
    counts = Counter((f["level"], f["outcome"]) for f in findings.values())
    if counts[("required", "drift")]:
        status = "non_compliant"
    elif counts[("required", "unknown")]:
        status = "incomplete"
    elif counts[("baseline", "drift")] or counts[("baseline", "unknown")]:
        status = "changed_since_baseline"
    else:
        status = "conforms_to_declared_policy"
    return {
        "schema": POLICY_SCHEMA,
        "profile": policy.get("profile", "unknown"),
        "status": status,
        "counts": {
            outcome if level == "review" else f"{level}_{outcome}": n
            for (level, outcome), n in sorted(counts.items())
        },
        "findings": dict(sorted(findings.items())),
        "limitations": [
            "Declared policy drift only; not a security or firewall certification.",
            "Presence of an /etc path says nothing about its content.",
            "review_required entries carry no expectation and never pass.",
        ],
    }


def evaluate_policy(report: dict, path: Path) -> dict[str, object]:
    try:
        return compare(report, load_policy(path))
    except PolicyError as exc:
        return {"schema": POLICY_SCHEMA, "status": "invalid_policy", "error": str(exc)}


def audit() -> dict[str, object]:
    return {
        "schema": "workstation-configuration-drift/v1",
        "read_only": True,
        "etc": inventory(Path("/etc")),
        "system_units": {u: unit_status(u, False) for u in SYSTEM_UNITS},
        "user_units": {u: unit_status(u, True) for u in USER_UNITS},
        "openclaw_effective_execstart_alignment": "not_verified",
        "openclaw_legacy_template": "blocked_do_not_apply",
        "dns": audit_dns(DNS_INTERFACE),
        "etc_contents_captured": False,
        "credentials_read": False,
        "home_directory_inspected": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print redacted JSON report")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY,
                        help="Declared OS policy (default: policies/home-desktop.yml)")
    args = parser.parse_args()
    result = audit()
    result["policy"] = evaluate_policy(result, args.policy)
    print(json.dumps(result, sort_keys=True, indent=2 if args.json else None))
    # Unknowns are informative; report is not a pass for DNS or runtime unit parity.
    # Policy status is reported in JSON; exit code stays 0 (report, not a gate).
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
