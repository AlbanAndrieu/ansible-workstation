# Sécurité de la workstation : audit du 16/11/2026 et plan de durcissement

**Statut :** audit fait, corrections urgentes et lots 1 et 2 appliqués le 16/11 ; lots 3 à 5 proposés.

Rapports : `/var/www/reports/security/` sur le disque local, servis par Apache en
`/reports` : `http://172.17.0.57:8087/reports/security/` depuis le LAN, et par le
tunnel Cloudflare derrière Cloudflare Access (voir « Accès aux rapports »).

## Réévaluation du 21 novembre 2026 — preuves et priorités

Les **derniers résultats des scanners sur la workstation accessibles dans cette documentation sont ceux du 16/11** ; aucun rapport brut du scan `security-scan@clamav` planifié samedi 21/11 n'a été fourni ou interrogé. Les trois workflows GitHub du 21/11 sur `9b672df` (CodeQL Python, Ansible Syntax, CI lint/contrats) ont conclu **success** ; `Molecule manual integration` est **skipped**. Ces statuts ne prouvent ni un OS sain ni une analyse complète de toutes les dépendances.

| Ordre | Interprétation fondée sur les rapports du 16/11 | Condition de réception |
| --- | --- | --- |
| **P0 — élévation de privilèges** | Les crons root qui exécutaient des scripts modifiables ont été supprimés le 16/11 (lot 1), mais `security_sudoers_passwordless: [albandrieu]` donne encore `NOPASSWD: ALL` selon la configuration décrite ; les groupes `docker`, `lxd`, `libvirt` et `microk8s` offrent d'autres chemins équivalents à root | Audit du sudoers **effectif**, des appartenances et des services réellement exploités, accès console de secours, suppression graduelle des droits non requis et test négatif |
| **P0 — rapports et WAN** | Apache autorise localement le tunnel avec un en-tête `Cf-Access-Jwt-Assertion` **sans validation cryptographique du JWT** ; application Cloudflare Access pas créée dans le rapport du 16/11. La confiance locale `CF-Connecting-IP` doit rester strictement liée à cloudflared | Application Access réelle avant publication, vérification signature/audience ou délégation prouvée au tunnel, 403 depuis WAN sans identité, aucun accès direct :8082/8087 |
| **P1 — Lynis** | 73/100 et un avertissement `grpck`. Ce score est un indice de configuration, **pas** une probabilité de compromission | Corriger les groupes orphelins après inventaire UID/GID ; enregistrer la différence de score et les tests encore applicables |
| **P1 — OpenSCAP CIS L1** | 260 PASS, 100 FAIL, 36 N/A sur contenu 24.04 adapté à 26.04 ; **pas de certification de conformité 26.04** | Revalider la compatibilité SSG, classer les échecs par contrôle, traiter GNOME lock, auditd, AppArmor, réseau ; justifier les règles inapplicables (Apache/Docker/NFS) |
| **P1 — rkhunter** | 116 binaires `modified` correspondent aux fichiers de paquets selon `dpkg --verify` documenté ; **aucune preuve de rootkit** | Rafraîchir la baseline `--propupd` seulement après preuve des paquets installés signés, conserver un diff du rapport |
| **P1 — ClamAV** | Deux détections `php.include.remote.526.UNOFFICIAL` sur cache NVD et détections `Heuristics.Zip.OverlappingFiles` ; les deux scans ont été interrompus (2 h et 8 h) | Conserver échantillons en quarantaine hors publication, provenance/signature des bases tierces, résultat `clamdscan --multiscan` avec résumé et durée ; `NOT_RUN` jusqu'à preuve du timer du 21/11 |
| **P2 — traçabilité** | `auditd` tournait avec règles vides avant les lots appliqués ; AIDE pas encore en place | Charger une allowlist minimale de règles et tester événement → journal, mesure de rétention et surcharge I/O |

**Risque de chaîne d'approvisionnement :** le cache Nexus [prévu pour APT/npm/PyPI/Docker](workstation-nexus-package-cache.md) ne fournit pas gratuitement la quarantaine Repository Firewall. Conserver CodeQL, scans SCA, SBOM, signature des métadonnées APT et contrôle des digests Docker. L'ancienne version de Nexus déclarée dans Compose (`3.92.3-alpine`) doit être revue séparément.

## Complément 21 novembre — preuves NFS/Apache (fournies par l'opérateur)

Le montage `/media/www` est un **automount systemd NFSv4.2** depuis
`nabla:/mnt/cpool/www`, avec `nosuid,nodev,noexec`.
Les symlinks historiques `/var/www/nabla-site-apache` et
`/var/www/nabla-site-bababou` pointent vers ce partage :
**ces sites sont servis en NFS, sans miroir local**.

`sudo apache2ctl -S` n'affiche que `*:80` et `*:8082`, exécutés
comme `www-data`, et aucun VirtualHost 8087 ou 443 dans les éléments
fournis. Il s'agit de l'état réellement observé, à distinguer de
l'`Alias /reports` sur port 8087 **préparé mais non réceptionné**
dans cette PR. `Main DocumentRoot: /var/www/html` ne décrit pas à lui
seul le `DocumentRoot` de chaque VirtualHost : les vhosts du dépôt
peuvent servir `/var/www/nabla-site-apache/public`.

