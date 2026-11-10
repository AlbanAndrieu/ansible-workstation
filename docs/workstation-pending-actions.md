# Actions en attente de l'opérateur

**11 novembre 2026.** Points de la [roadmap](roadmap-workstation.md) que l'agent ne peut pas
finir seul : une commande sudo (refusée à l'agent), ou une décision. Le code est commité ; chaque
section donne le contrôle, la commande et la vérification. Rayer une section une fois faite.

## 1. Commandes sudo prêtes

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

### Crontab root : scan ClamTk au repos, doublons retirés

Le `--check` ne change que ces deux tâches : `nice -n 19 ionice -c3` devant `clamscan`, et les
lignes maldet (cassée) et chkrootkit (en double) retirées.

```bash
mise run stabilize-check
.venv/bin/ansible-playbook -i localhost, -c local playbooks/stabilize-workstation.yml -e stabilize_apply=true -e stabilize_apply_approved=true -K
sudo crontab -l | grep -cE 'maldet|nice -n 19 ionice -c3 /usr/bin/clamscan'
```

Attendu : `1` (seule la ligne ClamTk, réécrite).

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

### Hôte Zabbix de la workstation

`ZABBIX_API_TOKEN` n'est pas exporté dans le shell : `zabbix-host-check` ne peut pas lire l'API.

```bash
export ZABBIX_API_TOKEN="$(…)"   # depuis Vaultwarden, sans l'afficher
mise run zabbix-host-check
```

## 2. Décisions

1. **Copie Restic hors site** : quel fournisseur et quel budget ? La règle « garder une copie
   indépendante de TrueNAS » n'est pas tenue ; un dépôt Restic chiffré chez un stockage objet
   (B2, Wasabi, OVH Object Storage…) suffit pour quelques Go.
2. **Racine Apache et `UMASK 027`** : les nouveaux fichiers créés sous `/var/www` ne seront plus
   lisibles par `www-data`. Options : setgid + groupe `www-data` sur la racine, ou `umask 022`
   pour le seul déploiement du site.
3. **DNS du démon Docker** : les conteneurs résolvent par `9.9.9.9` puis Pi-hole
   (`/etc/docker/daemon.json`), avec 27 échecs vers `9.9.9.9` en 24 h. Passer à `172.17.0.1`,
   comme l'hôte, impose un redémarrage de Docker et la recréation des conteneurs : quand ?
4. **Cadence apt** : garder la cadence hebdomadaire réglée sur la station
   (`Update-Package-Lists "7"`) ou passer au quotidien du tag `apt-periodic` ?
5. **Images et cache Docker** : 47,6 Go d'images et 25,4 Go de cache de build récupérables
   (`docker system df`, 11/11). `docker image prune -a` et `docker builder prune` retirent tout ce
   qu'aucun conteneur n'utilise : une image à reconstruire ou retélécharger au prochain usage. Les
   5,8 Go de volumes orphelins sont des données : à trier à la main, jamais en `prune`.
6. **`cleanup-apply-system`** (sudo) : caches apt, snaps désactivés, flatpaks inutilisés. À lancer ?
7. **Cron root `rm -f /var/log/audit/audit.log.*`** : il efface les rotations d'auditd. Le retirer
   et laisser `max_log_file_action = ROTATE` / `num_logs` d'auditd gérer la taille ?
8. **msmtp** : sans configuration, chaque sortie de cron finit en `status 0x004e from MTA` et
   se perd (`wacli` et `vdirsyncer` chaque heure). Configurer `/etc/msmtprc` (relais et compte à
   choisir), ou `MAILTO=""` et rediriger vers `logger` ?
9. **Howdy** : l'apply écrit `disabled = true` dans sa configuration ; l'activation PAM reste à
   nabla-yubikey. Appliquer ?
10. **Lot « vieilles distributions »** : 49 fichiers indexés dans ce checkout, à relire puis
    commiter (le commit n'est pas le mien).

## 3. Hors de ce dépôt

- **dotfiles** : remplacer `bin/inspect-workstation-system.py` par un wrapper vers
  `scripts/audit-workstation-inventory.py`, pour qu'il ne reste qu'un collecteur. Le checkout
  `~` est sur `chore/workstation-agents-20261031`, avec des changements non commités de
  l'opérateur : à faire sur une branche propre.
- **nabla-compose PR #346** : rebasée le 11/11. Elle retire les six diagnostics du lot 1, qui ne
  vivront plus qu'ici. À relire puis fusionner.
- **P2, scripts OpenClaw/TrueNAS** : l'API de sonde entre `nabla-openclaw` et `nabla-compose` se
  décide dans ces deux dépôts.
- **P2, pipeline audit → plan → apply** : chaque playbook a déjà son plan par défaut et sa double
  approbation. Il manque un retour arrière éprouvé, ce qui demande un apply réel puis un
  `git revert` réappliqué : à planifier avec l'opérateur.
