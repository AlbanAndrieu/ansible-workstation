#!/usr/bin/env python3
"""Read-only, bounded, redacted OpenClaw source audit on Ubuntu workstation.

This script does NOT prove effective systemd ExecStart/node alignment or model
readiness. Those require separate runtime probes in Compose until migrated.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import re

_COMMON = importlib.util.spec_from_file_location(
    "audit_common", Path(__file__).with_name("audit_common.py"))
common = importlib.util.module_from_spec(_COMMON)
_COMMON.loader.exec_module(common)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policies/openclaw-source-audit.json"


def run(argv):
    # Inherited environment: node/openclaw are mise-managed and systemctl --user
    # needs the session bus. Output above 512 bytes is refused, not truncated.
    status, out = common.run_fixed(argv, timeout=6, max_bytes=512, env=None)
    return (0, out) if status == "ok" else (127, "")


def major(stdout):
    hit = re.fullmatch(r"v?(\d+)(?:\.\d+){1,2}", stdout.strip())
    return int(hit.group(1)) if hit else None


def _report(policy, host, verdict, **observed):
    """Fixed-key report: no paths, raw versions, unit body, env or identities."""
    return {"schema": policy["schema"], "host": host, "source_audit": verdict,
            "read_only": True, "target": "truenas_not_examined", **observed}


def _unit_states(unit_name):
    rc, unit = run(["/usr/bin/systemctl", "--user", "show", unit_name,
                    "-p", "LoadState", "-p", "ActiveState"])
    fields = {}
    if rc == 0:
        for line in unit.splitlines():
            key, sep, value = line.partition("=")
            if (sep and "=" not in value and key in ("LoadState", "ActiveState")
                    and re.fullmatch("[a-z-]{1,30}", value)):
                fields[key] = value
    return fields


def audit(home=None):
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy["target_host"] != "truenas" or policy["source_host"] != "workstation":
        raise ValueError("ownership_policy_invalid")
    if policy["no_apply"] is not True:
        raise ValueError("source_must_be_readonly")
    home = home or Path.home()
    rc, version = run(["midclt", "call", "system.version"])
    if rc == 0 and version.strip().strip('"').startswith("TrueNAS-"):
        return _report(policy, "truenas", "wrong_host_no_runtime_inference")
    if not (home / ".openclaw" / "openclaw.json").is_file():
        return _report(policy, "unverified", "source_profile_unverified")

    fields = _unit_states(policy["source_unit"])
    nrc, node = run(["node", "--version"])
    orc, openclaw = run(["openclaw", "--version"])
    expected_cli = re.escape(policy["expected_openclaw_cli_version"])
    version_seen = bool(
        orc == 0 and re.search(r"(?<!\d)" + expected_cli + r"(?!\d)", openclaw)
    )
    node_seen = nrc == 0 and major(node) == policy["expected_node_major"]
    unit_seen = (fields.get("LoadState") == "loaded"
                 and fields.get("ActiveState") == "active")
    observed = node_seen and version_seen and unit_seen
    return _report(
        policy, "workstation",
        "source_cli_and_unit_observed" if observed else "source_drift_or_unverified",
        node_cli_major="expected" if node_seen else "drift_or_unverified",
        openclaw_cli_version="expected" if version_seen else "drift_or_unverified",
        gateway_user_unit="active_observed" if unit_seen else "inactive_or_unverified",
        effective_gateway_execstart="not_verified",
        gateway_http_readiness="not_tested",
        model_requests=0,
    )


def main():
    try:
        result = audit()
    except (OSError, ValueError, KeyError, UnicodeError):
        result = {"source_audit": "configuration_unverified", "read_only": True}
    common.emit(result, indent=None)
    return 0 if result.get("source_audit") == "source_cli_and_unit_observed" else 2


if __name__=="__main__":
    raise SystemExit(main())
