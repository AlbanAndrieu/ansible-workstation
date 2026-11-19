# Sécurité de la workstation : audit du 16/11/2026 et plan de durcissement

**Statut :** audit fait, corrections urgentes et lots 1 et 2 appliqués le 16/11 ; lots 3 à 5 proposés.

Rapports : `/var/www/reports/security/` sur le disque local, servis par Apache en
`/reports` : `http://172.17.0.57:8087/reports/security/` depuis le LAN, et par le
tunnel Cloudflare derrière Cloudflare Access (voir « Accès aux rapports »).

## Ce qui a été corrigé tout de suite

| Changement | Pourquoi | Retour arrière |
| --- | --- | --- |
| `/etc/apache2/conf-available/nabla-lan-only.conf` (activé) : `mod_remoteip` fait confiance à `CF-Connecting-IP` venant de `127.0.0.1` ; `/reports` et `/public/reports` limités à `172.17.0.0/24` ; `/server-status` à la station et au LAN | cloudflared arrive en `127.0.0.1` : `Require local` et l'absence de règle laissaient `/reports` (Lynis, rkhunter, ClamAV) et `/server-status` lisibles par tout client du tunnel. Vérifié : 403 avec un en-tête `CF-Connecting-IP` public, 200 depuis le LAN | `sudo a2disconf nabla-lan-only && sudo systemctl reload apache2` |
| `/etc/lynis/custom.prf` : `skip-test=CRYP-7902` | Ce test parcourt les certificats jusque dans les montages NFS : bloqué 35 min, Lynis jamais terminé | Supprimer le fichier |
| `openscap-scanner` et `ssg-debderived` installés (paquets Ubuntu) | Le `oscap` de `/usr/local/bin` (compilé à la main) est cassé (`librpm.so.8` absente) ; aucun contenu SCAP n'était installé | `sudo apt remove openscap-scanner ssg-debderived` |

### Accès aux rapports (16/11, soir)

Apache n'écoute plus que `127.0.0.1:8082` (tunnel) : la sonde HAProxy de pfSense
gardait le partage NFS `/media/www` monté. Les rapports quittent donc ce partage
pour `/var/www/reports` (local, `albandrieu:www-data` 2750), servi par
`Alias /reports` sur les deux ports :

| Accès | Règle | Vérifié |
| --- | --- | --- |
| LAN, `http://172.17.0.57:8087/reports/security/` | `Require ip 172.17.0.0/24` (ufw n'ouvre 8087 qu'au LAN) | 200 |
| Tunnel sans Access | — | 403 |
| Tunnel avec Access | connexion venant de `127.0.0.1` **et** en-tête `Cf-Access-Jwt-Assertion` | 200 (en-tête simulé) |

Seul Cloudflare Access ajoute cet en-tête, et seul cloudflared atteint 8082 :
un processus local pourrait le forger, pas un client du tunnel. Apache ne vérifie
pas la signature du jeton ; il faudrait `mod_auth_openidc` pour cela.

**Reste à faire dans Cloudflare (non fait)** : le jeton API de l'environnement
ne voit ni le tunnel `ab5097ef-…` ni la zone DNS, et la création de
l'application Access est refusée (`1010 auth.forbidden`).
`albandrieu.albandrieu.com` (nom de la workstation) n'a pas d'enregistrement DNS
public : le tunnel ne publie pas encore Apache. Dans le tableau de bord :

1. Zero Trust → Networks → Tunnels → tunnel `ab5097ef-…` → *Public Hostname* :
   `albandrieu.albandrieu.com` → `http://localhost:8082`.
2. Zero Trust → Access → Applications → *Self-hosted* : domaine
   `albandrieu.albandrieu.com`, chemin `reports`, politique *Allow* sur
   l'adresse e-mail du propriétaire, session 24 h. Créer l'application
   **avant** le nom d'hôte public.

Tant qu'elle n'existe pas, le tunnel répond 403 sur `/reports`. Les anciennes copies (`public/reports/` sur le partage NFS)
restent limitées au LAN et peuvent être supprimées.

## Résultats des scans

