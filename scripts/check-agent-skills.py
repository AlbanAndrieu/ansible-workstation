#!/usr/bin/env python3
"""Read-only offline contract for repo-scoped, vendored Ansible agent skills.

This validates layout, provenance metadata and local policy. The skills CLI's
computedHash is treated as provenance *metadata*; it is NOT a SHA256 of SKILL.md
and this check does not claim to reproduce or attest that hash.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "akin-ozer/cc-devops-skills"
EXPECTED = {
    "ansible-generator": "devops-skills-plugin/skills/ansible-generator/SKILL.md",
    "ansible-validator": "devops-skills-plugin/skills/ansible-validator/SKILL.md",
}
ALIASES = {
    ".claude/skills": "../../.agents/skills",
    ".hermes/skills": "../../.agents/skills",
    "skills": "../.agents/skills",
}
POLICIES = {
    "AGENTS.md": (
        "## Workstation skill precedence",
        ("ansible-workstation", "project policy", "external skills", "explicit approval"),
    ),
    "docs/agent-skills-workstation.md": (
        "## Security boundary",
        ("read-only", "PAM", "DNS", "secrets", "no automatic apply"),
    ),
}


def scoped_section(content: str, heading: str) -> str:
    lines = content.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        return ""
    for end in range(start + 1, len(lines)):
        if lines[end].startswith("## "):
            return "\n".join(lines[start:end])
    return "\n".join(lines[start:])


def audit(root: Path) -> tuple[str, list[str]]:
    issues: list[str] = []
    for relative, (heading, markers) in POLICIES.items():
        path = root / relative
        try:
            section = scoped_section(path.read_text(encoding="utf-8"), heading)
        except (OSError, UnicodeError):
            issues.append(f"{relative}: policy missing or unreadable")
            continue
        if not section:
            issues.append(f"{relative}: policy section missing")
            continue
        for marker in markers:
            if marker not in section:
                issues.append(f"{relative}: policy marker missing: {marker}")

    lock = root / "skills-lock.json"
    if not lock.is_file() or lock.is_symlink():
        if lock.exists() or lock.is_symlink():
            issues.append("skills-lock.json: not a regular file")
        for name in EXPECTED:
            if (root / ".agents/skills" / name).exists():
                issues.append(f"{name}: installed without skills-lock.json")
        return "not_installed", issues

    try:
        manifest = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return "invalid_manifest", issues + ["skills-lock.json: unreadable or invalid JSON"]

    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        return "invalid_manifest", issues + ["skills-lock.json: unsupported schema"]
    skills = manifest.get("skills")
    if not isinstance(skills, dict):
        return "invalid_manifest", issues + ["skills-lock.json: missing skills mapping"]

    declared = set(skills)
    for name in sorted(declared - set(EXPECTED)):
        issues.append(f"{name}: unreviewed skill in manifest")
    for name, source_path in EXPECTED.items():
        if name not in skills:
            issues.append(f"{name}: missing from manifest")
            continue
        metadata = skills[name]
        if not isinstance(metadata, dict):
            issues.append(f"{name}: invalid metadata")
            continue
        if (metadata.get("source"), metadata.get("sourceType"), metadata.get("skillPath")) != (
            SOURCE, "github", source_path
        ):
            issues.append(f"{name}: provenance mismatch")
        digest = metadata.get("computedHash")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            issues.append(f"{name}: missing or malformed computedHash")
        canonical = root / ".agents/skills" / name
        if canonical.is_symlink() or not (canonical / "SKILL.md").is_file():
            issues.append(f"{name}: canonical SKILL.md missing or redirected")
        for prefix, relative_base in ALIASES.items():
            link = root / prefix / name
            expected_link = f"{relative_base}/{name}"
            if not link.is_symlink():
                issues.append(f"{prefix}/{name}: expected symlink missing")
                continue
            try:
                target = os.readlink(link)
                resolved = link.resolve(strict=False)
                expected_path = canonical.resolve(strict=False)
            except (OSError, RuntimeError):
                issues.append(f"{prefix}/{name}: symlink unreadable")
                continue
            if target != expected_link or resolved != expected_path:
                issues.append(f"{prefix}/{name}: symlink target mismatch")

    return "installed", issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    state, issues = audit(args.root)
    print(json.dumps({
        "schema": "workstation-agent-skills-policy/v1",
        "read_only": True,
        "installation": state,
        "reviewed_skills": sorted(EXPECTED),
        "computed_hash_verification": "metadata_format_only",
        "status": "drift" if issues else "pass",
        "issues": issues,
    }, sort_keys=True))
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
