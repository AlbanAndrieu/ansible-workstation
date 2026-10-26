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

### direnv, mise and uv: first-time venv lifecycle

This repository has been compared with `fastapi-sample`. The other project's
`.envrc` explicitly creates and activates an environment, but also performs
various unrelated network/bootstrap tasks. Only the safe parts are reused.

In `ansible-workstation`, `direnv allow` now:
1. loads the **already installed** mise toolchain;
2. if `.venv` is absent, creates an **empty** local Python 3.12 venv using
   `uv venv --offline --no-python-downloads`;
3. activates a complete existing venv by setting `VIRTUAL_ENV` and prepending
   its `bin` directory;
4. never runs `uv sync`, downloads Python, installs packages, loads secrets
   or changes Git hooks.

If `mise`, uv or Python 3.12 are unavailable, first execute `mise install`
**explicitly**. After `.envrc` changes, run `direnv allow .` to authorize
the **new file contents**, then `direnv reload`. A reload alone does not
approve a changed `.envrc`. An existing incomplete venv is **not modified**;
its previous contents are preserved.

To recover the broken venv observed on the workstation
(`.venv/bin/python` missing in the project):

```bash
cd /workspace/users/albandrieu30/ansible-workstation

# Update the PR in the primary checkout, without discarding local edits.
git fetch origin fix/workstation-pfsense-split-dns-20261024
git merge --ff-only origin/fix/workstation-pfsense-split-dns-20261024

# Offline checks; safe before any runtime installation.
python3 -m unittest discover -s tests -p 'test_*contract.py' -v
bash -n .envrc
bash -n scripts/ensure-direnv-venv.sh
bash -n scripts/recover-workstation-venv.sh
bash -n scripts/bootstrap-workstation.sh

# Installs tools explicitly, not through direnv.
mise install

# Existing broken .venv? This archives it; NO deletion or sync.
mise run recover-venv

# Authorize the reviewed .envrc changed by Git before reloading it.
direnv status
direnv allow .
direnv reload
test -x .venv/bin/python && .venv/bin/python --version

# Explicitly sync locked project dependencies and repair primary Git hooks.
mise run init

# Verify that these commands do not fall back to the system Ansible.
.venv/bin/python -m pre_commit --version
.venv/bin/ansible --version
mise run check-venv
```

Do not run `mise run recover-venv` if an existing venv is healthy. It refuses
to archive a complete, executable environment. The command preserves an
incomplete venv as `.venv.incomplete-YYYYMMDD-HHMMSS-PID` (ignored by Git)
and never deletes any file. Review or retain that archive as needed.

A newly created empty `.venv` is deliberately **not commit-ready**:
`pre-commit` is installed later by `mise run init`. This separation keeps
`direnv allow` fast, offline, and free of hidden package mutations.

### Operator workflow (safe against empty uv.lock)

Previous workstation output (24 October): `uv lock` warned that the workspace
had no `requires-python`, produced a **three-line** `uv.lock`, and
`uv sync --locked` removed 71 existing packages. Subsequently `ansible`
resolved to `~/.local/bin/ansible` (system Python 3.14), **not the project's
toolchain**. The Ansible playbook syntax check was valid only for that system
Ansible. This was an accidental wrong-project resolution, not proof that
Ansible dependencies were successfully migrated.

Root cause of project-selection drift has **not yet been confirmed**.
The new wrapper explicitly selects the `pyproject.toml` in this checkout,
checks project metadata and the complete lock contents, and refuses external uv
environment overrides. Plain `mise exec -- uv sync` bypasses this protection:
**do not use it** for this project.

Review `mise.toml` in a trusted checkout before running mise tasks.

```bash
cd /workspace/users/albandrieu30/ansible-workstation

# Show your active branch and any local changes before fetching.
git status --short
git branch --show-current

# Update the tracked PR branch without rewriting local work:
git fetch origin fix/workstation-pfsense-split-dns-20261024
git merge --ff-only origin/fix/workstation-pfsense-split-dns-20261024

# No root privileges, network or package modification:
python3 -m unittest discover -s tests -p 'test_*contract.py' -v
bash -n scripts/uv-project.sh
bash -n .envrc

# Inspect possible external uv overrides (names only, never print tokens):
for key in UV_PROJECT UV_PROJECT_ENVIRONMENT UV_NO_PROJECT UV_NO_WORKSPACE; do
  if [ -n "${!key:-}" ]; then printf 'Review configured variable: %s\n' "$key"; fi
done

# Explicit toolchain setup; shared download cache, no global .venv:
mise install
mise run lock                  # explicit --project and verify dependencies
# Review uv.lock with git diff before staging or committing.
mise run sync                  # refuses existing unmanaged .venv
mise run check-venv            # must show .venv/bin/ansible, Python 3.12
mise run syntax                # only after project Ansible was verified
```