| Outil | Résultat | Lecture |
| --- | --- | --- |
| Lynis 3.x | Indice **73**/100 ; 1 avertissement (`grpck` : erreurs dans les fichiers de groupes), une trentaine de suggestions | Voir plus bas |
| rkhunter | 892 lignes, 116 binaires « modifiés » | Base de référence jamais refaite depuis la mise à niveau 26.04 : les 116 binaires correspondent tous aux sommes de leur paquet (`dpkg --verify`, `su` vérifié en root). Pas de rootkit détecté. Refaire `rkhunter --propupd` après chaque mise à niveau |
| OpenSCAP, CIS niveau 1 poste de travail | **260** conformes, **100** en échec, 36 non applicables | Contenu SSG 24.04 adapté à 26.04 (test `DISTRIB_CODENAME`) : indicatif |
| ClamAV (`/var/www`, `/opt`, `/usr/local`, `/etc`, `/tmp`, `/var/tmp`, `~/Downloads`) | **Incomplet** : arrêté après 2 h (limite), sans résumé ; 2 détections `php.include.remote.526.UNOFFICIAL` avant l'arrêt | Faux positifs probables : cache NVD (JSON de CVE) de `/opt/dependency-check-7.1.0-release` (2022), signature d'une base tierce. `clamscan` seul, à `nice 19`, est trop lent pour ce périmètre : passer par `clamd` (`clamdscan --multiscan`) |
| ClamAV, tâche root de nuit (`clamscan -r /home/albandrieu`, ClamTk) | Lancée à 00:00 le 16/11, **tuée à 08:08** sans résumé | Jamais terminée sur ce volume ; ses seules détections (`Heuristics.Zip.OverlappingFiles`, cache des modules Go) sont des faux positifs. Retirée au lot 2 : premier scan complet par `security-scan@clamav` le samedi 21/11 à 01:00 |

Échecs OpenSCAP les plus utiles pour un poste de travail : verrouillage de
session GNOME (délai, verrouillage), bannière de connexion, `pam_faillock` et
`pam_pwhistory`, mot de passe GRUB et UEFI, AppArmor (profils non chargés,
paramètre de démarrage), `sysctl` réseau (`rp_filter`, `log_martians`,
redirections IPv6), `nodev`/`nosuid` sur `/home`, `noexec` sur `/tmp`, core
dumps, `cron.allow`/`at.allow`, SSH (bannière, `LoginGraceTime`,
`AllowUsers`, MAC). Les règles « supprimer Apache, rsync, ufw » ne
s'appliquent pas à ce poste.

## Constats, du plus grave au moins grave

### Critique : élévation utilisateur vers root

La crontab root exécute des scripts que l'utilisateur `albandrieu` peut modifier :

| Tâche root | Fichier | Propriétaire |
| --- | --- | --- |
| Toutes les heures | `~/w/nabla/env/linux/run-perf-monitoring.sh` | albandrieu:docker 755 |
| 03:00 | `~/w/nabla/env/linux/run-audit-log-cleanup.sh` | albandrieu:docker 755 |
| Lundi 23:30 | `~/.linuxbrew/bin/pgbadger` | albandrieu |

`/opt/script/boot-update.sh` (root, au démarrage) lance aussi
`~/.conky/startconky.sh` (770 albandrieu) et `.../nabla/env/linux/cleanup-snap.sh`.
Tout processus lancé sous ce compte (navigateur, extension, dépendance npm)
peut donc devenir root.

### Haute

