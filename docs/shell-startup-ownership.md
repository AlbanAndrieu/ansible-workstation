# Workstation provisioning vs. interactive shell ownership

This repository provisions Ubuntu/Debian workstation packages and services with
Ansible. It does **not** run at every Terminator tab or Bash startup.

Config ownership:
- `ansible-workstation`: package/service provisioning, local SCM tools.
- `dotfiles`: `~/.bashrc`, Starship, Terminator profile and fallback prompt.
- `nabla`: `env/home/dev.env.sh` and optional Vaultwarden environment.

## Safe SCM provisioning

`scm_enabled` defaults to false. The myrepos package is installed only if the
SCM feature is enabled. Bulk repository registration is also **disabled by default**,
and is never executed with root privileges. This avoids writing myrepos
configuration as root or traversing the user's workspace unexpectedly.

To explicitly opt in during a trusted, reviewed workstation provisioning run:

```yaml
scm_enabled: true
workstation_myrepos_autoregister_enabled: true
workstation_myrepos_root: /workspace/users/albandrieu30
```

Registration remains a provisioning operation, not a Bash startup hook. Repeated
registration could still update per-user configuration; avoid enabling it in
routine unattended playbook runs.

## Shell startup regression (2026-10-24)

Three interactive Bash tests with network access averaged 5.65 s after opt-in
credential loading. Before that change, three tests requiring a Bitwarden unlock
averaged 19.05 s. Offline Bash still stalled, and after reconnection an attempt
to write `~/.gitconfig` failed because a lock already existed.

Direct causes found in the two shell repos:
- Nabla: active `git config --global user.name/user.email` at each Bash start.
- Nabla: `wget` downloading Kubernetes aliases on first shell start.
- Dotfiles: `git-radar --bash --fetch` in fallback PS1.

Fixes belong to **Nabla PR #68** and **dotfiles PR #1**, not Ansible tasks.
Do not delete `~/.gitconfig.lock` without checking for an active Git process.

## Local verification (no CI or secrets)

```bash
python3 -m unittest discover -s tests -p 'test_git_provisioning_contract.py' -v
ansible-playbook --syntax-check playbooks/workstation.yml
```

Syntax-check requires local Ansible collections/roles to be installed; it does
not apply the playbook. **Do not run the full role just to test shell startup.**
The broader `tasks/security.yml` includes unconditional firewall and Tailscale
configuration that needs separate review before applying it to a live workstation.
