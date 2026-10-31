# Restic : évaluation pour la workstation (31 octobre 2026)

[Restic](https://restic.net) sauvegarde des fichiers en **snapshots chiffrés** (AES-256, clé
dérivée d'un mot de passe), **dédupliqués** et incrémentaux. Le dépôt peut être un dossier
local, SFTP, un serveur REST, S3/B2 ou toute cible rclone. `restic check` vérifie l'intégrité,
`restic restore` restaure un snapshot, `restic forget --prune` applique la rétention.

## Constat

| Élément | État |
| --- | --- |
| `restic` 0.18.1, `rclone`, `timeshift`, `deja-dup` | installés |
| Config Restic, dépôt, timer de sauvegarde | **aucun** ; seul `dpkg-db-backup.timer` tourne |
| Cible disponible | dataset TrueNAS `cpool/backup`, monté en NFS sur `/media/backup` |
| Disque système | 456 Go, 86 % utilisés : prévoir le cache Restic (`~/.cache/restic`) |

Aujourd'hui, ce qui n'est pas dans Git n'a **aucune sauvegarde vérifiée** : secrets masqués
`@@SECRET@@` de `files/etc`, `~/.ssh`, `~/.gnupg`, `~/.ssh/config` privé, configs cloudflared,
credentials crowdsec, etc.

## Architecture proposée (3-2-1)

1. **Dépôt principal sur TrueNAS via `rest-server --append-only`**, pas via le montage NFS :
   avec NFS, un root compromis sur la workstation peut effacer les snapshots. En append-only,
   la workstation ajoute des snapshots mais ne peut ni les supprimer ni les réécrire ; la
   rétention (`forget --prune`) tourne côté TrueNAS. Le service rest-server relève de
   `nabla-compose`/TrueNAS, pas de ce dépôt.
2. **Copie indépendante hors site** : `restic copy` vers B2/S3 (ou rclone) depuis TrueNAS, avec
   un mot de passe de dépôt distinct. Couvre la perte de TrueNAS.
3. **Côté workstation (ce dépôt)** : unité et timer systemd quotidiens, listes d'inclusion et
   d'exclusion versionnées, mot de passe **hors Git** (`systemd-creds encrypt` lié au TPM, ou
   1Password).

| Inclure | Exclure |
| --- | --- |
| `/etc` complet, `~/.ssh`, `~/.gnupg`, `~/.config`, `~/.local/share/keyrings`, `/var/lib/` choisis | caches, `.venv`, `node_modules`, images Docker, modèles ollama (re-téléchargeables), `/media` (déjà sur TrueNAS) |

Rétention proposée : 7 quotidiens, 4 hebdomadaires, 12 mensuels.

## Gate d'acceptation (roadmap P1)

`restic check --read-data-subset=5%` OK, **restauration de test** d'un échantillon dans un
dossier temporaire comparée à l'original, copie hors site présente. Tant que ces trois preuves
manquent, la sauvegarde n'est pas validée.

## Décisions à prendre par l'opérateur

- Fournisseur hors site (B2, S3, autre) et budget.
- Stockage du mot de passe : TPM (`systemd-creds`) ou 1Password ; le perdre rend les snapshots
  illisibles, le conserver aussi hors de la machine.
- Taille du premier snapshot à mesurer (`restic backup --dry-run`) avant d'activer le timer.
