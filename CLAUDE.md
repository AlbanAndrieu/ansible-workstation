# Claude Code adapter — ansible-workstation

`AGENTS.md` is canonical. Load
`docs/agent-execution-modes.md` only for host/runtime work.
This repo configures **Ubuntu OS**; OpenClaw Gateway, dotfiles,
YubiKey secrets and TrueNAS applications are owned elsewhere.

On verified Ubuntu Workstation, prefer existing `mise` tasks and
targeted unit tests. Use read-only audits; never use the mutable
`playbooks/workstation.yml` to check host state. Do not run sudo,
install packages, change PAM/DNS/systemd/firewall or touch hardware
as incidental validation. One local `mise run quality` at publication,
not in every diagnostic loop.

If running in remote Codex/API-only mode, restrict work to
source/tests/docs and hermetic validation available to the agent.
Mark Workstation/TrueNAS/hardware checks **NOT_RUN**. Do not claim
CLI or live-host access, and do not use CI as a substitute. Open
a Draft PR; never merge without approval.

Load only the matching `.agents/skills/<name>/SKILL.md`.
The symlinks under `.claude/skills` refer to the same vendored
content; do not duplicate them.
