# Ansible skills: repository-local provenance and precedence

The skills `ansible-generator` and `ansible-validator` originate from
[akin-ozer/cc-devops-skills](https://github.com/akin-ozer/cc-devops-skills).
They are third-party reference material, not approved automation.

## Security boundary

The `agent-skills-check` contract is **read-only** and runs offline with the
Python standard library. It checks the expected source metadata, presence of
`SKILL.md`, manifest hash formatting and exact symlink targets. It never
executes external skill scripts or reads system **secrets**.

**PAM**, YubiKey PIN/PUK/PIV, **DNS**, sudo, firewall, systemd and network
changes require explicit operator approval and separate local checks: **no automatic apply**.
Never run the old `workstation.yml` for auditing. Do not treat skill examples
with passwords, permissive firewall defaults or automatic package updates as
workstation configuration.

The lockfile's `computedHash` is produced by the external skills installer.
Its format is checked; this audit does NOT prove its cryptographic relation to
the skill tree. Review upstream source, the exact diff and the installer
provenance before approving any skill update.

## Layout

- Canonical source: `.agents/skills/ansible-generator/` and
  `.agents/skills/ansible-validator/`.
- Reproducibility metadata: `skills-lock.json` (version 1).
- Symlink aliases:
  `.claude/skills/<name>` and `.hermes/skills/<name>` resolve to
  `../../.agents/skills/<name>`;
  `skills/<name>` resolves to `../.agents/skills/<name>`.
- Both skills are pinned in this repository: a missing lockfile is a
  **blocking drift**, including when the vendor directory is missing. A
  fresh clone must contain the lockfile, canonical directories and all
  six links. No implicit installation is attempted.

Do not duplicate installed skill contents under the alias directories, and do
not commit caches, personal settings, keys or `.env` files.

## Local verification

```bash
cd /workspace/users/albandrieu30/ansible-workstation
mise run agent-skills-check
.venv/bin/python -B -m unittest tests/test_agent_skills_contract.py -v
```

Run both after updating the vendor skills and before committing. Keep
`detect-private-key` and Gitleaks/Betterleaks active. Exclude vendored third-
party files from *auto-formatters* only, not security scanners. Review false
positives by exact file, rule and example before adding any suppression.

This is a source-contract gate, not a CI pass, a systemd readiness check or a
rebase verifier. No sudo, network calls, package installation or deployment.
