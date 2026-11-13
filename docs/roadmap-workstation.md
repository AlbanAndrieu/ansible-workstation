# Roadmap ansible-workstation — Ubuntu secure-by-default

**Périmètre :** seulement `ansible-workstation`. Contrat : [Option A](workstation-ownership-option-a.md). La vue homelab/YubiKey reste dans [nabla-compose](https://github.com/AlbanAndrieu/nabla-compose/blob/master/docs/roadmap-workstation-yubikey.md) ; shell utilisateur dans [dotfiles](https://github.com/AlbanAndrieu/dotfiles/blob/main/docs/roadmap-workstation.md).

**Consolidée le 10 novembre 2026** (rebase de la PR #20 sur `master` après la PR #18).
Statuts : **ACCEPTED** = preuve runtime opérateur ; **APPLIQUÉ** = exécuté sur la station ;
**CODE ADDED** = code et contrats offline, runtime non vérifié ; **À faire**.

## P0 — sécurité et exposition

| Livrable | Gate de validation | Statut |
| --- | --- | --- |
| Retirer le bundle YubiKey/PAM historique du rôle global | Aucune importation `yubikey.yml`, aucune mutation PAM, aucune action matériel | **ACCEPTED** : ancien PPA + templates PAM retirés ; dépendances OS restaurées en opt-in |
| [Prérequis OS YubiKey Ubuntu autonomes](yubikey-os-prerequisites.md) | Audit sans sudo/PAM/PPA ; installation doublement autorisée | **ACCEPTED (audit seul)** : 131/131 PASS, `ok=8 changed=0`, 7/7 paquets présents ; aucun apply |
| [`playbooks/audit-workstation.yml`](../playbooks/audit-workstation.yml), distinct de `workstation.yml` | Tests Python + `mise run audit-syntax` + `changed=0` | **ACCEPTED** : 60/60, `ok=14 changed=0` ; sondes passées par un exécuteur unique fail-closed ; [preuves](audit-workstation.md) |
| [Visibilité Docker/nftables/iptables sans privilèges, lecture privilégiée optionnelle](audit-workstation-network.md) | Lecture locale, `sudo -n` fixe, aucune donnée brute | **ACCEPTED** : 68/68 et 77/77 tests ; sauts DOCKER-USER observés le 11/11 (`audit-network-privileged`, `sudo -n` fixe) : saut présent dans `FORWARD` en IPv4 et IPv6, aucun verdict direct dans `DOCKER-USER`, le filtrage passe par `ufw-user-forward` (mesuré depuis TrueNAS le 10/11) |
| [Sockets TCP/UDP par portée d'écoute, IPv6 zoné](audit-workstation-network.md) | Rapport agrégé sans ports ni adresses | **ACCEPTED** : 95/95 tests, `unknown=0` |
| [ufw par allowlist, NFS serveur retiré, Zabbix vers TrueNAS](workstation-network-hardening.md) | Double approbation, `ufw status verbose` | **APPLIQUÉ** : ufw actif au boot (3/11), INPUT/FORWARD en DROP ; relevé du 10/11 : 18 règles, aucune ouverte à tous, synergy/deskflow limités au LAN ; `--check` avec les drapeaux d'apply : `changed=0` |
| Ports Docker publiés (DNAT avant ufw) | Mesure depuis TrueNAS de chaque port publié | **APPLIQUÉ le 10/11** : le bloc ufw-docker laissait passer toute source privée, LAN compris (Grafana 3009 répondait à TrueNAS). `harden_docker_routes` : 4 règles `FWD`, l'ACCEPT de TrueNAS sur 4000 avant les DROP du LAN, `--check` ensuite `changed=0`. Depuis TrueNAS : 3009 fermé, 4000 ouvert (`/health/liveliness` 200) ; en local, Grafana et LiteLLM répondent toujours. Pas mesuré : le DROP sur 4000 depuis une autre machine du LAN (aucun observateur) ; postgres/redis restent sur `127.0.0.1` ; WAN `not_verified` |
| [Mesures TCP par allowlist privée local/LAN/WAN](workstation-network-measurement.md) | Cibles préautorisées, observateurs séparés | **LOCAL ACCEPTED** 2/2 ; LAN depuis TrueNAS le 10/11, après les routes Docker : 4000, 11434, 9100, 8082 et 10050 ouverts comme prévu, 3009 et 8126 fermés ; WAN différé (aucun observateur externe) |
| Corriger le périmètre Ubuntu 26.04 du playbook historique | Plus de faux « unsupported » ; aucun apply global | **ACCEPTED (10/11)** : plancher de version au lieu de la liste qui s'arrêtait à 25 ; la seule porte (tag `platform`) rend « Ubuntu 26.04 x86_64 » ; test de contrat |

## P1 — configuration, sauvegarde, stabilité

| Livrable | Gate de validation | Statut |
| --- | --- | --- |
| [Stockage : sortir les écritures du SSD SATA usé, récupérer 382 Go de NVMe](#9-novembre-2026--stockage) | Archive vérifiée avant effacement, mesure avant/après | **ÉTAPES 0 À 5 FAITES** : `/home` sur le NVMe le 13/11, `sda` écrit 74 % de moins ; 4 bis (zram) acceptée le 11/11 ; restent les étapes 6 et 7 et les [propositions D1 à D12 du 13/11](#13-novembre-2026--après-la-bascule-de-home) |
| [Stabilisation workstation/TrueNAS](stabilisation-workstation-truenas.md) : automontages NFS, métriques GPU, Apache durci, journald 2G | `--check`, double approbation | **APPLIQUÉ** : `--check` avec les drapeaux d'apply le 10/11, `ok=31 changed=0` ; partages NFS actifs limités aux 12 de `fstab` ; adresse de sonde Apache rendue au déploiement ; `restic-backup.yml` ne retire plus les collecteurs de node_exporter. Crontab root ClamTk (scan en `nice`/`ionice`, lignes maldet et chkrootkit en double retirées) codée le 10/11, **apply à faire** : `--check` ne change que ces 2 tâches |
| Partages NFS TrueNAS et hôte Zabbix en code ([`truenas-nfs-shares.yml`](../playbooks/truenas-nfs-shares.yml), [`zabbix-workstation-host.yml`](../playbooks/zabbix-workstation-host.yml), [`truenas-stabilize.yml`](../playbooks/truenas-stabilize.yml)) | Plan seul par défaut (`mise run truenas-nfs-check`, `zabbix-host-check`) | **APPLIQUÉ le 10/11** avec l'accord de l'opérateur, plans vides ensuite. NFS : 13 partages resserrés sur le LAN, 10 partages `dpool` supprimés ; seule la workstation était connectée, ses 12 automontages répondent. Stabilisation : 5 crons (clamdscan, 4 tests SMART longs), domaine de recherche corrigé, tâche de snapshot 11 supprimée, autostart coupé sur les VM 5 et 7. `zabbix-host-check` pas lancé (jeton API) |
| [Restic](restic-evaluation.md) : sauvegarde quotidienne chiffrée vers TrueNAS | `restic check` + restauration isolée + copie indépendante | **APPLIQUÉ** : timer quotidien, dernière sauvegarde réussie le 10/11 à 00:39, `restic check` hebdomadaire réussi le 9/11 ; alerte Zabbix à 26 h, dernière réussite exposée à Prometheus via node_exporter. Restauration isolée : `restic-restore-test.service` codée le 10/11 (restaure `/etc/restic` dans un `/tmp` privé puis `diff -r`), **à installer et lancer** ; copie hors site : fournisseur et budget à décider |
| [Capture /etc et paquets, restauration](workstation-configuration-capture.md#capture-du-contenu-31-octobre-2026) | Secrets et adresses internes expurgés (`@@SECRET@@`, `@@INTERNAL@@`), point fixe testé | **POINT FIXE VÉRIFIÉ (10/11)**, restauration jamais appliquée. `restore-etc-check` signalait 80 fichiers à cause du mode `0664` du checkout : les modes sont maintenant fixés (`0644`, `0640` pour `ufw/after.rules`). Reste 9 écarts, tous expliqués : 3 commentaires expurgés, 3 drop-ins qui remplacent des lignes modifiées dans les fichiers d'origine, `after.rules` illisible sans sudo, propriétaire de `snmp_exporter.service`, et le `PATH` de `ollama.service`, qu'`install.sh` réécrit avec celui du shell mais que le drop-in remplace (PATH effectif `/usr/local/bin:/usr/bin:/bin`, vérifié le 11/11) : aucun écart à corriger |
| [Comparer état observé et `policies/home-desktop.yml`](workstation-configuration-capture.md#politique-déclarée-et-dérive) | Dérive classée, sans secrets | **ACCEPTED (10/11)** : `conforms_to_declared_policy` (4 baseline, 9 required, 29 à revoir) après la mise à jour de la politique : ufw actif, gateway OpenClaw arrêtée depuis la bascule du 3/11 |
| Nettoyer `tasks/security.yml` et unattended-upgrades | Pas de `dpkg-reconfigure` ni écrasement de conffile | **CODE ADDED** : drop-in `52unattended-upgrades-workstation`, tâches apt modernes ; absent de la station le 10/11 (unattended-upgrades actif avec la configuration du paquet). **SIMULATION OK le 10/11**, aucun apply : [`playbooks/workstation.yml`](../playbooks/workstation.yml) chargeait un rôle vide (`role: ../` se résolvait en `playbooks/`) ; il charge maintenant le dépôt (322 tâches). `--tags unattended-upgrades --check --diff` : `ok=3 changed=1`, seul le drop-in serait créé. `20auto-upgrades` passe sous le tag `apt-periodic` : il remplacerait la cadence hebdomadaire réglée sur la station (`Update-Package-Lists "7"`) par une cadence quotidienne, à décider |
| [devsec os_hardening + ssh_hardening adaptés au poste](workstation-network-hardening.md#durcissement-os--devsechardeningos_hardening) | Simulation, revue du diff, double approbation | **APPLIQUÉ le 10/11 à 22:18** (`ok=130 changed=38`). Avant l'apply, la relecture du diff avait corrigé deux pièges : `squashfs`/`vfat` restent chargeables (snaps, `/boot/efi`) et les dossiers personnels ne passent plus en `0700`. Vérifié ensuite : snaps, services, conteneurs et sysctl intacts. Deux suites : sshd démarré à tort par le handler du rôle (corrigé dans le code ; arrêté par l'opérateur, `inactive` et `disabled` le 11/11) ; `UMASK 027` gênera Apache sur les nouveaux fichiers ([détails](workstation-network-hardening.md#durcissement-os--devsechardeningos_hardening)) |
| [Howdy et motion : une caméra chacun](howdy-cameras.md) | Audit sans sudo ; PAM jamais modifié | **ACCEPTED (audit seul, 10/11)** : Howdy sur `/dev/video0`, motion sur `/dev/video2`, pas de conflit ; chemins `/dev/videoN` instables, `/dev/v4l/by-id` à préférer ; Howdy retiré du rôle global ; ACL motion restaurée ; activation PAM laissée à nabla-yubikey |
| [Nettoyage BleachBit](workstation-cleanup.md) | Caches régénérables uniquement, `check` par défaut | **APPLIQUÉ le 10/11** (`cleanup-apply`, sans sudo) : 6,8 Go et 116 000 fichiers supprimés, 2 erreurs ; `/` à 75 % ; nettoyeur `workstation_dev.xml` installé. Caches pip, npm, yarn, Code, Cursor et des composants Chrome vides. Restent : Chrome, ignoré tant qu'il tourne (cache 2 Go, modèle IA embarqué 4,5 Go, retéléchargé tant que la fonction est active) ; `~/.cache/pre-commit` 15 Go et `~/.cache/uv` 3,3 Go après `gc`/`prune` ; Docker ne retire que le pendant (43 Go d'images et 21 Go de cache de build inutilisés). `apply-system` (sudo) pas lancé ; journald aligné sur `SystemMaxUse=2G` |
| [Réparation de la toolchain utilisateur](user-toolchain-recovery.md) | `check` par défaut, OpenClaw épinglé | **ACCEPTED (10/11)** : `toolchain-check` sans problème ; une gateway désactivée n'est plus une erreur, et `toolchain-repair` ne la redémarre plus (deux gateways interrogeraient les mêmes comptes Telegram et WhatsApp) |
| [OpenClaw : audit de la source Workstation, cible TrueNAS](openclaw-workstation-to-truenas.md) | Contrats offline, aucune mutation | **BASCULE FAITE le 3/11** par `nabla-openclaw` : gateway de la station arrêtée et désactivée, gardée pour le retour arrière. Reste de la bascule retiré le 10/11 : la ligne `tech-news-digest` de 9 h de la crontab utilisateur, qui écrivait `/tmp/td-merged.json` sans rien envoyer (la livraison passe par la gateway TrueNAS) |
| [Extraire le code Workstation de nabla-compose](migration-from-nabla-compose-20261030.md) | Équivalence des sondes, secrets hors dépôt | **LOT 1 BASCULÉ (11/11)** : les 6 diagnostics DNS/Wi-Fi ont le même AST que les originaux de nabla-compose (inchangés depuis `cc3f9ca6`), aux virgules finales près. Seuls trois écarts cosmétiques : `mise run` au lieu de `just`, une lambda en `def`, deux variables extraites. Originaux retirés côté nabla-compose par la [PR #346](https://github.com/AlbanAndrieu/nabla-compose/pull/346), fusionnée le 11/11 (`30d1958b`) : seules restent les tâches `mise run workstation-*` d'ici ([détails](migration-from-nabla-compose-20261030.md#lot-1-copié-2026-11-02--diagnostics-dns-et-wi-fi-du-poste)) |
| [Transférer l'inventaire JSON v1 de dotfiles ici](audit-workstation.md#inventaire-système-json-v1) | Collecteur unique, date/source par champ | **CODE ADDED (10/11)** : `mise run audit-inventory`, sans sudo ; sur la station, même JSON v1 que dotfiles, plus `provenance` (source et date UTC de chaque champ, vérifiées par test de contrat). **Wrapper dotfiles en PR (11/11)** : `bin/inspect-workstation-system.py` lance ce collecteur, sorties identiques (JSON plus `provenance`, résumé) ; commité (`5f5d47d`), [dotfiles#5](https://github.com/AlbanAndrieu/dotfiles/pull/5) à relire puis fusionner |
| Profil minimal des paquets/services opt-in ; retirer les vieilles distributions | `--check` non destructif, idempotence, rollback | **VIEILLES DISTRIBUTIONS RETIRÉES (10/11)**, code seul : 52 tâches réservées à Ubuntu 12.04–19.10 supprimées (PPA morts, Unity, Wine 17.04…), 84 clauses toujours vraies sur 20.04+ retirées, `gui.yml`, `keepass.yml` et `record.yml` vidés puis supprimés ; plancher du `workstation.yml` racine relevé à 20.04 (tag `platform` : « Ubuntu 26.04 x86_64 », `changed=0`) ; test de contrat : plus aucun `ansible_distribution_version` dans `tasks/`. Rien ne change sur une 20.04+ : les tâches supprimées y étaient toujours sautées. Retour arrière : `git revert`. Profil minimal opt-in : périmètre à décider, après le commit de ce lot ([question 11](workstation-pending-actions.md#2-décisions)) ; idempotence d'un run complet non mesurée (pas d'apply global) |

## P2

| Livrable | Gate de validation | Statut |
| --- | --- | --- |
| Auditer Secure Boot / TPM / module NVIDIA ([`audit-boot-integrity.py`](../scripts/audit-boot-integrity.py)) | Diagnostic seulement | **ACCEPTED (11/11)** : `mise run audit-boot`, sans sudo, 5 tests de contrat. Secure Boot coupé, TPM 2.0 présent ; module NVIDIA 595.71.05 signé par la clé DKMS, mais clé non enrôlée (noyau marqué `E`) : activer Secure Boot couperait le GPU. Enrôlement : [runbook](workstation-pending-actions.md#secure-boot--enrôler-la-clé-dkms-avant-de-lactiver). Liaison TPM des volumes LUKS non examinée (root) |
| Transférer les contrats matériels vers `nabla-yubikey` | Tests hermétiques, aucun secret/PAM | **FAIT (1/11)** : 125 fichiers et 87 recettes `yubikey-*` copiés de nabla-compose, numéros de série retirés, 577 tests ; cutover nabla-compose PR #317 fusionné (copies retirées). Non prouvé : les recettes qui demandent la clé principale, l'USB d'escrow ou une écriture matérielle (suivi dans nabla-yubikey) |
| Découpler les scripts OpenClaw/TrueNAS | API de sonde entre `nabla-openclaw` et `nabla-compose` | Gateway dans `nabla-openclaw`, épinglée en sous-module `apps/openclaw` ; 59 scripts du poste et 3 de TrueNAS restent dans nabla-compose : retrait ou portage à décider ([question 12](workstation-pending-actions.md#2-décisions)) |
| Pipeline audit → plan → apply + rétablissement éprouvé | Rollback local testé | **CODE ADDED (11/11)** : plan et double approbation sur chaque playbook ; retour arrière par `restore-etc.yml` limité à `etc_restore_only` (copie datée, ni unités ni motion), vérification d'un seul fichier `changed=0`, chemin non restaurable refusé. Test réel (journald dérèglé puis rétabli) : [runbook](workstation-pending-actions.md#retour-arrière-ciblé-p2-pipeline-audit--plan--apply) |

## Règles

- **Les faits ne sont pas des sauvegardes.** Snapshots machine hors Git ; Restic assure la
  conservation chiffrée ; garder une copie indépendante de TrueNAS.
- **Pas de CI payante ni de fusion automatique.** Tests de contrat en local (`mise run test-offline`),
  PR revues par l'opérateur.
- **Suivant :** les commandes sudo et les décisions du [runbook des actions en
  attente](workstation-pending-actions.md) ; boot à froid (étape 3) et bascule de `/home` (étape 4)
  du stockage, devant la machine.

## 30 octobre 2026 — skills Ansible et acceptation DNS

- **Skills** : recette `mise run agent-skills-check` et alias
  `just agent-skills-check`, script de politique et tests hermétiques.
  Vérifie source déclarée, schéma et `computedHash` (format seulement),
  source canonique, liens Claude/Hermes et priorité des règles Ubuntu.
  **ACCEPTED on operator checkout (earlier HEAD): 11/11 PASS**,
  `installation=installed`, `status=pass` pour les deux skills.
  Les fichiers vendor et `skills-lock.json` sont désormais commités
  sur la PR #17 ; les six liens symboliques sont versionnés. Le
  contrôle `missing_manifest` fail-closed et la dernière extension
  de l'audit systemd **doivent encore être rejoués sur le HEAD courant**.
- **Pre-commit** : les hooks de formatage/lint n'altèrent plus
  `.agents/skills/`; les contrôles de secrets restent actifs, avec
  une exception `detect-private-key` pour le scanner de signatures
  `ansible-validator/scripts/scan_secrets.sh`. Ne pas exclure la
  totalité du répertoire des scanners.
- **DNS** : preuve opérateur du 30 octobre : `resolvectl dns eno1`
  affiche `172.17.0.1`, `resolvectl domain eno1` affiche
  `~int.albandrieu.com`; `dig @172.17.0.1` et `getent ahostsv4`
  résolvent `sample.int.albandrieu.com` vers `172.17.0.24`.
  Cela ne valide pas le DNS hors LAN ni la protection effective DNSSEC.
- **OpenClaw** : Gateway `systemd --user` actif/activé et CLI Node
  24/OpenClaw 2026.10.7 observées ; `ExecStart`, HTTP readiness et
  accès aux modèles restent **NOT VERIFIED**. L'avertissement Ansible
  Python Homebrew 3.14 est corrigé dans le code du playbook via
  `ansible_python_interpreter` mais pas encore revalidé sur la station.
- **Suite** : valider les tests des skills, inspecter les diffs tiers
  et réaliser une comparaison expurgée des `ExecStart` effectifs
  avant toute promotion de template ou bascule du Gateway.

## 9 novembre 2026 — stockage

Relevé du 8 novembre (SMART, `/sys/block/*/stat`, `pidstat -d`) :

| Disque | Contenu | État |
| --- | --- | --- |
| Samsung 860 500 Go (SATA, LUKS) | `/`, `/home` (142 Go), `/swapfile` 16 Go | **66 % d'usure** (`Wear_Leveling_Count` 34), 117 To écrits, 35 700 h ; encore 48 Gio écrits par jour, surtout les profils Chrome, Claude Desktop et ChatGPT de `/home` |
| Samsung 970 PRO 1 To (NVMe) | `/docker`, `/workspace` ; `p2` et `p5` en LUKS2 dans `vg-nvme-crypt` (modèles ollama, `/home` à venir) depuis le 11/11 ; 98 Gio non partitionnés entre `p3` et `p4` | 0 % d'usure, 5,9 To écrits |
| 2 × Seagate 2 To (RAID1 LVM) | `/data` 500 Go ; 2,66 To non alloués dans `vg-sata` | `sdc` : 312 646 cycles de têtes (300 000 prévus), 32 000 h ; aucun secteur réalloué ni en attente |

Partitions NVMe inutilisées :

- `nvme0n1p2` (196 Go, ext4) : ancienne installation Ubuntu 21.04 de septembre 2021, 59 Go.
  `workspace/users/albandrieu30` (24 Go, clones de dépôts), `home/albandrieu` (22 Go, dont
  `Pictures` 9,8 Go : 60 fichiers sur 114 absents de l'actuel `~/Pictures`), `var` 7 Go, un
  `swapfile` de 2 Go. Inspectée montée en lecture seule (`ro,noload`), puis démontée.
  Contrôle du 10/11 : les 114 fichiers de `Pictures` (et les 1 400 du zip `Eleonore-001`) sont
  déjà sur TrueNAS (`/media/photo`, `/media/home/albandrieu`) ou dans `/data/photo-TODELETE`
  (sha256, ou nom et taille pour le zip), sauf trois logos publics. Le reste (`home` sans photos,
  `workspace` de 2021) ne vaut pas d'archive, décision de l'utilisateur : `p2` peut être effacée.
- `nvme0n1p5` (187 Go, LUKS2) : un seul emplacement de clé, sans jeton FIDO2, absente de
  `/etc/crypttab`, jamais ouverte dans le journal. Ouverte le 10/11 en lecture seule : un ext4
  créé en septembre 2021, **vide** (28 Ko, seulement `lost+found`). Dernière écriture le
  24/01/2026, 3 Go écrits au total : les sauvegardes qu'elle a portées ont déjà été supprimées.

| Étape | Quoi | Gate | Statut |
| --- | --- | --- | --- |
| 0 | Supprimer les copies Docker d'avant la migration ; `apm = 254` sur les deux disques durs ; écritures en attente plafonnées à 1 Gio, vidage dès 256 Mio | [`stabilize-workstation.yml`](../playbooks/stabilize-workstation.yml), tests de contrat | **FAIT le 9/11** : `/` 84 → 74 %, `APM_level 254`, `vm.dirty_bytes` 1 Gio |
| 1 | Effacer `p2` (`wipefs`), rien à archiver | Photos retrouvées ailleurs (fait) | **FAIT le 11/11** : `wipefs -a` et `blkdiscard` sur `p2` et `p5` |
| 1 bis | Comparer `/data/photo-TODELETE` (53 Go sur le RAID1 de disques durs) à `/media/photo` sur TrueNAS, fichier par fichier (`sha256`), puis le supprimer | 0 fichier absent de TrueNAS | Comparé le 10/11 : 18 671 fichiers sur 18 673 identiques (les deux restants : config de l'éditeur `ee`). `Eleonore/Eleonore/IMG-20200210-WA0000.jpg` est corrompu sur TrueNAS (octets aléatoires) ; la bonne version y est deux fois dans `google/Takeout`, recopiée à sa place le 11/11. **SUPPRIMÉ le 10/11** : `/data` 36 → 25 % (166 → 114 Go) |
| 1 ter | Comparer `/data/music-TODELETE` (94 Gio, bibliothèque `iTunes`) à `/media/music` sur TrueNAS (`sha256`), puis le supprimer | 0 fichier absent ou différent sur TrueNAS | Comparé le 11/11 : 26 329 fichiers sur 26 329 identiques ; seul écart, `.windows-serial` (2 octets, absent de TrueNAS). **SUPPRIMÉ le 11/11** par l'utilisateur : `/data` 25 → 5 % (114 → 20 Gio, reste l'ancienne copie des modèles ollama) |
| 2 | Ouvrir `p5` avec sa phrase de passe, inventorier, archiver ce qui compte | Volume vide, rien à archiver | **FAIT le 10/11** : libre pour l'étape 3 |
| 3 | LUKS2 sur `p2` et `p5`, déverrouillés au boot (clé sur la racine chiffrée, ou YubiKey FIDO2), PV dans un VG `vg-nvme-crypt` : LV `home` 250 Go, LV `models` 40 Go, reste libre | `cryptsetup luksDump`, boot à froid sans intervention | **FAIT le 11/11** : clé `/etc/cryptsetup-keys.d/nvme_crypt.key`, copie et en-têtes LUKS sur la clé USB d'escrow (`luks-escrow/`) ; `/etc/crypttab` en `nofail`, ouverture par `systemd-cryptsetup@` vérifiée ; 92 Go libres dans le VG. Reste à voir un boot à froid ([runbook](runbook-storage-nvme.md)) |
| 4 | Migrer `/home` sur le NVMe : passe finale `rsync -aHAXS` sans session ouverte, `fstab`, ancienne `/home` gardée une semaine | Session graphique normale, 0 Gio/jour de profils sur `sda` (`pidstat -d`) | **FAIT le 13/11** : bascule au boot de 10:33 par l'unité ponctuelle `home-nvme-switch.service` (passe finale 5 min 14 s) ; `/home` sur `vg--nvme--crypt-home`, 160,6 Go, aucune unité en échec ; `sda` de 11:00 à 16:00 : écritures 5,3 → 1,4 Gio, lectures 29,7 → 0,1 Gio ([relevé](#13-novembre-2026--après-la-bascule-de-home)). Montage codifié dans `stabilize_nvme_mounts`, unité retirée du dépôt et du système. Reste : supprimer `/home.sda-old` le 20/11 ([runbook](runbook-storage-nvme.md), § 1) |
| 5 | `OLLAMA_MODELS` sur le LV `models` (drop-in ollama) | Chargement à froid mesuré avant/après (`qwen3.5:4b`, 12 à 17 s aujourd'hui) | **FAIT le 11/11** : LV monté sur `/data/models/ollama` (chemin inchangé), `RequiresMountsFor` dans le drop-in ; **17 s → 5,7 s**. Ancienne copie dans `/data/models/ollama.hdd-20261111`, à supprimer après une semaine |
| 6 | Alertes : `Wear_Leveling_Count` de `sda` sous 20, secteurs réalloués ou en attente sur `sdb`/`sdc` (métriques `smartmon_` déjà exportées, job `workstation_node`) ; prévoir le remplacement de `sdc` (`lvconvert --repair`) | Alerte de test reçue | **EN PR le 13/11** : 3 règles dans `nabla-compose` ([PR #371](https://github.com/AlbanAndrieu/nabla-compose/pull/371)), promtool valide, expressions vérifiées sur le Prometheus de TrueNAS (`sda` à 33, 0 secteur défaillant, NVMe à 0). Reste : recharger Prometheus après la fusion, alerte de test ([runbook](runbook-storage-nvme.md) § 2) |
| 7 | À terme : déplacer `/` et `/boot` du SSD 860 vers le NVMe, ou le remplacer | Après les étapes 4 et 6 | Plus tard |

Après l'étape 4, `sda` ne porte plus que le système (environ 180 Go, 40 %) : moins plein, il s'use
moins par écriture. Pas retenu : `noatime` (gain négligeable face à `relatime`).

Relevé du 10 novembre (6,7 jours sans redémarrage) : l'étape 0 tient (`vm.dirty_bytes` 1 Gio,
`APM_level` 254 sur `sdb` et `sdc`), mais rien n'a encore réduit les écritures sur `sda` :
48 Gio/jour, `Wear_Leveling_Count` normalisé 34 → 33. La swap écrit maintenant : 6,3 Gio occupés
sur `/swapfile`, 23,6 Gio écrits depuis le démarrage (environ 3,5 Gio/jour sur `sda`). `sdc` est passé
de 312 646 à 312 856 cycles de têtes depuis le 8/11 ; toujours 312 856 le 11/11 : `APM_level` 254
a arrêté le parcage des têtes.

Vitesses de lecture séquentielle mesurées le 10/11 (`hdparm -t --direct`) : NVMe 1 956 Mo/s (une
seule file d'attente, lien PCIe 3.0 x4 complet), SSD 860 451 Mo/s, disques durs 214 et 219 Mo/s,
clé USB 36 Mo/s.

| Étape | Quoi | Gate | Statut |
| --- | --- | --- | --- |
| 4 bis | Swap hors de `sda` : zram (`zram-tools`, `PERCENT=25`, priorité 100) devant le `/swapfile`, gardé en secours à priorité basse | Utilisation de `/swapfile` stable sur 24 h (`/proc/swaps`), aucun OOM | **APPLIQUÉ le 10/11** ([`stabilize-workstation.yml`](../playbooks/stabilize-workstation.yml)) : `/dev/zram0` zstd 15,7 Gio, priorité 100 ; reste la mesure sur 24 h (`/swapfile` : 6,3 Gio utilisés au départ, ne doit pas monter ; 5,6 Gio le soir du 10/11, zram 10 Gio). 11/11 : zram plein (15,6 Gio, compressés 3:1, surtout les pages inactives de Claude Desktop, Chrome et des terminaux), `/swapfile` 5,7 Gio : la gate tient. zram passé à `PERCENT=50` (31,4 Gio). **ACCEPTED le 11/11 à 12:45** : `/swapfile` 5,7 Gio (6,3 au départ, n'a pas monté), zram 6 Gio utilisés sur 31,4 (compression 3,3:1), aucun OOM dans le journal noyau depuis le 10/11 |

## 13 novembre 2026 — après la bascule de `/home`

Relevé de 16:00 à 16:15, poste démarré à 10:50.

**Bascule.** Au boot de 10:33, `home-nvme-switch.service` a tourné de 10:33:24 à 10:38:38, avant
GDM. `findmnt /home` : `/dev/mapper/vg--nvme--crypt-home`, ext4 ; `/etc/fstab` porte la ligne
`/home` (`nofail,x-systemd.device-timeout=30s`) ; `lvs` : LV `home` de 250 Gio sur tout
`nvme2_crypt` et le début de `nvme5_crypt`. L'ancien emplacement, `/home.sda-old` sur `/`, n'est
ouvert par aucun processus (`lsof`). Boot de 10:50 : `systemctl --failed` vide,
`journalctl -b -p warning` sans erreur de disque, de LVM ni d'ext4 (restent les avertissements
connus : rasdaemon `cxl`, générateur SysV, `nf_conntrack_max`) ; 17,7 s d'espace utilisateur,
`systemd-cryptsetup@nvme5_crypt` 3,6 s et `@nvme2_crypt` 1,9 s.

| Contrôle des données | Ancienne copie (`/home.sda-old`) | LV NVMe (`/home`) |
| --- | --- | --- |
| Taille apparente de `albandrieu` | 160,23 Go | 160,60 Go (écritures depuis 10:38) |
| Entrées (`find -xdev`) | 3 993 156 | 4 000 615 |
| `jenkins` et `nexus` | 495 264 et 15 544 octets | identiques |
| `.bashrc`, `.gitconfig`, `.ssh/config`, `.ssh/known_hosts`, `.gnupg/pubring.kbx` | — | identiques (`cmp`) |
| Fichiers modifiés après 10:33:24 et absents du LV | 47 images `motion` (10:38:06 à 10:38:27) | non recopiées, inutiles d'après l'opérateur |

Effet sur les disques (Prometheus, job `workstation_node`, de 11:00 à 16:00, le 12/11 puis le
13/11) :

| Disque | Écrit | Lu | Temps occupé |
| --- | --- | --- | --- |
| `sda` (SSD 860 usé) | 5,3 → 1,4 Gio | 29,7 → 0,1 Gio | 319 → 36 s |
| `nvme0n1` | 0,9 → 5,2 Gio | 0,0 → 1,5 Gio | 213 → 291 s |

Sur une minute (16:12), `sda` a écrit 7,6 Mio, soit environ 11 Gio/jour contre 48 le 10/11 :
Chrome et Claude Desktop, premiers écrivains (`pidstat -d`), écrivent maintenant sur le NVMe ;
restent surtout journald, Grafana et le journal ext4 de `/`.

État des disques :

- SMART : `sda` `Wear_Leveling_Count` 33 (inchangé depuis le 10/11), 117 To écrits ; NVMe 0 %
  d'usure, 0 erreur média, 42 °C, 746 entrées au journal d'erreurs, toutes
  `Invalid Field in Command` (commandes d'administration des sondes) ; `sdb` et `sdc` : aucun
  secteur réalloué ni en attente, `sdc` à 32 178 h.
- Alignement : toutes les partitions sur 1 Mio. TRIM : `discard` traverse LUKS (`allow_discards`),
  `fstrim.timer` hebdomadaire (683 Gio le 9/11, 1 h 09 à cause des disques durs) ; `/home` et
  `models` seront taillés pour la première fois le 16/11.
- Ordonnanceurs d'E/S : `none` sur le NVMe, `mq-deadline` sur le SSD et les disques durs.
- Swap : zram 31,4 Gio (priorité 100) devant `/swapfile` 16 Gio sur `sda` (priorité -1), 0 octet
  utilisé ; pas d'hibernation (`resume` absent de la ligne de commande du noyau).
- Place libre : 92 Gio dans `vg-nvme-crypt`, 122,5 Gio non partitionnés sur le NVMe (98,1 entre
  `p3` et `p4`, 24,5 en fin de disque), 2,66 Tio dans `vg-sata`, 1 Gio dans `vgubuntu`.
  Remplissage : `/` 77 % (dont les 160 Go de l'ancienne copie), `/docker` 75 %, `/home` 67 %,
  `/workspace` 65 %, `/data` 5 %. Réserve root ext4 de 5 % sur chaque volume.
- Restic : `/etc`, quatre dossiers de `~` (`.ssh`, `.gnupg`, `.config`, `.local/share/keyrings`) et
  trois fichiers Maven, chaque nuit ; dernière sauvegarde le 13/11 à 00:31, avant la bascule. Le
  reste de `~` n'est pas dans Restic.

Propositions, rien n'est appliqué :

| # | Proposition | Mesure | Gain attendu | Risque |
| --- | --- | --- | --- | --- |
| D1 | Verrouiller le point de montage vide de `/home` sur `/` (`chattr +i`, posé à travers un `mount --bind /` temporaire) | `/home` en `nofail` et autologin GDM : si `vg-nvme-crypt` ne s'ouvre pas, la session s'ouvre sur un `/home` vide de `sda` et y recrée des profils | Plus de session sur un `/home` vide : la connexion échoue visiblement | Faible, réversible (`chattr -i`) ; retirer `nofail` serait plus strict mais mène au shell de secours |
| D2 | Supprimer `/home.sda-old` le 20/11, après une sauvegarde Restic réussie ([runbook](runbook-storage-nvme.md), § 1) | 160 Go sur `/`, scannés en double par ClamAV chaque samedi | `/` de 77 % à environ 42 % : plus de cellules libres pour répartir l'usure du SSD ; scan ClamAV raccourci | Plus de retour arrière vers l'ancienne copie |
| D3 | Supprimer `/data/models/ollama.hdd-20261111` le 18/11 | 20 Gio sur le RAID1 de disques durs | `/data` de 5 à 1 % | Nul : modèles retéléchargeables |
| D4 | Remplacer `/swapfile` par un LV swap chiffré de 8 Gio dans `vg-nvme-crypt`, priorité basse derrière zram | 16 Gio sur `sda`, 0 octet utilisé ; 5,7 Gio utilisés le 11/11, avant zram à `PERCENT=50` | 16 Gio libérés sur `/`, plus aucune écriture de swap sur `sda` | Faible ; supprimer la swap disque sans la remplacer avancerait l'OOM quand zram est plein |
| D5 | Réserve ext4 de 5 à 1 % sur `/home`, `/workspace`, `/docker` et `/data` (`tune2fs -m 1`), 5 % gardés sur `/` | 64,3 Go réservés à root sur ces quatre volumes | +51 Go utilisables (`/home` +10,7, `/workspace` +13, `/docker` +6,3, `/data` +21,4) | Faible, réversible à chaud ; plus de marge pour root sur ces volumes |
| D6 | Purger Docker : images inutilisées et cache de build (`docker image prune -a`, `docker builder prune`) | `/docker` à 75 %, 36 Go libres ; `docker system df` : 79,6 Go d'images et 25,3 Go de cache récupérables | Jusqu'à une centaine de Go libérés (couches partagées : à mesurer après) | Images retéléchargées et premiers builds plus lents |
| D7 | dm-crypt NVMe sans files de travail : `no-read-workqueue,no-write-workqueue` dans `/etc/crypttab` par `stabilize_nvme_crypt` | `nvme2_crypt` et `nvme5_crypt` n'ont que le drapeau `discards` | Latence de lecture aléatoire plus basse sur `/home`, à mesurer (`fio` 4 Kio QD1 avant/après) | Faible, réversible au boot suivant |
| D8 | `/tmp` en tmpfs (`tmp.mount` de systemd, `size=8G`) | `/tmp` sur `/` (`sda`), 31 Mo à 16:00 | Petit, à mesurer : les fichiers temporaires ne touchent plus le SSD usé | Gros fichiers temporaires en RAM ; `/tmp` vidé au reboot |
| D9 | Allouer les 98,1 Gio libres entre `p3` et `p4` : `p6` en LUKS2, PV de `vg-nvme-crypt` | 122,5 Gio non partitionnés | `vg-nvme-crypt` à 190 Gio libres, de quoi accueillir `/` (environ 171 Go après D2) | Moyen : table de partitions du disque en service modifiée ; sauvegarder les en-têtes LUKS avant |
| D10 | Étape 7 : déplacer `vgubuntu-root` sur le NVMe par `pvmove` (PV NVMe chiffré ajouté à `vgubuntu`, initramfs qui l'ouvre), puis `/boot` | `sda` : environ 11 Gio/jour, `Wear_Leveling_Count` 33 | Plus aucune écriture sur le SSD usé ; `/` sur le NVMe (1 956 contre 451 Mo/s en lecture) | Élevé : racine et initramfs ; sauvegarde complète et clé d'escrow avant ; après D2 et D9 |
| D11 | Étape 6 : poser les alertes SMART dans `nabla-compose` ([runbook](runbook-storage-nvme.md), § 2) | `sda` à 33, `sdc` à 32 178 h ; aucune alerte en place | Remplacement anticipé au lieu de subi | Nul |
| D12 | Restic : vérifier le 14/11 la première sauvegarde après la bascule (`restic snapshots --latest 1`), puis décider d'y ajouter `~/Documents`, `~/Backups` et `~/Dropbox` | 4 dossiers de `~` sauvegardés sur 156 Go | Données personnelles avec au plus 24 h de perte | Dépôt plus gros sur TrueNAS, sauvegarde plus longue |

Décisions de l'opérateur le 13/11 : D1, D2, D6 et D11 acceptées.

- D1 **appliquée le 13/11** : `chattr +i` sur le point de montage vide de `/home` sur `/`, posé à
  travers un `mount --bind /` temporaire, retiré aussitôt. Testé avant sur un dossier de `/data` :
  l'écriture est refusée et le montage par-dessus fonctionne. Le retour arrière du
  [runbook](runbook-storage-nvme.md) § 1 commence désormais par `chattr -i`.
- D2 : à faire le 20/11, comme prévu, après une sauvegarde Restic réussie depuis la bascule.
- D11 : en PR, voir l'étape 6.
- D6 **appliquée le 13/11 à 18:20** : `docker builder prune` (25,3 Go), 20 images de registre
  sans conteneur (linters, Prometheus, Alertmanager, images de base) et 3 anciennes versions sans
  tag supprimées ; `/docker` de 101 à 70 Go utilisés (75 → 51 %, 67 Go libres). Gardées : les
  images construites en local, qu'on ne peut pas retélécharger :
  `nabla/ansible-jenkins-slave-docker:node26-test` et `:resolute-test` (21,4 Go, une autre
  session travaillait sur `:runner-test` à ce moment-là) et les 11 tags `bower-sample` (6,7 Go).

Pas retenu : `noatime` (écarté le 9/11), ordonnanceur `none` sur `sda` (SSD SATA peu chargé
désormais), secteurs LUKS de 4 Kio (réchiffrer 382 Go pour un gain CPU marginal, avec un risque
de perte en cas de coupure).