- **Crontab root morte ou dangereuse** : `lynis` (`/usr/local/lynis` absent),
  `oscap` (binaire cassé, chemin relatif `ssg-ubuntu2204`), `chkrootkit` et
  `maldet` (rapports vers `/var/www/nabla/...`, qui n'existe pas ; `maldet`
  désinstallé), `webmin` (`update.pl` absent), `rm -f /var/log/audit/audit.log.*`
  le 1er du mois (efface la piste d'audit), `speedtest` quotidien en root,
  `clamscan` de tout le home chaque nuit (encore en cours à 2 h).
- **Doublons** : `chkrootkit` (crontab + `cron.daily` + `chkrootkit.timer`),
  `rkhunter` (`cron.daily` + `cron.weekly`), Lynis (crontab + `lynis.timer`),
  AIDE et tripwire en parallèle, `debsums` quotidien, hebdomadaire et mensuel,
  `maldet` (`cron.d/maldet_pub` toutes les 5 min et `cron.daily`, binaire
  absent), `cron.monthly/clam_scan` (mode 644, jamais lancé).
- **Apache** : `public/ftp` → `/media/ftp` (tout le partage FTP lisible par URL
  connue) ; écoute toujours sur `*:8082` et `*:8087` (le correctif
  `Listen 127.0.0.1` du dépôt n'est pas appliqué) ; 8087 sert la page par défaut.
- **Binaires compilés à la main qui masquent les paquets** : `/usr/local/bin/oscap`
  (cassé) ; une arborescence Go 1.18 de 2022 **dans `/usr/bin/go`**, qui
  empêche `golang-go` de poser son lien ; ImageMagick de 2020 (déjà mis en
  quarantaine le 16/11, voir [howdy-cameras.md](howdy-cameras.md)).

### Moyenne

- `/opt/script/boot-update.sh` : pas de `set -euo pipefail`, `cd` non protégés,
  références mortes (`whatsie`, deux `clean_old_folders.py`), `zenity` et `brew`
  en root, diverge du modèle `templates/boot-update.sh-Ubuntu.j2`.
- `/opt/script/hide-location.sh` et `hide-mac.sh` : anciennes versions (sans la
  garde split-DNS du modèle), unités désactivées.
- `nabla-servers-bower-sample/.npmrc:11` : un jeton npm commenté, versionné sur
  GitHub. À vérifier puis révoquer s'il est réel.
- `nabla-site-apache/info.php` en mode 777 (hors DocumentRoot) ; `mod_php`
  chargé sans PHP servi.
- `public/freebox/*port-redirect*.bmp`, `truenas.html`, `snort.html` : plan du
  réseau publié.
- `auditd` actif avec un jeu de règles vide.
- Comptes et UID orphelins : `/opt/ansible`, `/opt/oracle`, `/opt/zabbix`
  appartiennent à l'UID 2000, sans compte.
- `cloudflared` : `warp-routing: enabled`, ingress géré à distance (non
  vérifiable ici).

### Basse

- 496 paquets supprimés avec configuration restante (`rc`).
- `download-TODELETE`, `jenkins`, `webalizer` (vides ou obsolètes) dans
  `/var/www`, et le `cron.daily/webalizer` qui tourne pour rien.
- JS obsolète dans bower-sample (non servi) ; `d3.v3` servi.

## Plan proposé

### Lot 1 : supprimer l'élévation vers root (appliqué le 16/11)

- Crontab root : les scripts de `~/w/nabla` et `~/.linuxbrew/bin/pgbadger` n'y
  sont plus (voir lot 2).
- `boot-update.sh` coupé en deux : la partie root
  (`templates/boot-update.sh-Ubuntu.j2` : apt, snaps désactivés, docker) ne
  lit plus aucun fichier de l'utilisateur ; le reste (mr, brew, pip, conky,
  docker compose) tourne dans l'unité utilisateur `boot-update-user.timer`,
  16 min après l'ouverture de session.
- `/etc/sudoers.d/tizen-emulator` (openvpn sans mot de passe, binaire absent)
  et `/etc/sudoers.d/gvm` (compte absent) déplacés dans
  `/var/backups/sudoers.d-20261116/` ; `visudo -c` OK.
- Restes d'OpenVPN Access Server, d'OpenVPN 3 et de GVM/OpenVAS, aucun binaire
  installé : unité `ospd-openvas.service` (lançait le scanner, en `gvm`),
  `/etc/openvpn/up.sh`/`down.sh`, politiques D-Bus `net.openvpn.v3.*`,
  `/usr/local/openvpn_as` (base, clés TLS du serveur web) et comptes système
  `_gvm`, `openvpn`, `nm-openvpn` et groupe `gvm` (root en était membre).
  Six paquets à l'état `rc`/`ic` purgés, flux NVT (`/var/lib/openvas`, 476 Mo)
  supprimé, le reste mis de côté dans
  `/var/backups/privilege-leftovers-20261116/` (root, 0700).

Reste critique : `security_sudoers_passwordless: [albandrieu]` dans
`workstation.yml` donne `NOPASSWD: ALL`, et les groupes `docker`, `lxd`,
`libvirt` et `microk8s` valent root. Proposition : sudo avec mot de passe ou
`pam_u2f` (YubiKey), porté par `nabla-yubikey` qui possède PAM.

### Lot 2 : un seul ordonnanceur pour les scans de sécurité (appliqué le 16/11)

`playbooks/security-scans.yml` (plan par défaut, écriture avec
`security_scans_apply` et `security_scans_apply_approved`) :

| Timer | Fréquence | Sortie |
| --- | --- | --- |
| `security-scan@lynis` | Chaque nuit, 03:10 | `lynis.txt`, `lynis-report.dat` |
| `security-scan@rkhunter` | Dimanche 03:40 | `rkhunter.txt` |
| `security-scan@clamav` | Samedi 01:00, `clamdscan --multiscan`, disques locaux | `clamav.txt` |
| `security-scan@openscap` | Le 1er du mois, 04:20, CIS niveau 1 poste de travail | Rapport HTML |

- `/opt/script/security-scan.sh` écrit en root dans
  `/var/lib/security-reports/<date>/` et dans le collecteur textfile de
  node_exporter (`security_lynis_hardening_index`,
  `security_clamav_infected_files`, `security_openscap_rules`,
  `security_scan_last_success_timestamp_seconds`).
- `OnSuccess=` lance `/opt/script/publish-security-reports.sh` en
  `albandrieu` : copie dans `/var/www/reports/security/` (local), garde
  90 jours, écrit `index.html`.
- Crontab root réduite à `MAILTO=""` et speedtest ; `lynis.timer` arrêté,
  `/etc/cron.monthly/clam_scan` supprimé, `APT_AUTOGEN` pour rkhunter.
- auditd tourne ses journaux (`max_log_file_action = ROTATE`) au lieu du `rm`
  mensuel ; `harden-os.yml` garde la même valeur.

Non fait : AIDE (tripwire absent) ; signaler les écarts avec la veille dans
`index.html`.

### Lot 3 : durcissement par les rôles

#### `AlbanAndrieu/ansible-role-security` (branché le 16/11, pas encore rejoué)

`requirements.yml` et `workstation.yml` utilisent maintenant le fork
(`albanandrieu.security`). Il est identique à `geerlingguy` de juillet 2024 ;
l'amont a avancé depuis (dernier commit le 01/11/2026). Simulation
(`--check --diff`) avec les variables de `workstation.yml` : 8 changements.

| Changement | Avis |
| --- | --- |
| `sshd` démarré (`security_sshd_state: started` par défaut) | **Corrigé** : `security_sshd_state: stopped` dans `workstation.yml`, sshd est masqué |
| `sshd_config` : `Port 9922`, `AllowUsers`, `PasswordAuthentication no`, `X11Forwarding no`… | Sans effet tant que sshd est coupé |
| `sshd_config` passe de `0600` à `0644` (`mode` codé en dur dans le rôle) | Contredit `ssh_hardening` (0600) : chaque rôle remet son mode. Corriger dans le fork (`mode: "0600"`) |
| `/etc/fail2ban/jail.local` : jail `sshd` sur 9922, journal systemd | Inutile sans sshd ; utile pour Apache (jails `apache-auth`, `apache-badbots`) |
| `50unattended-upgrades` réécrit | Garde la poche `-security`, perd ESM : ajouter `security_autoupdate_additional_origins` |

À faire dans le fork : `mode` 0600, pas de démarrage forcé de sshd, puis
rattraper l'amont.

#### `devsec.hardening` : ce que changerait l'application de `harden-os.yml`

Simulation du 16/11 (`playbooks/harden-os.yml --check --diff`) : **4 changements**,
le reste est déjà conforme depuis l'application du 10/11.

| Changement | Effet |
| --- | --- |
| auditd `max_log_file_action` | Aligné sur `rotate` (sinon `keep_logs` remplirait `/var/log/audit`) |
| `/var/log` `0775` → `0755` | Sans risque |
| `net.ipv4.conf.*.log_martians = 1` | Journalise les paquets impossibles ; sans risque |
| `ssh.service` désactivé | Déjà masqué |

#### Couverture plus durcie proposée

Chaque ligne se teste seule, en simulation d'abord :

| Variable ou action | Gain | Risque sur ce poste |
| --- | --- | --- |
| `os_mnt_home_enabled: true` (`nodev,nosuid` sur `/home`, ext4 séparé) | CIS ; bloque les binaires setuid dans `/home` | Faible |
| `os_mnt_tmp_enabled` avec `noexec` sur `/tmp` (tmpfs déjà `nosuid,nodev`) | Bloque l'exécution depuis `/tmp` | Moyen : installeurs, `pip`, `npm` qui compilent dans `/tmp` |
| `hidepid_option: "2"` avec `proc_mnt_options` et le gid de `polkitd` | Cache les processus des autres comptes | Moyen : outils GNOME |
| Règles auditd dans `/etc/audit/rules.d/` (le rôle n'en pose aucune) : identités, `sudo`, modules, horloge, `/etc/sudoers.d` | Traçabilité ; aujourd'hui **aucune règle** chargée | Faible, surveiller le volume |
| `os_security_suid_sgid_remove_from_unknown: true` après revue de la liste | Moins de binaires setuid | Moyen : vérifier la liste |
| `os_chmod_home_folders` | `0700` sur les homes | Casse motion → `~/Dropbox/motion` : à garder à `false` |
| Hors rôle : verrouillage GNOME par `dconf` (5 min), mot de passe GRUB (édition seulement), AppArmor `enforce` (265 profils déjà chargés), PAM `pam_faillock` et `pam_u2f` par `nabla-yubikey` | Échecs OpenSCAP les plus utiles | Faible |

### Lot 4 : Apache et ses expositions

État au 16/11 : `mpm_prefork` avec `php`, `proxy`, `proxy_http`, `ssl`,
`status`, `autoindex`, `rewrite` et `remoteip` ; `Listen 8082` et `8087` sur
toutes les interfaces ; cloudflared (tunnel configuré côté Cloudflare, sans
ingress local) arrive par `127.0.0.1`. En-têtes : `Server: Apache`, `ETag`,
`nosniff`, `frame-ancestors`.

Proposé, du plus utile au moins utile :

1. **Écoute** (fait le 16/11) : `127.0.0.1:8082` pour le tunnel, `*:8087`
   (ufw : LAN seulement) pour les rapports ; supprimer le vhost `*:80` mort.
2. **Tunnel** : `/reports` exige Cloudflare Access (fait côté Apache,
   application à créer côté Cloudflare) ; étendre Access à tout le nom d'hôte si
   rien ne doit être public ; restreindre
   l'ingress du tunnel aux seuls noms d'hôte publiés, et couper `warp-routing`
   s'il ne sert pas (il ouvre le LAN aux clients WARP).
3. **Contenu publié** : supprimer `info.php` (mode 777, `phpinfo()`), les pages
   freebox, truenas et snort de `public/`, et `public/ftp` →
   `/media/ftp` ; remplacer `FollowSymLinks` par `SymLinksIfOwnerMatch` là où
   des liens restent.
4. **Modules** : couper `autoindex` (`Options -Indexes`), `ssl` (pas de vhost
   443), `proxy`/`proxy_http` avec le `ProxyPass /api/` cassé, et `php` si plus
   rien n'en dépend (alors passer à `mpm_event`).
5. **En-têtes** (`conf-available/security.conf`) : `ServerTokens Prod`,
   `ServerSignature Off`, `TraceEnable Off`, `FileETag None`,
   `Referrer-Policy: strict-origin-when-cross-origin`,
   `Permissions-Policy: camera=(), microphone=(), geolocation=()`.
6. **Défense** : jails fail2ban `apache-auth` et `apache-badbots` (par le rôle
   fork) ; ModSecurity avec OWASP CRS seulement si des applications PHP
   restent exposées.
7. **Ménage `/var/www`** : archiver `download-TODELETE`, `jenkins`,
   `webalizer`, `sample`, et bower-sample s'il est abandonné.

Tout passe par `files/etc/apache2/` et `restore-etc.yml`, vérifié par
`curl` depuis le LAN (200) et avec `CF-Connecting-IP` public (403).

### Lot 5 : ménage

- `/usr/bin/go` (Go 1.18 de 2022) : mettre en quarantaine, puis
  `sudo apt install --reinstall golang-go`.
- `/usr/local/bin/oscap` cassé et `/opt/dependency-check-7.1.0-release` (2022) :
  supprimer.
- `sudo apt purge $(dpkg -l | awk '/^rc/{print $2}')` après revue de la liste.
- Corriger les erreurs de `grpck` ; réattribuer ou supprimer l'UID 2000.