`getfacl -p /media/www/nabla-site-apache/public` prouve
`owner=albandrieu`, `group=www-data`, ACL `user::rwx`,
`group::rwx`, `other::r-x` : le groupe Apache a le **droit
d'écriture** dans la racine NFS du site. C'est un risque de
modification du contenu servi (PHP est chargé), **à revoir avant
toute bascule d'ACL** pour ne pas casser le flux de déploiement.
Modules vus : `php_module`, `proxy_module`, `proxy_http_module`,
`remoteip_module`; aucune preuve de `security2_module` chargé
dans ce filtre. `AH00558` est un avertissement `ServerName` global
sans effet sur le succès de `apache2ctl -S`.

Architecture CTEM prévue, **non attestée déployée** :

```text
TrueNAS /mnt/cpool/ctem/amass/reports  [privé, jamais NFS]
   └─ export expurgé /mnt/cpool/www/reports/ctem
         └─ NFS /media/www/reports/ctem (source à revalider)
               └─ publish-ctem-web-mirror.py (non-root, opt-in)
                     └─ /var/www/reports/ctem (local)
                           └─ Apache Alias /reports (LAN only)
```

Sur la workstation, contrôles **en lecture seule** :

```bash
sudo apache2ctl -S
sudo grep -R -n -E 'Alias /reports|Listen 8087|ServerName' \
  /etc/apache2/sites-enabled /etc/apache2/conf-enabled /etc/apache2/ports.conf
findmnt -T /media/www/reports -o TARGET,SOURCE,FSTYPE,OPTIONS
namei -l /var/www/reports /var/www/nabla-site-apache/public
getfacl -p /media/www/nabla-site-apache/public /var/www/reports
python3 /opt/script/publish-ctem-web-mirror.py --check
```

