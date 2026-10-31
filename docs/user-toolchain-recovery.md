# Réparation de la toolchain utilisateur (mise, starship, direnv, OpenClaw)

**Statut :** CODE ADDED / RUNTIME NOT VERIFIED — 6 contrats offline PASS
(`tests/test_user_toolchain_repair_contract.py`), shellcheck PASS.

Outil **opérateur**, hors rôle Ansible. Il répare l'environnement de
l'utilisateur après la perte de `~/.local/share/mise` (incident du
30 octobre 2026 : nettoyage disque avec `rm -Rf ~/.local/share/mise/*`).
Selon [Option A](workstation-ownership-option-a.md), la configuration
utilisateur relève de `dotfiles` et le gateway OpenClaw cible de
`nabla-openclaw` ; ce script ne fait que **restaurer l'existant**.

## Symptômes

- `bash: ~/.local/share/mise/installs/starship/.../starship: No such file or directory`
- `bash: ~/.local/share/mise/installs/direnv/.../direnv: No such file or directory`
- `mise run …` échoue (plus de `uv`), `openclaw-gateway.service` en échec.

Le `.venv` du dépôt n'est **pas** concerné : il utilise le Python géré par uv
(`~/.local/share/uv/python`).

## Utilisation

```bash
# 0. Dans le terminal cassé, couper les hooks devenus invalides
unset PROMPT_COMMAND; PS1='\u@\h:\w\$ '

cd /workspace/users/albandrieu30/ansible-workstation
bash scripts/repair-user-toolchain.sh check   # lecture seule (défaut)
bash scripts/repair-user-toolchain.sh apply   # réparation explicite
exec bash -l
```

Alias : `mise run toolchain-check` et `mise run toolchain-repair` (si mise
fonctionne encore).

| Étape `apply` | Action |
|---|---|
| Espace disque | Refus si moins de `MIN_FREE_GB` (10 Gio par défaut) libres dans `$HOME` |
| mise global | `mise install` depuis `$HOME` (config `~/.config/mise/config.toml`) puis `mise reshim` |
| Projet | `mise install` (versions de `mise.lock`), puis `uv-project.sh check` |
| OpenClaw | Lit l'`ExecStart` **effectif** (dernier drop-in), installe la version de node attendue, puis `npm install -g openclaw@2026.10.7` avec liste blanche de scripts, `daemon-reload` et `restart` |
| Contrôle final | Rejoue `check` ; code retour 0 seulement sans problème |

## Garde-fous

- Refus en root ; jamais `sudo`, `curl | sh`, PAM ni socket Docker.
- `OPENCLAW_VERSION` doit être une version exacte `X.Y.Z` (pas `latest`).
- `NPM_ALLOW_SCRIPTS` : liste explicite, jamais `*`. Par défaut
  `openclaw,koffi,esbuild` (plugins intégrés, binaire natif FFI, binaire
  esbuild). Restent bloqués : `protobufjs` (simple avertissement de version)
  et `@google/genai` (no-op).
- Les arguments d'`ExecStart` et l'`EnvironmentFile` (jetons) ne sont jamais
  affichés : seuls la présence du binaire node, de l'entrée OpenClaw et
  l'état du service le sont.
- Si mise lui-même manque : réinstallation depuis le dépôt APT signé
  documenté sur <https://mise.jdx.dev>, pas de script distant.

## Unités `systemd --user` en échec

Le script les liste sans les modifier. Cas connu :

- **`bitcoin-qt.service`** (unité historique de `tasks/services.yml`) :
  `ExecStart` vers `/usr/local/bin/bitcoin-qt`, rattachée à `xsession.target`.
  Diagnostic : `journalctl --user -u bitcoin-qt -n 50`. Si inutilisée :
  `systemctl --user disable --now bitcoin-qt.service && systemctl --user reset-failed bitcoin-qt.service`.
  Un nœud complet avec `-prune=0` occupe plusieurs centaines de Go : vérifier
  `du -sh ~/.bitcoin` lors d'un manque d'espace.

## Limites et suite

- Le drop-in OpenClaw pointe vers un chemin **versionné** de mise
  (`installs/node/24.22.1`) : toute mise à jour ou purge de mise le casse.
  Correctif durable à porter dans `nabla-openclaw`/`dotfiles`.
- Déclarer les outils globaux, dont `npm:openclaw`, avec versions figées dans
  `~/.config/mise/config.toml` pour qu'un `mise install` suffise.
- Howdy : traité séparément (PAM), voir la roadmap.
