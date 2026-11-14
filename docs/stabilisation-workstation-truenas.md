# Stabilisation : workstation, puis TrueNAS (relevé du 4 novembre 2026)

Audits en lecture seule, puis corrections du 5 et du 6 novembre. Les causes notées « suspecté » ne
sont pas prouvées.

## Déjà corrigé

| Quoi | Preuve |
| --- | --- |
| Glances local en échec depuis le boot du 3/11 : clé `web_4_description` en double (ligne 512) | `web_6_description` ; écoute sur `127.0.0.1:61209` |
| node_exporter, ServerActive de zabbix-agent2, entrée Glances `truenas` | [workstation-network-hardening.md](workstation-network-hardening.md#liens-avec-truenas-relevé-du-4-novembre-2026) |
| Sondes de `172.17.0.1` vers le port 3000 (bloquées par ufw toutes les 20 s) | Arrêtées à 19:53, quand le honeypot a été retiré de pfSense |
| Partages NFS et hôte Zabbix décrits en code | [`truenas-nfs-shares.yml`](../playbooks/truenas-nfs-shares.yml), [`zabbix-workstation-host.yml`](../playbooks/zabbix-workstation-host.yml) |
| Journal à `SystemMaxUse=2G` (il ne couvrait que 30 h) ; `JOURNAL_MAX` du script de nettoyage aligné à `2G` | journald `max 2G` |
| Purge de `cloud-init` (logrotate en échec chaque jour) et de `linux-cloud-tools-*` (90 s perdues au boot sur `hv_kvp`) | logrotate `Result=success`. Le gain au boot se verra au prochain redémarrage. |
| `cento`, `bitcoin-qt` et `xscreensaver` arrêtés ; `screensaver_enabled` et `bitcoinqt_enabled` à `false` | `systemctl --failed` vide, système et utilisateur |
| Collecteurs SMART, NVMe et apt réinstallés ; node_exporter lit aussi `/var/lib/prometheus/node-exporter` | 263 métriques `smartmon_`, `nvme_`, `apt_` sur `172.17.0.57:9100` |
| node_exporter : collecteurs `cpu`, `meminfo`, `loadavg`, `filesystem` et `systemd` pour le heartbeat OpenClaw et le briefing du matin ; drop-in `wait-for-lan.conf` (attend `network-online.target`, `Restart=on-failure` toutes les 5 s sans limite) codé ici | `node_scrape_collector_success` à 1 pour les six collecteurs ; `active` et `enabled` après un redémarrage |
| Santé de postgres et redis (aucune autre sonde) : `workstation_container_healthy{container=…}`, écrit chaque minute par `docker-health-textfile.timer` ([script](../files/docker-health-textfile.sh)). Le collecteur nabla-openclaw ne la lit pas encore. | Les deux à `1` sur `172.17.0.57:9100` ; `node_textfile_mtime_seconds` signale un fichier figé |
| Docker (`/docker`) et containerd (`/var/lib/containerd`, en bind) sur le LV NVMe `vg-docker/docker-nvme0` | 43 Go sur 144 Go ; les 12 conteneurs relancés. Anciennes copies supprimées le 9/11 (`/` : 84 → 74 %). |
| Disques durs : `apm = 254` (têtes garées sans arrêt, `sdc` au-delà de 300 000 cycles) ; écritures en attente plafonnées à 1 Gio au lieu de 15 % de 62 Go | `APM_level 254` ; `vm.dirty_bytes = 1073741824`. Suite : [roadmap stockage](roadmap-workstation.md#9-novembre-2026--stockage) |
| Gel quand TrueNAS est arrêté ou surchargé : les 12 partages NFS étaient montés en permanence (`hard`), et `bg` faisait attendre systemd sans limite (`TimeoutSec=infinity`, `retry=10000`). Ils sont maintenant en `x-systemd.automount` : montés au premier accès, démontés après 5 min d'inactivité, abandon au bout de 20 s si TrueNAS ne répond pas. Le playbook refuse aussi de tourner si le port NFS 2049 est fermé. Détails plus bas. | 12 unités `media-*.automount` actives ; sauvegarde `/etc/fstab.1233265.2026-11-06@21:22:59~` |
| `mongod` arrêté et désactivé : aucun client depuis le 28/11/2025, et sa collecte FTDC faisait un `statfs` par seconde sur chaque partage NFS | `strace` : 120 `statfs` sur `/media` en 8 s, 0 depuis l'arrêt. Données intactes dans `/var/lib/mongodb` ; `sudo systemctl enable --now mongod` pour le relancer. |
| Conky orange : anneaux `/media/bitcoin` et `/media/photo` retirés. Conky les interrogeait chaque seconde (montages jamais libérés, conky figée pendant une panne). | Copie dans `~/.conky/ConkyOrange/conky_orange_4k.lua.bak-20261106` (fichier non suivi par le dépôt dotfiles) |
| NFS : `rsize/wsize=16384` remplacés par la taille négociée (1 Mio) | Lecture directe de 1 Gio : 17 Mo/s et 65 536 requêtes avant, 25 Mo/s et 1 024 requêtes après |
| `awstats` purgé : son cron échouait toutes les 10 min, et il n'a jamais rien produit (`/var/lib/awstats` vide depuis 2020, logs apache illisibles par www-data). `sudo apt install awstats` pour revenir. | `/etc/cron.d/awstats` absent |
| Métriques GPU `nvidia_gpu_*` et réglage d'ollama dans un drop-in | [gpu-llm-workstation.md](gpu-llm-workstation.md) |
| Samsung C49HG9x à 120 Hz (`1920x1080@119.879` sur DP-2 et HDMI-2) au lieu de 144 Hz | Appliqué en persistant (`~/.config/monitors.xml`, dépôt dotfiles). À surveiller : un nouvel arrêt brutal infirmerait la piste. |

Les changements de la workstation passent par
[`stabilize-workstation.yml`](../playbooks/stabilize-workstation.yml) (`mise run stabilize-check`), sauf
le réglage d'écran.

### Migration de Docker sur le NVMe (6 novembre 2026)

Le playbook monte le LV et refuse de le faire par-dessus un dossier non vide. La copie s'est faite à
la main, conteneurs arrêtés :

```bash
docker ps -q --no-trunc > running.txt && docker stop $(cat running.txt)
sudo systemctl stop docker.socket docker.service containerd.service
sudo mount /dev/vg-docker/docker-nvme0 /mnt/docker-nvme   # restes de 2022 rangés dans .old-2022
sudo rsync -aHAXS --numeric-ids /docker/ /mnt/docker-nvme/
sudo rsync -aHAXS --numeric-ids /var/lib/containerd/ /mnt/docker-nvme/containerd/
sudo umount /mnt/docker-nvme
sudo mv /docker /docker.pre-nvme && sudo mkdir -m 710 /docker
sudo mv /var/lib/containerd /var/lib/containerd.pre-nvme && sudo mkdir -m 700 /var/lib/containerd
.venv/bin/ansible-playbook -i localhost, -c local playbooks/stabilize-workstation.yml \
  -e stabilize_apply=true -e stabilize_apply_approved=true
sudo systemctl start containerd docker && docker start $(cat running.txt)
sudo systemctl start litellm.service   # son ExecStop a fait « compose down »
```

Sauvegardes supprimées le 9 novembre, après trois jours sans problème (43 Go libérés sur `/`) :

```bash
sudo rm -rf /docker.pre-nvme /var/lib/containerd.pre-nvme
```

### Pourquoi la workstation gelait sans TrueNAS (6 novembre 2026)

- Un `daemon-reload` (Ansible, apt) lance les générateurs dans un bac à sable qui ouvre chaque point de
  montage. Sur un montage NFS `hard` dont le serveur ne répond plus, cette ouverture attend le retour
  du serveur, et PID 1 attend avec elle (`do_wait`) : plus de `systemctl` ni de `sudo`.
- Un point d'automount au repos n'est pas un montage NFS : rien ne contacte TrueNAS. Vérifié avec un
  automount de test vers une adresse muette (`192.0.2.1`) : `daemon-reload` en 0,8 s. Un accès échoue
  en `No such device` au bout de 20 s, ou 40 s s'il attend une tentative déjà en cours.
- Les montages encore actifs pendant une panne restent exposés : restic la nuit, apache
  (`/var/www/nabla-site-*` pointe vers `/media/www`) et l'outil Claude Code. Avant chaque commande,
  celui-ci accède à tous les points de montage ; pendant une panne, chaque commande attendra donc le
  délai de 20 s.
- Pour remettre un partage comme avant : remettre ses options d'origine dans `/etc/fstab` (voir la
  sauvegarde), puis `sudo systemctl daemon-reload`, avec TrueNAS joignable.

### Test de `softreval` (7 novembre 2026)

Serveur NFSv4.1 jetable (nfs-ganesha en mémoire, dans un conteneur), monté une fois en `hard` et une
fois en `hard,softreval,timeo=50,retrans=1`. Deux pannes : serveur gelé (TCP ouvert, aucune réponse,
comme un TrueNAS surchargé), puis interface coupée (comme un TrueNAS éteint). Chaque commande est
coupée au bout de 25 s.

| Après 65 s de panne | `hard` | `hard,softreval` |
| --- | --- | --- |
| `stat` d'un fichier, `ls`, `statfs` | bloqués, dans les deux pannes | bloqués, dans les deux pannes |
| `daemon-reload` | 0,8 à 1,0 s | 0,8 s |
| Retour du serveur | immédiat | immédiat |

`softreval` ne sert pas les attributs en cache pendant ces pannes ; il n'est pas adopté. Explication
probable, non vérifiée : en NFSv4.1 sur TCP, le client ne compte pas d'expiration tant que la
connexion reste ouverte. `daemon-reload` n'a pas figé PID 1, contrairement au 6/11 : une panne plus
longue ou un redémarrage de TrueNAS (reprise d'état NFS) pourrait être la condition manquante. Les
automounts restent la protection : un partage non utilisé n'est pas monté.

### Apache (7 novembre 2026)

Apache 2.4.66 (prefork, mod_php 8.5) écoute sur 8082 et 8087, ouverts au LAN par ufw. En 7 jours de
journaux, seuls la workstation et les sondes de santé de pfSense (`172.17.0.1`) l'ont appelé :
`www.albandrieu.com` pointe vers Cloudflare.

| Constat | Correctif ([`stabilize-workstation.yml`](../playbooks/stabilize-workstation.yml)) |
| --- | --- |
| La racine du 8082 était tout le dépôt `nabla-site-apache` : `.git/`, `terraform.tfvars`, `.envrc` et deux `info.php` téléchargeables depuis le LAN | Racine sur `public/` ; `/public/…` garde ses URL par un `Alias` |
| Aucun blocage des fichiers cachés, listing des répertoires actif sous `/var/www`, `Server: Apache/2.4.66 (Ubuntu)` | [`security.conf`](../files/etc/apache2/conf-available/security.conf) : 404 sur tout chemin en `/.` (sauf `.well-known`), `info.php` et `php.ini` ; `ServerTokens Prod`, `ServerSignature Off`, `nosniff`, `frame-ancestors 'self'` ; `Indexes` retiré |
| pfSense sonde `OPTIONS /` et `OPTIONS /test.php` toutes les 0,5 s : 200 000 lignes d'accès et 100 000 erreurs PHP par jour (39 Mo chacun) | Sondes hors du journal d'accès ; `/test.php` répond 404 avant PHP |
| Rotation des journaux cassée depuis le 6/11 : PID 1 figé (gel NFS), le `reload` de logrotate a échoué, apache écrivait encore dans `access.log.1` | Le rechargement du 7/11 a rouvert les journaux |
| Vhost `*:3000` (honeypot) sans `Listen` ; huit modules chargés sans usage (`proxy_ajp`, `proxy_balancer`, `proxy_connect`, `proxy_fcgi`, `proxy_html`, `xml2enc`, `slotmem_shm`, `vhost_alias`) | Vhost retiré, modules désactivés |

Non corrigé : `/api/` est relayé vers `albandrieu.albandrieu.com:80` (`127.0.0.1`), où rien n'écoute
(503) ; la sonde `/test.php` de pfSense vise un backend HAProxy obsolète, à retirer côté pfSense.

## Workstation, reste à faire

| # | Problème et preuve | Correctif proposé | Où |
| --- | --- | --- | --- |
| 1 | LiteLLM vers Redis : 360 erreurs `invalid username-password pair` en 6 h. Cache et suivi des dépenses hors service. Cause (7/11) : le mot de passe de `REDIS_URL` diffère du `requirepass` du conteneur `redis`, qui utilise la valeur par défaut écrite dans `compose.redis.yml`. LiteLLM est son seul client. | Nouveau mot de passe aléatoire dans `REDIS_AUTH` (`.env` de nabla-compose) et dans `REDIS_URL` (`~/.litellm/.env`), puis recréer les deux conteneurs (secret : à faire à la main). **CORRIGÉ le 13/11** : `/cache/ping` de LiteLLM `ping_response: True`, 0 erreur Redis. Vraie cause : le profil shell (`pass/database.key.env.sh`) exporte `REDIS_URL`, `REDIS_AUTH` et `DATABASE_URL`, que Compose préfère aux `.env` ; selon le shell qui lançait Compose, Redis et LiteLLM recevaient des mots de passe différents. Son `DATABASE_URL` visait encore `172.17.0.57:5432`, fermé depuis que `postgres` n'écoute que sur `127.0.0.1` (nabla-compose `ec2c2391`) : LiteLLM s'arrêtait à chaque recréation. L'opérateur a aligné le profil (même mot de passe, hôte `postgres:5432`) et le `REDIS_AUTH` du `.env` de nabla-compose : profil, `.env`, `~/.litellm/.env` et Redis en service ont la même valeur (comparée par empreinte). `compose.redis.yml` refusera de démarrer sans `REDIS_AUTH` ([nabla-compose#371](https://github.com/AlbanAndrieu/nabla-compose/pull/371)). [`scripts/rotate-workstation-redis-password.sh`](../scripts/rotate-workstation-redis-password.sh) refuse de tourner si le shell exporte ces variables, et réécrit aussi `.env.secrets` et `.env.local` quand ils définissent `REDIS_AUTH` (mise les charge dans le shell de nabla-compose, `[env] _.file`). Une prochaine rotation doit aussi mettre la valeur dans le profil | nabla-compose, `~/.litellm/.env` |
| 2 | ~~Grafana local : 13 036 erreurs en 6 h. Ses règles visent `prometheus` et `loki`, qui n'existent pas en local.~~ Codé le 10/11 (nabla-compose PR #346) : `GF_UNIFIED_ALERTING_EXECUTE_ALERTS=false`. Les règles Temporal n'ont rien à surveiller, ni ici ni sur TrueNAS. | Recréer le conteneur après la fusion : sa base `grafana.db` n'a pas de volume et sera perdue | nabla-compose |
| 3 | ~~doco-cd : le sous-module `apps/fastapi-sample` est en SSH, sans clé.~~ `.gitmodules` est en HTTPS depuis le 6/11 (`512aad42`) ; seul le cache arrêté de doco-cd garde l'URL SSH (`/mnt/cpool/dococd/…/mirror/config`). | Corriger ce cache seulement si doco-cd revient sur la station | — |
| 4 | ~~`restic-backup.yml` réécrivait `ARGS` de node_exporter sans les collecteurs `cpu`, `meminfo`, `loadavg` et `filesystem` de `stabilize_node_exporter_flags`.~~ Corrigé le 10/11 : son fichier porte les mêmes options (test de contrat). | — | — |
| 5 | `/home` occupe 141 Go sur `/`. | Inventaire avec `mise run cleanup-check` | `scripts/workstation-cleanup.sh` |
| 6 | Un `daemon-reload` pendant une panne de TrueNAS a figé PID 1 le 6/11, avec des partages montés. Les tests du 7/11 ne reproduisent pas ce gel (voir plus bas) : la condition exacte reste inconnue. | Ne pas lancer apt pendant un arrêt de TrueNAS. `softreval` n'aide pas (testé le 7/11). | `/etc/fstab` |
| 7 | Les conteneurs résolvent par `9.9.9.9` puis Pi-hole sur TrueNAS (`/etc/docker/daemon.json`) : 27 échecs vers `9.9.9.9` en 24 h. | Passer à `172.17.0.1` comme l'hôte (redémarrage de Docker et recréation des conteneurs) | `/etc/docker/daemon.json` |
| 8 | msmtp n'a aucune configuration : chaque sortie de cron finit en `status 0x004e from MTA` (awstats toutes les 10 min jusqu'au 7/11, `wacli` et `vdirsyncer` chaque heure). La sortie est perdue. | Configurer `/etc/msmtprc`, ou `MAILTO=""` et rediriger vers `logger`. **14/11** : les deux lignes de la crontab utilisateur sont commentées (sauvegarde `~/.crontab.bak-20261114-105404`) : `/usr/bin/wacli` n'existe plus (seule sa base reste dans `~/.local/state/wacli`), et `vdirsyncer.timer` (utilisateur, paquet) synchronise déjà toutes les 15 min. Restent perdus : les rapports de `debsecan` (horaire) et d'`apticron` | crontab utilisateur, `/etc/msmtprc` |
| 9 | Crontab root (ClamTk) : `clamscan -r /home/albandrieu` à minuit, plus de 1 h 40 à 100 % d'un cœur, sans `nice`. `maldet -a /` appelle un binaire désinstallé et publie un rapport vide. `chkrootkit` tourne deux fois (crontab et `chkrootkit.timer`). | **Codé le 10/11, revu le 13/11**, apply à faire : lignes ClamTk, `maldet` et `chkrootkit` retirées (le rapport HTML de chkrootkit disparaît avec) ; `clamav-local-disks` hebdomadaire sur les disques locaux, sans les partages TrueNAS | [`stabilize-workstation.yml`](../playbooks/stabilize-workstation.yml) |
| 10 | Port USB `1-1.3` : un périphérique refuse l'énumération (`error -71`), le 6/11 à 16:41. | Changer de câble ou de port | Matériel |
| 11 | Open-AudIT (installé en 2024 sous `/usr/local/open-audit`) : `/etc/cron.d/open-audit` lance PHP chaque minute, sans MySQL ni MariaDB installés ni site Apache. | **Désactivé le 14/11** : renommé `open-audit.disabled-20261114` (cron ignore les noms avec un point) ; plus aucun lancement dans le journal. Retour : remettre le nom `open-audit` | `/etc/cron.d` |
| 12 | Environ 5 000 `[UFW BLOCK]` par jour dans le journal. Les principaux viennent de pfSense (`172.17.0.1`) vers des ports où rien n'écoute : syslog UDP `1514` (ancienne cible, déjà notée « à retirer » dans nabla-compose) et TCP `3000`, `9000`, `8081` (backends HAProxy `ntopng`, `albandrieu`, `graylog`… vérifiés chaque seconde, services partis de la station). | Retirer la cible syslog et ces backends dans pfSense | pfSense (nabla-compose) |
| 13 | DNS : 4 248 délais dépassés sur 223 808 requêtes en 24 h (1,9 %), groupés (13/11 vers 14 h, 20 h, 21 h, 14/11 vers 0 h) : `vdirsyncer` a échoué 1 023 fois rien qu'entre 14 h et 15 h. La station n'interroge que `172.17.0.1`, en DNSSEC strict. | Chercher côté pfSense et Pi-hole ce qui tombe à ces heures ; le DNSSEC strict reste un choix voulu | pfSense, Pi-hole (TrueNAS) |
| 14 | `libvirtd` tourne sans aucune VM (22 Mo, 5 `dnsmasq`, `virbr0` éteint) et écrit 32 erreurs par jour sur les `veth` de Docker qui disparaissent. | Proposé : `sudo systemctl disable --now libvirtd.service`. Ses sockets restent actives et le relancent à la demande (`virsh`, virt-manager) | systemd |

Suspecté :

- DNSSEC strict (une panne du routeur casse le DNS et remplit le journal) ;
- redémarrage en attente.

Vérifié sain :

- disques : SMART PASSED partout ;
- système : 0 OOM, mémoire libre ;
- les 13 montages NFS, sans retransmission ;
- Restic : sauvegarde du 4/11 à 00:38 ;
- 12 conteneurs sains.

Relevé du 14/11 (journal, `dmesg`, systemd) :

- aucune unité en échec, système ni utilisateur ; 0 OOM en 7 jours ; un seul coredump
  (`gnome-keyring-daemon`) ;
- rasdaemon : aucune erreur mémoire ni PCIe. Ses avertissements portent sur les événements CXL,
  absents de ce matériel ;
- démarrage : les « 2 min 43 » de la phase noyau dans `systemd-analyze` sont un artefact (le noyau
  date son premier message à 160 s : compteur non remis à zéro au redémarrage à chaud ; noyau et
  initramfs prennent environ 6 s). Les 35 s du chargeur viennent de `recordfail` de GRUB : menu de
  30 s après les redémarrages anormaux du 13/11, au lieu des 10 s habituelles ;
- bruit sans conséquence : `Page flip failed` de gnome-shell (pilote NVIDIA sous Wayland), SGX
  coupé par le BIOS.

## TrueNAS

[`truenas-stabilize.yml`](../playbooks/truenas-stabilize.yml) et
[`truenas-nfs-shares.yml`](../playbooks/truenas-nfs-shares.yml) décrivent les correctifs. Plans du
6 novembre 2026, **appliqués le 10 novembre** avec l'accord de l'opérateur (stabilisation
`changed=5`, NFS : 13 partages resserrés, 10 partages `dpool` supprimés). Avant l'apply, seule la
workstation avait une connexion NFS ouverte. Après : les deux plans sont vides, et les 12
automontages de la workstation et Apache (`/media/www`) répondent. Le certificat de l'UI (#2) était
déjà le bon, et il n'y avait aucun coredump à réinitialiser (#6).

| # | Problème et preuve | Plan |
| --- | --- | --- |
| 1 | OOM global le 4/11 entre 05:59 et 06:14 : qemu (Talos) et Chrome de karakeep tués. Pas de swap, 3 Go libres sur 61. `taloswk01` et `taloswk02` sont `STOPPED` mais en autostart. | Autostart à `false` pour les deux workers (VM 5 et 7). `taloscp01` reste tel quel. |
| 2 | Certificat de l'UI renouvelé le 4/11 (jusqu'au 1/2/2027), mais `:7000` sert l'ancien, qui expire le 3/12/2026. | `system.general.ui_restart`, seulement si le certificat servi diffère |
| 3 | NFS : `home`, `jenkins-slave` et `backup/lab` ouverts à `*` ; anciens réseaux sur six partages ; dix partages sur `dpool`, qui n'existe plus. Seul `172.17.0.57` monte des partages. | `networks: [172.17.0.0/24]` et `hosts: []` sur 13 partages ; suppression des 10 partages `dpool` |
| 4 | Le scan ClamAV mensuel est tué : `clamscan` charge une seconde base à côté de `clamd` (952 MiB), au-delà de la limite de 2 Gio. | Cron `clamav-scan` en `clamdscan --multiscan --fdpass` |
| 5 | Aucun test SMART planifié (`smart.test` n'existe plus en 26.0). sda et sdd ont 78 018 h et tournent à 47–48 °C. | Quatre crons `smart-long-sd*`, à 02:00 les 7, 14, 21 et 28 ; budgéter deux disques |
| 6 | Le domaine de recherche contient une coquille (`albanandrieu.com`). 4 `systemd-coredump` en échec. | Domaines `[albandrieu.com]` ; `reset-failed` |
| 7 | Tâche de snapshot 11 sur `dpool/workspace`, désactivée. | Suppression |

À lancer depuis la workstation (le contrôle des permissions de Claude a refusé ces écritures) :

```bash
mise run truenas-stabilize-check
.venv/bin/ansible-playbook -i truenas, playbooks/truenas-stabilize.yml \
  -e truenas_stabilize_apply=true -e truenas_stabilize_apply_approved=true
mise run truenas-nfs-check
.venv/bin/ansible-playbook -i truenas, playbooks/truenas-nfs-shares.yml \
  -e truenas_nfs_apply=true -e truenas_nfs_apply_approved=true
```

Reste hors de ces playbooks :

| Problème | Correctif | Où |
| --- | --- | --- |
| L'app `homarr` est `CRASHED` : `homarr-sync` sort en code 2 (`HOMARR_API_KEY is required`). | Fournir la clé, ou sortir en code 0 avec un avertissement | nabla-compose `apps/homarr/` |
| `PiHoleAdsBlockedTooLow` toujours active : `rate()` sur une jauge journalière ; `PiHoleQueryCountHigh` a le même défaut. | `pihole_ads_percentage_today < 1`, `for: 1h` | nabla-compose `apps/prometheus/rules/pihole.rules.yml` |
| Profil de mise à jour `EARLY_ADOPTER` (26.0.0-BETA.2), qui propose la RC 27. | `GENERAL` n'est pas proposé sur ce train (`available: false`). Garder la vérification automatique coupée et ne pas prendre la RC. | UI |
| Le cron `clamav-cleanup` cherche `clamav-scan-*-.log` : ce motif ne correspond à aucun journal. | `clamav-scan-*.log` (supprime ceux de plus de 90 jours). Déclaré dans `truenas-stabilize.yml` le 11/11 : le plan ne contient que cette mise à jour (cron 5), **apply à faire** | `truenas-stabilize.yml` |

Suspecté :

- Pi-hole ne voit presque pas le trafic : 562 requêtes en 14 h, aucun blocage. Voir le résolveur de pfSense.
- Juste avant l'OOM, dockerd renvoyait `broken pipe` sur son socket.

Déjà suivi dans nabla-compose :

- PSI `io full` à 14 % le 4/11, ~50 % le 11/11 vers 00:10 (charge 19) : `cpool` encaisse ~670
  écritures/s à 61 ms pour 14 Mo/s, et les imports Python de FastAPI Sample ont dépassé 4 min le
  10/11 à 17:06 UTC, d'où l'échec de sa mise à jour par le cron. Le 11/11 à 11:45 UTC, après l'arrêt
  des boucles de `pihole-dns-sync` et de Pyroscope : ~30 %, charge 5,8, ~300 écritures/s à 55 ms ;
- 12 360 snapshots ;
- 679 volumes Docker orphelins ;
- 5 cibles Prometheus DOWN et Alertmanager sans récepteur ;
- pas de réplication hors site.

Vérifié sain :

- pools sains, scrubs à 0 erreur, cpool à 53 % ;
- SMART PASSED ;
- tâches de snapshot et cloud sync en succès ;
- 150 conteneurs sur 177 démarrés, aucun unhealthy ;
- chrony synchronisé ;
- `app.query` répond en 0,7 s.
