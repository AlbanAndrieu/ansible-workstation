# Nettoyage de la workstation avec BleachBit

**Statut :** CODED, TESTED (13 contrats offline, shellcheck). `check` exécuté
le 22/11/2026 sur la workstation ; `apply` et le timer : NOT_RUN (à lancer
par l'opérateur).

Remplace les chaînes `rm -Rf` de `nabla/env/linux/cleanup-*.sh` par :

- les **nettoyeurs intégrés** de BleachBit (`vscode`, `google_chrome`,
  `firefox`, `thunderbird`, `thumbnails`, `claude`, `apt`, `snap`) ;
- un **nettoyeur personnalisé** [`files/bleachbit/workstation_dev.xml`](../files/bleachbit/workstation_dev.xml)
  (CleanerML), installé dans `~/.config/bleachbit/cleaners/` et visible aussi
  dans l'interface graphique de BleachBit ;
- [`scripts/workstation-cleanup.sh`](../scripts/workstation-cleanup.sh) pour orchestrer.

## Pourquoi

Le 30 octobre 2026, les lignes 59-66 de `cleanup-home.sh` ont été exécutées à
la main : `rm -Rf ~/.local/share/mise/*` a supprimé starship, direnv, uv, node
et le gateway OpenClaw (voir [réparation](user-toolchain-recovery.md)). Un
nettoyage ne doit supprimer que ce qui se **régénère seul**.

## Utilisation

```bash
cd /workspace/users/albandrieu30/ansible-workstation
mise run cleanup-check          # lecture seule : tailles + bleachbit --preview
mise run cleanup-apply          # caches utilisateur, sans sudo
mise run cleanup-apply-system   # apt, snaps désactivés, journald, flatpaks (sudo)

# Options explicites
EXTRA_CLEANERS="system.trash workstation_dev.maven_repository" mise run cleanup-apply
APT_AUTOREMOVE=1 MOTION_RETENTION_DAYS=30 mise run cleanup-apply-system
JOURNAL_MAX=300M mise run cleanup-apply-system
```

Les options absentes de la version installée de BleachBit sont ignorées et
signalées (`skipped`). Les options `process` (uv, pre-commit, docker) ne sont
sélectionnées que si l'outil est dans le `PATH`.

## Nettoyage périodique (timer utilisateur hebdomadaire)

```bash
mise run cleanup-timer-install   # ~/.config/systemd/user/workstation-cleanup.{service,timer}
systemctl --user list-timers workstation-cleanup.timer
mise run cleanup-timer-remove
```

Le timer (dimanche 12:30, `Persistent=true`, `Nice=19`, I/O `idle`) lance
`periodic` : caches de développement et purges natives des outils seulement
(`go clean -cache`, `uv cache prune`, `pre-commit gc`, images Docker orphelines
et cache de build, pip, npm, miniatures). Les caches des navigateurs, éditeurs
et de Claude restent dans `apply`, manuel, parce que ces applications peuvent
être ouvertes. Rien n'exige sudo ; `apply-system` reste manuel.

Images Docker inutilisées (re-téléchargeables ; une image construite
localement devra être reconstruite) : opt-in par âge,
`DOCKER_UNUSED_IMAGE_DAYS=30 mise run cleanup-apply`.

### Mesures du 22/11/2026 (`mise run cleanup-check`)

| Poste | Taille | Traitement |
|---|---|---|
| `~/.cache/pre-commit` | 16 Go | `pre-commit gc` (environnements non référencés) |
| `~/.cache/uv` | 11 Go | `uv cache prune` |
| `~/.local/share/mise/installs` | 12 Go | **jamais** (outils installés) ; `mise prune` à la main |
| `~/.gvm`, `~/.nvm` | 7,5 + 7,4 Go | anciens gestionnaires de versions, remplacés par mise : décision opérateur |
| `~/.config/google-chrome/OptGuideOnDeviceModel` | 4 Go | `google_chrome.ai` ; Chrome le re-télécharge |
| `~/.config/Claude/vm_bundles` | 18,6 Go | image de VM de Claude Desktop : ni nettoyée ni sauvegardée |
| Docker | 60 Go d'images inutilisées, 5 Go de cache de build | `periodic` + opt-in `DOCKER_UNUSED_IMAGE_DAYS` |
| BleachBit `apply` | 9,3 Go | aperçu `bleachbit --preview` |

`/home.sda-old` (159 Go) a été supprimé le 22/11 après comparaison avec le
nouveau home et un test de restauration Restic réussi ; la racine est passée
de 78 % à 41 %.

## Correspondance avec les scripts historiques

| Historique (`nabla/env/linux`) | Désormais |
|---|---|
| `~/.config/{Code,Cursor}/{Cache,CachedData,CachedExtensionVSIXs}` | `vscode.cache` (couvre Code, Cursor, VSCodium, Windsurf…) |
| Chrome `OptGuideOnDeviceModel` | `google_chrome.ai` |
| Chrome `component_crx_cache`, `extensions_crx_cache`, `optimization_guide_model_store` | `workstation_dev.chrome_component_caches` |
| `~/.cache/google-chrome`, `~/.mozilla/*`, `~/.thunderbird/*` | `google_chrome.cache`, `firefox.cache`, `thunderbird.cache` (cache seul, **profils conservés**) |
| `~/.cache/thumbnails`, `~/.thumbnails` | `thumbnails.cache` |
| `~/.cache/pip`, `pypoetry`, `pipenv` | `workstation_dev.python_caches` |
| `~/.cache/uv/*` | `workstation_dev.uv_cache` (`uv cache prune`) |
| `~/.npm`, `~/.cache/yarn`, `~/.node-gyp` | `workstation_dev.node_caches` (`~/.npm/_cacache` seulement) |
| `~/.cache/pre-commit/` | `workstation_dev.pre_commit_gc` (`pre-commit gc`) |
| `~/.cache/Cursor`, `schemas_cache`, `state.vscdb.backup` | `workstation_dev.editor_extras` |
| `~/.ansible/tmp/` | `workstation_dev.ansible_tmp` |
| `docker image prune`, `docker builder prune` | `workstation_dev.docker_build` |
| `~/.m2/repository/` | `workstation_dev.maven_repository` (opt-in, avertissement) |
| `~/.config/variety/Downloaded/*/` | `workstation_dev.variety_downloads` (opt-in) |
| `~/.local/share/Trash/*` | `system.trash` (opt-in : dernière chance de récupération) |
| `apt-get clean`, snaps désactivés, `refresh.retain=2` | `apply-system` : `apt.clean`, `apt.autoclean`, `snap.disabled` |
| `journalctl --vacuum-size=300M` | `apply-system` : `JOURNAL_MAX` (2G par défaut, comme `SystemMaxUse`) |
| `flatpak uninstall --unused` | `apply-system`, **sans** `--delete-data` |
| `rm /workspace/Dropbox/motion/*.{jpg,mkv}` | `apply-system` avec `MOTION_RETENTION_DAYS` (les captures récentes restent) |

## Jamais supprimé par ce dépôt

| Action historique | Raison |
|---|---|
| `~/.local/share/mise/*`, `~/.gem`, `~/.local/lib/python3.*` | Outils installés, pas des caches (cause de l'incident du 30/10) |
| `~/.mozilla/*`, `~/.thunderbird/*`, `~/.config/{Code,Cursor}` | Profils, courriels, réglages et extensions |
| `~/.config/Cursor/User/workspaceStorage/*`, `Code/User/History` | Historique local et conversations Cursor (`vscode.backup` reste en opt-in) |
| `~/.local/share/wineprefixes/*` | Applications Wine et leurs données |
| `docker rm -f $(docker ps -aq)`, `docker system prune`, volumes | Conteneurs et données (Postgres, Redis…) |
| `/var/lib/mongodb/*`, `/var/lib/redis/*.rdb` | Bases de données |
| `/var/log/syslog`, `/var/log/*.gz`, `audit.log` | Traces d'audit ; logrotate et auditd gèrent la rotation |
| `journald.clean` de BleachBit | Réduit le journal à presque rien (`--vacuum-size=1`) |
| `/usr/share/doc`, `/var/lib/apt/lists`, sources APT | Fichiers gérés par dpkg/apt |
| `find ~ -type d -empty -delete`, `find ~ -name '*~' -delete` | Casse des applications, supprime des sauvegardes |
| `*.passwords`, `system.free_disk_space`, `system.memory` | Refusés même en opt-in |

## Scripts historiques à isoler (dépôt `nabla`, non modifié ici)

Ces scripts ne sont **pas** du nettoyage et ne doivent jamais être enchaînés
avec les précédents :

- `cleanup-disk.sh` : efface `~/.ssh`, les dotfiles et des disques entiers
  (`wipe`, `scrub`) — script de **décommission**.
- `cleanup-security.sh` : efface les fichiers d'identifiants — réponse à
  incident. Il révèle aussi des secrets en clair dans `$HOME`
  (`.git-credentials`, `.vault-token`, `.pgpass`…) à migrer vers un
  gestionnaire (libsecret, pass).
- `run-git-clean.sh` : supprime tous les tags locaux et des branches **distantes**.
- `cleanup-docker.sh` : supprime tous les conteneurs et toutes les images.
- `run-audit-log-cleanup.sh` : supprime `audit.log` pendant que auditd écrit
  (perte d'événements) ; préférer `max_log_file_action = ROTATE`.
- `cleanup-jenkins.sh` : supprime `secret.key` (rend illisibles les
  identifiants Jenkins).

Recommandation : les renommer `decommission-*.sh` / `danger-*.sh` avec une
confirmation explicite, et retirer l'appel `DRY_RUN=0 ./cleanup-workstation.sh`
de `cleanup-home.sh`.
