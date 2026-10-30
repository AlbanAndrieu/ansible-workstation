#!/usr/bin/env python3
"""Read-only guard against deploying stale legacy OpenClaw systemd template."""
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates/openclaw-gateway-systemd.sh-Ubuntu.j2"

def inspect(mise_text, template_text):
    config = tomllib.loads(mise_text)
    intended = str(config.get("tools",{}).get("node", ""))
    pinned = sorted(set(re.findall(r"/mise/installs/node/(\d+(?:\.\d+){0,2})/", template_text)))
    # Template is explicitly legacy and must not be applied just because a
    # version now coincides. Promote via a new independently-reviewed task.
    out = {"schema":"workstation-openclaw-template-safety/v1",
           "no_mutation":True, "template_legacy":True,
           "mise_node_major_present":bool(re.fullmatch(r"\d+(?:\.\d+){0,2}",intended)),
           "template_node_major_match":bool(pinned and
             all(x.split(".")[0]==intended.split(".")[0] for x in pinned)),
           "template_has_hardcoded_runtime":bool(pinned)}
    return out

def main():
    import json
    try:
        facts=inspect((ROOT/"mise.toml").read_text(encoding="utf-8"),
                      TEMPLATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("template_audit=unverified")
        return 2
    print(json.dumps(facts,sort_keys=True))
    print("template_apply=blocked_legacy_requires_review")
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
