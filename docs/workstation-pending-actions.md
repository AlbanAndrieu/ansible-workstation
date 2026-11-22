# Actions en attente de l'opérateur

**Révision documentaire du 21 novembre 2026** (observations de poste : 16–18/11 ; CI GitHub : 21/11). Décisions et actions qui exigent un sudo local, un contrôle physique ou une autorisation. Avant de reprendre une ancienne commande, **revalider son préflight** : aucun test live n'a été réalisé pendant cette révision.


## Synthèse des décisions ouvertes

| Rang | Décision / risque | Gate avant intervention |
| --- | --- | --- |
| **P0 — W01/W03** | Fenêtre GNOME InputCapture ; rétention auditd ; autologin/session | Identifier le processus D-Bus demandeur et les consentements ; ne pas collecter d'événements clavier ni accorder de permission inconnue. Contrôler le cron destructeur avant de le supprimer |
| **P0 — W02** | Restauration Restic et copie hors NAS | Service de test de restauration installé et succès observable ; confirmer une sauvegarde **postérieure au 13/11**, sa couverture et la possession indépendante de la clé |
| **P0 — W04** | Surface Docker/UFW/IPv6 | Test de refus depuis un **autre** hôte LAN et un observateur WAN autorisé ; aucune conclusion WAN sur la seule mesure TrueNAS |
| **P1 — W06** | Suppression de l'ancien home | **Pas avant le 20/11** et seulement après restauration vérifiée ; vérifier montage/LUKS/backup |
| **P1 — W05/W07/W08** | MOK, DNS Docker, APT, Apache, cron | Fenêtres d'apply séparées et approbations explicites ; rollback documenté |

