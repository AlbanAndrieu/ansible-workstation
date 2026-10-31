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

## Plan retenu (31 octobre 2026)

L'opérateur a choisi le dépôt **`/media/backup/workstation`** (dataset `cpool/backup`, NFSv4.2,
2,2 To libres). Le partage applique `root_squash` : root ne peut pas y écrire, `albandrieu` si.

- **Exécution** : service systemd système `restic-backup.service` avec `User=albandrieu` et
  `AmbientCapabilities=CAP_DAC_READ_SEARCH` (méthode recommandée par Restic) : lecture de tout
  `/etc` sans être root, écriture sur NFS sous l'identité autorisée.
- **Planification** : `restic-backup.timer` avec `OnCalendar=daily`, `RandomizedDelaySec=1h`
  et `Persistent=true` (rattrape une exécution manquée si la machine était éteinte). Pas de cron :
  le timer donne journald, l'état d'échec et les dépendances (`RequiresMountsFor=/media/backup`).
  Après la sauvegarde : `forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune`.
  `restic-check.timer` hebdomadaire : `restic check --read-data-subset=5%`.
- **Alerte** :
  - en cas de succès, le service écrit l'horodatage dans `/var/lib/restic/last-success` ;
  - `zabbix-agent2` expose son âge (`UserParameter=restic.last_success_age`) ;
  - le Zabbix de TrueNAS déclenche une alerte au-delà de **26 h**, ce qui couvre un échec, un
    timer arrêté, un montage NFS absent ou une machine éteinte : c'est un *dead man's switch* ;
  - `OnFailure=` envoie en plus une notification de bureau immédiate.
- **Mot de passe** : `LoadCredentialEncrypted=` (`systemd-creds`, lié au TPM), copie hors machine.
- **Limite connue** : sur NFS, la workstation peut effacer ses propres snapshots (pas d'append-only).
  À compenser par des **snapshots ZFS** du dataset côté TrueNAS, que la workstation ne peut pas
  supprimer, en attendant `rest-server --append-only`.

## Implémentation

[`playbooks/restic-backup.yml`](../playbooks/restic-backup.yml) et [`files/restic/`](../files/restic/) :
plan seulement par défaut, écriture avec `restic_apply` **et** `restic_apply_approved`.

```bash
mise run restic-backup-check   # plan, sans sudo
.venv/bin/ansible-playbook -i localhost, -c local playbooks/restic-backup.yml \
  -e restic_apply=true -e restic_apply_approved=true -K
sudo systemd-creds decrypt /etc/credstore.encrypted/restic.password -   # à copier dans Bitwarden
sudo systemctl start restic-backup.service   # premier snapshot, puis :
journalctl -u restic-backup.service -n 30
```

Le mot de passe est chiffré par le TPM : **sans sa copie hors machine, une panne de carte mère
rend les snapshots illisibles**.

**Côté Zabbix (TrueNAS), une seule fois** : sur l'hôte `albandrieu`, item *Zabbix agent* de clé
`restic.last_success_age` (numérique, unité `s`, intervalle 10 min) et trigger
`last(/albandrieu/restic.last_success_age)>93600` (26 h), sévérité *High*. Ajouter aussi un
trigger `nodata(/albandrieu/restic.last_success_age,2h)=1` pour détecter l'agent muet.

### Mot de passe : où il est, copie Vaultwarden

Le mot de passe n'existe en clair nulle part sur disque : seulement dans
`/etc/credstore.encrypted/restic.password`, chiffré par le TPM. Copie dans Vaultwarden, sans
affichage (le coffre doit être déverrouillé par l'opérateur) :

```bash
export BW_SESSION="$(bw unlock --raw)"
sudo systemd-creds decrypt /etc/credstore.encrypted/restic.password - \
  | jq -Rn '{type:1, name:"restic workstation", notes:"Dépôt /media/backup/workstation (TrueNAS cpool/backup)", login:{username:"restic", password:input}}' \
  | bw encode | bw create item | jq -r .id
bw lock
```

**Pourquoi pas la YubiKey** pour ce mot de passe : la sauvegarde de nuit tourne sans personne
devant l'écran, donc sans contact sur la clé. Le TPM déverrouille sans intervention ; la YubiKey
protège la copie Vaultwarden (2FA).

### Rétention : Restic + snapshots ZFS

Restic garde 7 quotidiens, 4 hebdomadaires et 12 mensuels, mais la workstation peut effacer son
dépôt sur NFS. Une tâche de **snapshots ZFS** sur `cpool/backup`, côté TrueNAS, garde des copies
que la workstation ne peut pas supprimer. Proposition : chaque jour à 03:00 (après la sauvegarde),
conservés 14 jours. Sur TrueNAS, en root (géré par `nabla-compose`, pas par ce dépôt) :

```bash
midclt call pool.snapshottask.create '{"dataset":"cpool/backup","recursive":true,"lifetime_value":14,"lifetime_unit":"DAY","naming_schema":"auto-%Y-%m-%d_%H-%M","schedule":{"minute":"0","hour":"3","dom":"*","month":"*","dow":"*"}}'
```

Coût : les blocs supprimés par `restic prune` restent occupés 14 jours.

## Gate d'acceptation (roadmap P1)

`restic check --read-data-subset=5%` OK, **restauration de test** d'un échantillon dans un
dossier temporaire comparée à l'original, copie hors site présente. Tant que ces trois preuves
manquent, la sauvegarde n'est pas validée.

## Décisions à prendre par l'opérateur

- Fournisseur hors site (B2, S3, autre) et budget.
- Stockage du mot de passe : TPM (`systemd-creds`) ou 1Password ; le perdre rend les snapshots
  illisibles, le conserver aussi hors de la machine.
- Taille du premier snapshot à mesurer (`restic backup --dry-run`) avant d'activer le timer.