Le préflight peut retourner `NOT_RUN` / fichier absent si le pilote
n'est pas installé : ne pas assimiler cela à une panne du serveur ou
à une validation du partage. Le producteur expurgé et les règles de
minimisation sont documentés dans
[nabla-compose #436](https://github.com/AlbanAndrieu/nabla-compose/pull/436)
et dans son
[runbook commun](https://github.com/AlbanAndrieu/nabla-compose/blob/feat/ctem-vantage-isolated-20261121/docs/runbooks/workstation-truenas-report-sharing-and-honeypot.md).

## 21 novembre 2026 — tableaux de bord des scans (CODED, non déployé)

Le pipeline versionné prépare un résumé HTML statique et un fichier JSON
`workstation-security-summary/v1` contenant les dates, statuts et compteurs
des quatre scanners. Les rapports complets restent disponibles uniquement
sur le LAN ; le résumé ne contient aucun finding brut ni nom d'hôte.

Les états `COMPLETE`, `INCOMPLETE`, `PARTIAL` et `NOT_RUN` sont distincts.
Une erreur ClamAV ne doit jamais être interprétée comme un scan terminé.
Les contrats offline exercent la génération du rapport à partir de données
de test, ainsi que l'absence de texte sensible dans la synthèse.

L'ancien contrôle Apache fondé sur un simple en-tête de demande Access
est remplacé, dans la configuration versionnée, par un accès LAN uniquement.
Avant toute réouverture distante, réceptionner une vérification réelle du
jeton signé et des tests de refus extérieur.

Une intégration DefectDojo doit passer par l'importeur privé existant de
`nabla-compose` et uniquement pour des findings qualifiés et revus.
Sur `nabla-site-alban`, ne publier qu'une éventuelle synthèse agrégée
explicitement autorisée ; pas de connexion à l'API DefectDojo ni de rapports
bruts dans le bundle public.
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

## NFS minimal, Code Server et rapports CTEM (21/11/2026)

### Pourquoi la workstation voit-elle `/mnt/cpool/code` ?

`nabla-compose/apps/code/compose.yml` publie des chemins TrueNAS dans
le **conteneur Code Server** : `/mnt/cpool/code:/code-server`,
`/mnt/cpool/code/config:/config` et plusieurs dossiers frères.
Ce montage Docker est distinct d'un partage **NFS workstation**.
Dans `defaults/main.yml` et les exports déclarés par
`playbooks/truenas-nfs-shares.yml`, `cpool/code` n'est pas un
partage workstation légitime. Le code NFS crée maintenant des
déclarations `state: absent` pour les exports exacts :

- `/mnt/cpool/code`
- `/mnt/cpool/ctem`
- `/mnt/cpool/ctem/amass/reports`
- `/mnt/cpool/var/nabla/ops-logs`

Ces interdictions sont **CODED / NOT_APPLIED**. Le playbook NFS ne
supprime rien en mode plan ; il laisse actuellement les exports
**non déclarés** intacts. Contrôler également tout export parent
`/mnt/cpool` ou `/mnt/cpool/var`, qui contournerait une suppression
par chemin exact.

Pour identifier le mécanisme réel sur la workstation, **sans lancer
un `find` récursif sur les NFS automounts** :

```bash
findmnt -T /mnt/cpool/code -o TARGET,SOURCE,FSTYPE,OPTIONS || true
readlink -f /mnt/cpool/code || true
findmnt -rn -t nfs,nfs4 -o TARGET,SOURCE,OPTIONS
ls -ld /mnt/cpool /mnt/cpool/code 2>/dev/null || true
```

Sur TrueNAS, l'inventaire des exports reste
`sudo midclt call sharing.nfs.query`. Exécuter
`playbooks/truenas-nfs-shares.yml` sans `truenas_nfs_apply=true`
pour voir le plan avant de demander une suppression explicite.
Code Server doit être audité séparément : ses montages RW
`nginx,drawio,compose,traefik,prometheus,grafana,litellm` sont
trop larges pour une configuration Zero Trust ; limiter chaque
montage à l'usage réellement attendu, de préférence en lecture seule.

### Distribution CTEM vers `/media/www`, puis Apache

Le répertoire TrueNAS privé
`/mnt/cpool/ctem/amass/reports` reste hors NFS/Apache. Seule sa
synthèse **sans FQDN, sans IP ni entité Backstage** est projetée dans
le partage existant :

| Provenance | Destination / effet |
| --- | --- |
| TrueNAS `/mnt/cpool/www/reports/ctem` | Deux fichiers expurgés, copie dans le NFS `www` |
| Workstation `/media/www/reports/ctem` | Vue du partage TrueNAS, **non directement servie** |
| Workstation `/var/www/reports/ctem` | Miroir local des deux fichiers, revalidé puis HTML reconstruit |
| Apache `/reports/ctem/` | `Alias /reports /var/www/reports` déjà existant, **LAN uniquement** tant qu'Access JWT n'est pas vérifié |

La copie locale évite de remonter `/media/www` lors de chaque requête
Apache, conformément à la stabilisation du 16/11. Le playbook
`security-scans.yml` installe désormais
`/opt/script/publish-ctem-web-mirror.py` **sans le planifier**.
Il refuse l'HTML venant de NFS et tout champ JSON inattendu
(y compris sous-domaines ou données brutes) ; il reconstruit
localement un HTML statique `noindex` et un JSON 0640 avec groupe
`www-data`. Recette après publication TrueNAS :

```bash
# Sur workstation, utilisateur propriétaire de /var/www/reports (pas sudo)
python3 /opt/script/publish-ctem-web-mirror.py --check

CTEM_WORKSTATION_MIRROR_APPROVED=YES \
  python3 /opt/script/publish-ctem-web-mirror.py --apply
```

Aucun timer, `rsync` récursif du NAS, ni changement de VirtualHost
Apache n'est ajouté. **La configuration Apache de cette PR refuse les
accès au rapport qui ne proviennent pas du LAN** : elle n'accorde plus
l'accès sur la seule présence d'un en-tête
`Cf-Access-Jwt-Assertion`. Il faudra une vraie vérification
cryptographique du JWT ou une protection équivalente avant d'envisager
un accès externe. Contrôler les clients NFS autorisés séparément.

### Autres candidats à un portail local de synthèses

- **Acceptables après expurgation** : état Gatus / couverture Prometheus
  agrégée, score Lynis et dérive de conformité, récapitulatif
  `checkdmarc` SPF/DMARC, compte de findings DefectDojo par sévérité,
  rapports de disponibilité TrueNAS (statuts et dates sans adresses),
  FinOps Vercel agrégé.
- **Ne pas publier tels quels** : JSON Amass des sous-domaines, graphe
  PostgreSQL, rapports Nuclei/ZAP avec URLs et réponses, fichiers
  complets Lynis/rkhunter/ClamAV/OpenSCAP contenant chemins ou noms
  internes, dumps de bases, logs d'authentification ou logs
  `nabla-ops-logs`. Pour ces derniers, utiliser le coffre privé et une
  visualisation authentifiée, pas Apache statique.

### Identification du journal `reconcile-f51102a8.log`

Le SHA abrégé `f51102a8` correspond au commit
`f51102a814fe5b69475c08b76bee7941f7e35814` de
`nabla-compose` (8/11/2026), une fusion de `origin/master` dans
`ccr-bc925643-xffav2` avec résolution de conflits de roadmap et
catalogue. L'emplacement par défaut des journaux d'exploitation est
`/mnt/cpool/var/nabla/ops-logs` depuis `scripts/cron.sh`.
L'origine précise du fichier et son contenu **ne peuvent être
authentifiés sans un `stat` et une lecture locale contrôlée**.

Sur le NAS, si le fichier existe dans ce dossier :
`sudo stat -c '%n %s bytes %a %U:%G %y' /mnt/cpool/var/nabla/ops-logs/reconcile-f51102a8.log`.
Conserver privé, ne jamais le publier sur `/media/www` ou Apache.

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