If the earlier `.venv` exists, **do not delete it**. Back it up manually
only after you have confirmed its path and any project-local dependencies:

```bash
# Example ONLY. Run once in the intended checkout after inspection:
mv .venv ".venv.before-uv-$(date +%Y%m%d-%H%M%S)"
mise run sync
```

The new `uv.lock` must contain resolved packages including `ansible-core`,
`pytest`, `ruff`, and their dependencies. It should never consist of only
`version`, `revision`, and `requires-python`. Once reviewed, commit the lock
in the same PR. The incomplete three-line lock was removed from GitHub.

Note that Ansible 2.21 supports controller Python 3.12–3.14, while the project
chooses Python 3.12 for consistent local development. The mere output of
`ansible --version` does not establish that it came from the local .venv.

### Tracked lockfiles and generated cache (25 October 2026)

The workstation's current staging status included:
`A mise.lock`, `M package-lock.json`, `M package.json`,
`M uv.lock`, `?? .config/`, `?? .node_cache/`.

**The three lockfiles are intentional and must be versioned.**
The latest PR branch now includes a resolved `uv.lock` with the Ansible
toolchain and a `mise.lock` matching Python 3.12, Node 24, uv 0.13.5.
`package.json` and `package-lock.json` are also committed together.
The offline `tests/test_lockfiles_contract.py` checks these invariants.

`.node_cache/` and the manually generated
`.config/requirements-lock.txt` are ignored. **Do not ignore the entire
`.config/` directory**: first inspect the exact untracked filenames.
Do not stage private credentials or accidentally commit a generated cache.
These ignores do not remove files already tracked by Git.

Before updating a workstation checkout with **staged local changes**, do
not run `git reset --hard` or a blind `git pull`:

```bash
git status --short --untracked-files=all
git diff --cached --stat
git diff --cached -- package.json package-lock.json uv.lock mise.lock
git fetch origin fix/workstation-pfsense-split-dns-20261024
git diff --stat HEAD..origin/fix/workstation-pfsense-split-dns-20261024
```

If the local index and the remote branch conflict, review them in an
isolated Git worktree before choosing which local changes to keep.

### Empty output and stale Git ignores (25 October)

The attempted manual pre-commit recovery printed **nothing**, followed by
`git status --short` showing only `?? .config/` and `?? .node_cache/`.

The old procedure included `test -x .venv/bin/python || exit 1` in
a subshell; a missing/non-executable interpreter causes an **entirely silent
exit**. Other possibilities remain (output not captured, shell flags, changed
current directory). Do not assume installation succeeded without checking
`python -m pre_commit --version`.

Run the read-only diagnostic **from any checkout**:

```bash
cd /workspace/users/albandrieu30/ansible-workstation
printf 'PWD: '; pwd -P
bash scripts/diagnose-pre-commit.sh
# After obtaining the updated version of the PR:
mise run hooks-diagnose
```

It displays the working directory, branch, primary-vs-linked worktree,
effective hook path, Python availability, installed pre-commit version and
the active Git ignore rules. It never downloads or installs anything.
`mise run hooks-repair` is only applicable to a primary checkout where the
project `.venv` exists.

The remote PR's `.gitignore` includes `.node_cache/` and
`.config/requirements-lock.txt`. These rules do **not** become effective
in the local checkout until the updated `.gitignore` is incorporated.
Do not add either directory to Git. Check with:

```bash
git status --short --untracked-files=normal
git check-ignore --no-index -v .node_cache/ .config/requirements-lock.txt
git fetch origin fix/workstation-pfsense-split-dns-20261024
git diff --name-status HEAD..origin/fix/workstation-pfsense-split-dns-20261024
```

Never run a destructive reset to clear generated cache. If there are no local
tracked modifications and the branch can fast-forward, then use
`git merge --ff-only origin/fix/workstation-pfsense-split-dns-20261024`.
The previous output contained no proof of a successful local Git commit.

### Git pre-commit repair on an existing workstation (25 October)

The 20 offline static tests passed in a detached worktree, but the regular
checkout's `git commit` failed before hook execution with:

```text
.venv/bin/python: No module named pre_commit
```

The previously executed exact uv sync removed packages from the existing
environment. The Git hook still points to that worktree-local Python.
This is an environment issue, **not a failing quality gate**.

Use a **trusted** working checkout that already contains its own `.venv`.
This must be the **primary checkout**, not a linked Git worktree:
the Git hook directory is shared in normal multi-worktree setups. Running
the repair from a secondary worktree fails closed instead of rewriting the
shared hook's Python interpreter. Worktree tests remain supported.