La [roadmap consolidée](roadmap-workstation.md#portefeuille-priorisé--21-novembre-2026) est la vue d'arbitrage. Les chiffres ci-dessous reflètent leurs **dates d'observation**, pas une nouvelle mesure.

### Réception des rapports de sécurité (21/11)

Le code de synthèse HTML/JSON est préparé mais non installé sur la machine.
Prévoir un contrôle local des quatre timers, du résultat des scans et de la
publication LAN après un `--check` Ansible puis un apply explicitement approuvé.
L'accès par un en-tête Cloudflare non authentifié a été supprimé du modèle Apache ;
vérifier que l'instance active a bien été alignée avant de conclure à une
protection effective. Les données complètes restent privées ; aucun import
DefectDojo ni export vers le site public n'est activé.
## 1. Commandes sudo prêtes

### Après la bascule de `/home` sur le NVMe (faite le 13/11)

Unité de bascule retirée du système le 13/11. Reste à supprimer `/home.sda-old` le 20/11 :
commande dans le
[runbook stockage](runbook-storage-nvme.md#1-bascule-de-home-sur-le-nvme--faite-le-1311). Pour
enrôler la clé DKMS (section Secure Boot plus bas), lancer `mokutil --import` avant un reboot :
MokManager s'affiche au redémarrage suivant.

### Restauration Restic isolée

Installe `restic-restore-test.service`, puis restaure `/etc/restic` dans un `/tmp` privé et le
compare à l'original (`diff -r`).

```bash
mise run restic-backup-check
.venv/bin/ansible-playbook -i localhost, -c local playbooks/restic-backup.yml -e restic_apply=true -e restic_apply_approved=true -K
sudo systemctl start restic-restore-test.service
systemctl show restic-restore-test.service -p Result
```

Attendu : `Result=success`.

### Crontab root : scans de sécurité en timers systemd, doublons retirés

Les lignes ClamTk (`clamscan -r /home/albandrieu` chaque nuit, tuée à 08:08 le 16/11 sans résumé), maldet,
chkrootkit, lynis, oscap, webmin, pgbadger et les scripts de `~/w/nabla` (modifiables par l'utilisateur,
donc élévation vers root) sont retirées. `playbooks/security-scans.yml` les remplace par des timers
`security-scan@<outil>` ; ClamAV passe par `clamdscan --multiscan` le samedi à 01:00, sur les systèmes de
fichiers locaux seulement (les partages TrueNAS sont scannés sur TrueNAS).

```bash
.venv/bin/ansible-playbook -i localhost, -c local playbooks/security-scans.yml -e security_scans_apply=true -e security_scans_apply_approved=true -K
sudo crontab -l | grep -vE '^(#|$)'
systemctl list-timers 'security-scan@*'
```

Attendu : `MAILTO=""` et speedtest seuls, puis quatre timers. Détail : `docs/security-workstation.md`.

**Appliqué le 16/11** : crontab réduite à `MAILTO=""` et speedtest, 4 timers actifs, Lynis publié
(indice 73). Les tâches orphelines de maldet sont supprimées et anacron écrit dans le journal
(`systemd-cat`). Apache écoute `127.0.0.1:8082` (tunnel) ; les rapports sont servis en local sur 8087 (LAN)
et par le tunnel derrière Cloudflare Access, application encore à créer (« Accès aux rapports » dans
`security-workstation.md`).

### Secure Boot : enrôler la clé DKMS avant de l'activer

`mise run audit-boot` rend `secure_boot_off_enroll_dkms_key_first` :
- Secure Boot est coupé ;
- le TPM 2.0 est présent ;
- le module NVIDIA 595.71.05 est signé par la clé DKMS `/var/lib/shim-signed/mok/MOK.der`, que le
  shim ne connaît pas (noyau marqué `E`).

Activer Secure Boot maintenant empêcherait le chargement du module : plus de GPU, ni pour la
session graphique ni pour ollama.

```bash
sudo mokutil --import /var/lib/shim-signed/mok/MOK.der
```

`mokutil` demande un mot de passe à usage unique. Au redémarrage, MokManager (écran bleu) propose
« Enroll MOK » : saisir ce mot de passe. Ensuite :

```bash
mise run audit-boot
```

Attendu : `dkms_mok: enrolled`, verdict `secure_boot_off_ready_to_enable`. Activer Secure Boot
dans le firmware reste un choix distinct : après l'activation, `audit-boot` doit rendre
`secure_boot_on` et `nvidia-smi` répondre. Retour arrière : couper Secure Boot dans le firmware.

### unattended-upgrades

Dépend du lot « vieilles distributions » (49 fichiers indexés, non commités) et de la cadence
choisie (question 4).

```bash
.venv/bin/ansible-playbook -i localhost, -c local playbooks/workstation.yml --tags unattended-upgrades --check --diff -K
.venv/bin/ansible-playbook -i localhost, -c local playbooks/workstation.yml --tags unattended-upgrades -K
```

Attendu au `--check` : `changed=1`, seul `52unattended-upgrades-workstation` est créé.

### Retour arrière ciblé (P2, pipeline audit → plan → apply)

`restore-etc.yml` prend `etc_restore_only` : il restaure ces seuls fichiers depuis la capture,
garde une copie datée de ce qu'il remplace, et ne touche ni aux unités ni à motion. Test sur un
fichier sans risque : on dérègle la taille de journald, puis on la rétablit.

```bash
sudo sed -i 's/^SystemMaxUse=2G$/SystemMaxUse=1G/' /etc/systemd/journald.conf.d/size.conf
.venv/bin/ansible-playbook -i localhost, -c local playbooks/restore-etc.yml -e '{"etc_restore_only": ["systemd/journald.conf.d/size.conf"]}'
.venv/bin/ansible-playbook -i localhost, -c local playbooks/restore-etc.yml -e '{"etc_restore_only": ["systemd/journald.conf.d/size.conf"]}' -e etc_restore_apply=true -e etc_restore_apply_approved=true -K
grep SystemMaxUse /etc/systemd/journald.conf.d/size.conf
```

Attendu :
- la première passe liste le fichier dans `would_change_or_changed` ;
- après l'apply, `SystemMaxUse=2G` est revenu, et une seconde passe rend une liste vide ;
- la copie datée (`size.conf.<horodatage>~`) reste à côté : journald ne lit que les `*.conf`.

### Hôte Zabbix de la workstation

`ZABBIX_API_TOKEN` n'est pas exporté dans le shell : `zabbix-host-check` ne peut pas lire l'API.

```bash
export ZABBIX_API_TOKEN="$(…)"   # depuis Vaultwarden, sans l'afficher
mise run zabbix-host-check
```

### Nouveau lot — accès Nexus et sécurité (21/11)

- **Nexus package cache** : [plan et critères de réception](workstation-nexus-package-cache.md). Vérifier le TLS privé `nexus.int.albandrieu.com`, les dépôts réellement créés, l'absence de proxy de sécurité Ubuntu et les limites Community avant tout changement APT/npm/uv/Docker. Pas d'URL publique Cloudflare Access dans les fichiers de configuration CLI.
- **Privilèges P0** : relever `sudo -l` sans jeton dans les logs, inspecter `security_sudoers_passwordless` et les groupes `docker`/`lxd`/`libvirt`/`microk8s`. Préparer un accès de secours et un plan de retrait ; aucun changement PAM ou YubiKey automatique.
- **Scans P1** : obtenir la sortie du premier `security-scan@clamav` de samedi 21/11 et les erreurs `grpck` ; vérifier Lynis, OpenSCAP et rkhunter sur les scans achevés. Les résultats du 16/11 ne prouvent pas un scan complet le 21/11.

## 2. Décisions

1. **Copie Restic hors site** : quel fournisseur et quel budget ? La règle « garder une copie
   indépendante de TrueNAS » n'est pas tenue ; un dépôt Restic chiffré chez un stockage objet
   (B2, Wasabi, OVH Object Storage…) suffit pour quelques Go.
2. **Racine Apache et `UMASK 027`** : les nouveaux fichiers créés sous `/var/www` ne seront plus
   lisibles par `www-data`. Options : setgid + groupe `www-data` sur la racine, ou `umask 022`
   pour le seul déploiement du site.
3. **DNS du démon Docker après le retrait de pfSense** : l'ancien couple `9.9.9.9`/Pi-hole et ses 27 échecs sont des mesures antérieures. La station utilise Pi-hole `172.17.0.24` pour `~int.albandrieu.com`, Quad9 pour le public et le R7000 `172.17.0.1` comme routeur. **Ne pas traiter `172.17.0.1` comme DNS pfSense.** Auditer les résolutions dans les conteneurs et valider un plan de redémarrage avant toute modification de `daemon.json`.
4. **Cadence apt** : garder la cadence hebdomadaire réglée sur la station
   (`Update-Package-Lists "7"`) ou passer au quotidien du tag `apt-periodic` ?
5. **Images et cache Docker** : le nettoyage **D6 a été effectué le 13/11** (environ 31 Go libérés). L'ancienne estimation du 11/11 n'est plus un quota récupérable. Relancer `docker system df` avant une nouvelle proposition, conserver les images locales non re-téléchargeables et **ne jamais pruner les volumes par défaut**.
6. **`cleanup-apply-system`** (sudo) : caches apt, snaps désactivés, flatpaks inutilisés. À lancer ?
7. **Auditd** : la suppression du cron destructeur et la rotation `max_log_file_action=ROTATE` sont documentées **APPLIQUÉES le 16/11** dans `security-workstation.md`. La prochaine action est une vérification `auditctl -l`/rétention et un test de production de traces, pas la répétition de l'ancien nettoyage.
8. **msmtp** : sans configuration, chaque sortie de cron finit en `status 0x004e from MTA` et
   se perd (`wacli` et `vdirsyncer` chaque heure). Configurer `/etc/msmtprc` (relais et compte à
   choisir), ou `MAILTO=""` et rediriger vers `logger` ? **16/11** : anacron passe par `systemd-cat`
   (journal et code de retour conservés) ; restent les sorties de `debsecan` et d'`apticron`.
9. **Howdy** : l'apply écrit `disabled = true` dans sa configuration ; l'activation PAM reste à
   nabla-yubikey. Appliquer ?
10. **Lot « vieilles distributions »** : livré d'après la roadmap du 10/11. Ne pas reproduire l'ancienne instruction de committer « 51 fichiers indexés » : inspecter les changements locaux et respecter les propriétaires des autres sessions.
11. **Profil minimal opt-in** : `tasks/workstation.yml` importe sans condition ses 50 fichiers de
    tâches, et chacun dépend de ses propres `*_enabled` (68 dans `defaults/main.yml`). Proposition :
    une variable `workstation_profile: minimal` qui n'importe que sécurité, réseau, git, éditeur,
    Python, conteneurs, sauvegarde et réglages système, tout le reste restant opt-in. Quel
    périmètre ? Ces fichiers sont dans le lot de la question 10 : il faut le commiter d'abord.
12. **Scripts OpenClaw de nabla-compose** : 59 scripts restent dans `scripts/workstation/` (et 3
    dans `scripts/truenas/`). Ils servent la gateway du poste, arrêtée depuis la bascule du 3/11 et
    gardée seulement pour le retour arrière. Les retirer de nabla-compose une fois ce retour arrière
    abandonné, ou porter ceux qui servent encore vers `nabla-openclaw` ?

## 3. Hors de ce dépôt

- **dotfiles** : `bin/inspect-workstation-system.py` est devenu un wrapper vers
  `scripts/audit-workstation-inventory.py` (même JSON, `provenance` en plus, et même résumé), avec
  ses tests et ses docs. Commité (`5f5d47d`) sur `refactor/inventory-wrapper-20261111` :
  [dotfiles#5](https://github.com/AlbanAndrieu/dotfiles/pull/5), **fusionnée le 11/11**.
- ~~**nabla-compose PR #346**~~ : fusionnée le 11/11 (`30d1958b`) ; les six diagnostics du lot 1
  ne vivent plus qu'ici.
- **P2, scripts OpenClaw/TrueNAS** : voir la question 12. L'API de sonde entre `nabla-openclaw`
  et `nabla-compose` se décide dans ces deux dépôts.
