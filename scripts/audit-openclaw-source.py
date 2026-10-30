#!/usr/bin/env python3
"""Read-only, bounded, redacted OpenClaw source audit on Ubuntu workstation.

This script does NOT prove effective systemd ExecStart/node alignment or model
readiness. Those require separate runtime probes in Compose until migrated.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policies/openclaw-source-audit.json"


def run(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           check=False, timeout=6)
        return p.returncode, p.stdout[:512] if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return 127, ""


def major(stdout):
    hit = re.fullmatch(r"v?(\d+)(?:\.\d+){1,2}", stdout.strip())
    return int(hit.group(1)) if hit else None


def audit(home=None):
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy["target_host"] != "truenas" or policy["source_host"] != "workstation":
        raise ValueError("ownership_policy_invalid")
    if policy["no_apply"] is not True:
        raise ValueError("source_must_be_readonly")
    home = home or Path.home()
    rc, version = run(["midclt", "call", "system.version"])
    if rc == 0 and version.strip().strip('"').startswith("TrueNAS-"):
        return {"schema":policy["schema"], "host":"truenas",
                "source_audit":"wrong_host_no_runtime_inference", "read_only":True,
                "target":"truenas_not_examined"}
    if not (home / ".openclaw" / "openclaw.json").is_file():
        return {"schema":policy["schema"], "host":"unverified",
                "source_audit":"source_profile_unverified", "read_only":True,
                "target":"truenas_not_examined"}

    rc, unit = run(["systemctl", "--user", "show", policy["source_unit"],
                    "-p", "LoadState", "-p", "ActiveState"])
    fields = {}
    if rc == 0:
        for line in unit.splitlines():
            if line.count("=") == 1:
                k,v = line.split("=",1)
                if k in ("LoadState","ActiveState") and re.fullmatch("[a-z-]{1,30}",v):
                    fields[k]=v
    nrc, node = run(["node","--version"])
    orc, openclaw = run(["openclaw","--version"])
    version_seen = bool(orc == 0 and re.search(
        r"(?<!\d)" + re.escape(policy["expected_openclaw_cli_version"]) + r"(?!\d)", openclaw))
    node_seen = nrc == 0 and major(node) == policy["expected_node_major"]
    unit_seen = fields.get("LoadState")=="loaded" and fields.get("ActiveState")=="active"
    verdict = "source_cli_and_unit_observed" if node_seen and version_seen and unit_seen else "source_drift_or_unverified"
    # No shell paths, raw versions, unit body, environment, tokens, identities.
    return {"schema":policy["schema"], "host":"workstation",
            "source_audit":verdict, "read_only":True,
            "node_cli_major":"expected" if node_seen else "drift_or_unverified",
            "openclaw_cli_version":"expected" if version_seen else "drift_or_unverified",
            "gateway_user_unit":"active_observed" if unit_seen else "inactive_or_unverified",
            "effective_gateway_execstart":"not_verified",
            "gateway_http_readiness":"not_tested",
            "target":"truenas_not_examined",
            "model_requests":0}


def main():
    try:
        result = audit()
    except (OSError, ValueError, KeyError, UnicodeError):
        result = {"source_audit":"configuration_unverified", "read_only":True}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("source_audit")=="source_cli_and_unit_observed" else 2


if __name__=="__main__":
    raise SystemExit(main())