Run the repair explicitly, not from Bash startup or a Git hook:

```bash
cd /workspace/users/albandrieu30/ansible-workstation
mise run hooks-repair
.venv/bin/python -m pre_commit --version
python3 -m unittest discover -s tests -p 'test_*contract.py' -v
```

`hooks-repair` verifies the interpreter's `sys.prefix` is the current
worktree's `.venv`. It reads the `pre-commit` version from `uv.lock`,
installs **only that package and its requirements** with
`uv pip install --python .venv/bin/python` when missing or mismatched, and
installs the pre-commit / commit-msg Git hooks. It never performs an exact
`uv sync`, never installs into the system Python, and never runs implicitly
at `git commit` time. The first actual hook execution may fetch and build
the configured isolated hook environments; audit network access before
running it offline.

If the checkout has not yet received the new branch (staged changes prevent
a fast-forward), restore just the missing module by running:

```bash
uv pip install --python "$PWD/.venv/bin/python" "pre-commit==4.7.0"
"$PWD/.venv/bin/python" -m pre_commit install \
  --hook-type pre-commit --hook-type commit-msg
```

Then review the Git index with `git diff --cached --stat` before committing.
Never use `git reset --hard`, `git commit --no-verify`, or an exact
`uv sync` to work around this error. `git commit -am` does not include
untracked files, including new files from a local installation.

The old duplicate Ruff entry `ruff-check` (not a valid hook ID in
ruff-pre-commit) and unsafe automatic Ruff fixes were also removed. Ruff
lint remains enabled as a read-only check.

### Strict local shell acceptance (read-only)

After Direnv and the project `.venv` are set up, check the actual Bash
environment rather than assuming a successful installation implies activation.

```bash
cd /workspace/users/albandrieu30/ansible-workstation

# Run as a NEW command AFTER this directory's prompt has returned.
if source scripts/verify-direnv-shell.sh; then
  echo "PASS: shell has the reviewed Python/Ansible toolchain"
else
  echo "FAIL: run 'source scripts/diagnose-direnv-shell.sh' locally"
fi

python3 -m unittest discover -s tests \
  -p 'test_*contract.py' -v
```

`verify-direnv-shell.sh` must be **sourced**, not run under `bash` or
`mise run`, because a child cannot inspect its parent's Bash functions.
It returns nonzero when Direnv is missing from `PROMPT_COMMAND`, the known
invalid `_mise_hookhistory` token appears in `PS1` or
`PROMPT_COMMAND`, `VIRTUAL_ENV` does not match this project or
`python`/`ansible` resolve outside its local `.venv/bin`. It never
starts Ansible, downloads tools, installs dependencies or reads secrets.

No `uv sync` or venv rebuild is needed for shell-hook problems.

**Upstream compatibility debt:** mise explicitly treats simultaneous use of
its environment shell hooks and Direnv as unsupported. The workstation
configuration currently works, but a future standalone ADR should choose a
single environment owner. Do not remove either hook in this incident fix.

References:
- https://mise.jdx.dev/direnv.html
- https://direnv.net/docs/hook.html

### Mise prompt regression after Direnv activation (26 October 2026)

Latest workstation evidence after the prior Direnv hook fix:

- The interactive shell **has** `_direnv_hook` in `PROMPT_COMMAND`.
- Diagnostics printed `VIRTUAL_ENV` unset and system-global Ansible **before**
  Bash executed its next prompt.
- The following prompt printed `direnv: loading .../.envrc` and
  `direnv: export +VIRTUAL_ENV ... ~PATH`, then failed with
  `_mise_hookhistory: command not found`.
- The exact original `PROMPT_COMMAND` text is unknown. An invalid token is
  present; concatenation of a mise hook and Bash `history` is suspected but
  not conclusively proven from the logs.

Three coordinated fixes (no new PRs):

- `dotfiles` PR #1: restore only the known malformed token in Bash, and ask
  already-active mise to restore its **own** hook if needed; Direnv stays last.
  Preserve legitimate history, Starship and arrays. Do not modify quoted
  prompt text or reset the user's custom `.bashrc`.
- `nabla` PR #68: remove only whole obsolete prompt commands, never substrings
  inside names or quoted commands.
- `ansible-workstation` PR #13: display a privacy-preserving diagnostic of
  the known invalid token, without dumping arbitrary prompt contents.

After fast-forwarding all applicable branches, open a **new Bash terminal**.
Run the read-only diagnostic; then, after the prompt has returned, check
`VIRTUAL_ENV` and `type -P python` / `type -P ansible` on **a new command**.
This timing matters because Direnv performs its export at the prompt boundary.

