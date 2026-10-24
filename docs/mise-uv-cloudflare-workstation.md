# Workstation toolchain and remote access — October 2026

Scope: **ansible-workstation PR #13**. The existing opt-in pfSense split-DNS
reconciliation is preserved; this work does not change the LAN configuration
or cloudflared secrets.

## Runtime ownership

| Layer | Source | Behavior |
| --- | --- | --- |
| Workstation packages/services | Ansible role | Host config; privileged tasks opt-in |
| CLI runtimes | `mise.toml` | Python 3.12, Node.js 24 LTS, uv |
| Python project dependencies | `pyproject.toml` / `uv.lock` | `uv sync` into checkout-local `.venv` |
| Shell/Starship | `dotfiles` + `nabla` | No installation, network fetch or secret unlock at startup |
| Tunnel config and tokens | External approved Cloudflare management | Never generated or read by this Ansible role |

**No live runtime install or dependency resolution occurs at shell startup.**
A `.venv` is kept in each worktree. uv's download cache can be shared across
worktrees; do not share an editable global Python environment.

### Operator workflow

Before running mise tasks, review `mise.toml`; mise config is executable
input and requires trust. Use only from a trusted workstation checkout.

```bash
cd ~/w/ansible-workstation
mise --version
mise install
mise exec -- uv --version
mise exec -- uv lock           # create/review uv.lock; commit after resolution
mise exec -- uv sync --locked  # creates a per-worktree .venv
mise run test-offline
mise run syntax                # only once dependencies/roles are available
```

No `uv.lock` is included yet because external dependency resolution has not
been validated on the workstation. **Do not use `uv sync --frozen` until
a reviewed lockfile is committed.** Prior `poetry.lock` and `Pipfile.lock`
remain for audit/rollback but are no longer the primary installation path.

Optional feature groups from the old Poetry configuration were rationalized:
API, deployment, encryption, telemetry, InfluxDB, notebook. Legacy Python 2,
obsolete build backends, global pip2 tools and old PyTorch/Temporal pins are not
automatically reinstalled. Validate dependent workflows before removal of the
older lockfiles.

Provisioning flags (default off):
```yaml
workstation_mise_uv_provision_enabled: false
workstation_legacy_asdf_enabled: false
workstation_legacy_python_enabled: false
workstation_legacy_nvm_enabled: false
```

When the workstation already has the expected mise binary, an **explicit**
`workstation_mise_uv_provision_enabled=true` permits a `mise install` in the
role checkout as the unprivileged user. It does not call `uv sync`; do that in
the developer checkout intentionally.

## VPN / Tunnel (non-destructive)

```yaml
tailscale_enabled: false
workstation_tailscale_disable_existing: true
workstation_tailscale_install_enabled: false
workstation_cloudflared_manage_existing: false
workstation_firewall_manage_enabled: false
```

On a full playbook application, an existing `tailscaled.service` is stopped
and disabled; the Tailscale package, keys, configuration and data are **not**
deleted. This may affect any outstanding VPN sessions; check local console
access before applying. `tailscale_enabled=true` prevents the disable operation.

Cloudflare Tunnel is the chosen access path. Existing `cloudflared.service`
is left untouched by default. To manage an **already installed and authorized**
service, set `workstation_cloudflared_manage_existing=true`. If no service is
installed, this mode fails without installing any tunnel or exposing a token.
Cloudflare ingress routes, service credentials and Access policies remain
separate administrative responsibilities.

UFW and Docker firewall changes are intentionally disabled by default:
`workstation_firewall_manage_enabled=false`. Validate SSH, Docker, local LAN
and Cloudflare access before turning it on.

## Offline verification

```bash
python3 -m unittest discover -s tests -p 'test_*contract.py' -v
python3 - <<'PY'
import tomllib
for file in ('mise.toml', 'pyproject.toml'):
    with open(file, 'rb') as f:
        tomllib.load(f)
print('PASS: TOML')
PY
bash -n .envrc
```

The tests above are static contracts, not a live workstation integration test.
No Ansible playbook is applied by this PR.