No `uv sync`, Ansible apply or service restarts are needed for this issue.

### Interactive Bash: Direnv hook lost after prompt initialization

Later workstation validation established that `mise run syntax` passes with
the **project-local** Ansible, while `direnv status` still shows
`No .envrc or .env loaded`, `VIRTUAL_ENV` is unset and ordinary
`command -v ansible` resolves to the global binary in
`~/.local/bin/ansible`. Approving/reloading `.envrc` did not fix the
**interactive shell's** environment.

The Bash config is owned by the `dotfiles` repository. Inspection found
that Direnv was hooked **before** Nabla/mise/Starship prompt setup. The
`dotfiles` PR #1 now checks `PROMPT_COMMAND` and reinstalls the Direnv Bash
hook **at the end of `.bashrc`** if prompt initialization dropped it.
This is a likely cause, not yet confirmed by an in-shell PROMPT_COMMAND dump.
According to Direnv's upstream hook documentation, the Bash hook must appear
after other prompt extensions.

To inspect the **current interactive Bash**, run `source`, **not**
`bash scripts/diagnose-direnv-shell.sh` or `mise run`: a subprocess
cannot read the parent shell's `PROMPT_COMMAND`.

```bash
cd /workspace/users/albandrieu30/ansible-workstation
source scripts/diagnose-direnv-shell.sh

# Temporary one-shell recovery, only after reviewing/allowing trusted .envrc:
eval "$(direnv hook bash)"
_direnv_hook

printf 'VIRTUAL_ENV=%s\n' "${VIRTUAL_ENV:-unset}"
type -P python
type -P ansible
```

Expected paths in this directory:
`/workspace/users/albandrieu30/ansible-workstation/.venv/bin/python`
and `.../.venv/bin/ansible`. This does not require rebuilding `.venv`
and does not change global Python or Git configuration.

After the `dotfiles` PR #1 is incorporated into the actual home checkout,
open a new terminal to confirm that the Bash prompt hook persists, then run
the diagnostic again. Do not replace `PROMPT_COMMAND` manually or install
a second Direnv hook on every prompt.

### Verified workstation bootstrap (25 October 2026)

Operator executed the PR branch with these results:

- **30/30 offline contract tests passed** before this documentation update.
- `mise install` reported all declared tools installed.
- `mise run recover-venv` correctly reported no `.venv` existed.
- `direnv reload` left `.venv` missing. A possible explanation is that
  Git had changed `.envrc` and the new content had not been authorized with
  `direnv allow .`. **This was not confirmed by `direnv status`.**
- `mise run init` succeeded: uv resolved **166** lockfile packages and
  installed **48** packages into `.venv`.
- The verified project binary is `.venv/bin/ansible` (**Ansible 2.21.5**
  and **Python 3.12.10**), not system Ansible.
- `pre-commit 4.7.0` was installed and both `pre-commit` and `commit-msg`
  hooks were installed successfully.
- `mise run check-venv` succeeded after initialization.

A uv warning about **hardlink fallback to copy** is nonfatal and can arise
when the uv cache and checkout are on different filesystems. uv can be
explicitly told to use `UV_LINK_MODE=copy` if this remains the desired
installation strategy; do not set it globally without evaluating other
projects.

Do **not** delete or recreate the now-healthy `.venv` just to reproduce
the direnv authorization issue. Instead, run `direnv status`, review and
authorize `.envrc` with `direnv allow .`, then inspect `VIRTUAL_ENV`
and `command -v python` / `command -v ansible`.

Remaining integration evidence: `mise run syntax`, `pre-commit validate-config`,
and a normal commit to verify the installed hooks. Applying the full
workstation playbook and changing DNS, Tailscale or firewall remain out of
scope of this local runtime validation.

### Pre-commit, Ansible config and CI safety

- `uv-sync` is removed from automatic pre-commit execution: it may uninstall
  dependencies on each commit. `uv-lock`, `uv-export` and
  `pre-commit-update` are manual-only, to avoid unrelated Git mutations.
- The Ansible and Python CI jobs use `.venv/bin/` directly and require an
  existing, valid lock. CI will not be release-ready until a reviewed lock is
  committed; the PR stays Draft.
- `ansible.cfg` now enables SSH host key verification, stops ignoring TLS
  certificates, removes automatic root login, plaintext repository logging,
  automatic Vault password lookup, invalid jsonfile caching and unsafe SSH
  known_hosts overrides. A new host must first be enrolled with a **verified**
  SSH host key.
- `--syntax-check` never applies system configuration; avoid running the
  entire playbook until UFW, DNS, Tailscale and existing services have been
  separately approved.

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
