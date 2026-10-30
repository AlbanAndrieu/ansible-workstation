# Workstation Ubuntu — plan P0 de validation de l'exposition réseau

**Statut : deux tentatives TCP ciblées depuis l'observateur LAN déclaré ont été refusées ; autres expositions LAN et WAN non vérifiées.** Aucun changement de règle réseau n'est appliqué. Le protocole opérateur se trouve dans [le runbook de mesure](workstation-network-measurement.md).
Décision Option A : [contrat](workstation-ownership-option-a.md). État observé :
[audit réseau](audit-workstation-network.md). Cette page est propriétaire de
la prochaine gate **d'accessibilité réelle**, pas des sauvegardes ni de la
configuration YubiKey.

## Base de preuves (27 octobre 2026)

- Audit hôte : Ubuntu 26.04, noyau AppArmor `enabled` (profils non attestés).
- Forwarding IPv4 et IPv6 activé.
- Consultation privilégiée autorisée : `nft`, `iptables` et `ip6tables`
  répondent `ok` ; politiques de base rapportées `ACCEPT`. Des règles
  de filtrage et des chaînes Docker existent, mais la politique effective
  ne peut pas être déduite des valeurs par défaut.
- Listeners TCP **54** : wildcard **34**, loopback **16**, spécifiques **4**.
- Listeners UDP **135** : wildcard **51**, loopback **5**, spécifiques **79**.
  Les deux familles sont désormais **100 % classées** (`unknown=0`).
- Suite de validation de l'audit listener : **95/95 PASS**, exécution Ansible
  `ok=2 changed=0 failed=0`. Les tests de portée LAN/WAN **n'ont pas eu lieu**.

**Interprétation :** les adresses `wildcard` et non-loopback représentent
des candidats à examiner, pas des ports démontrés accessibles. Les ports
Docker publiés par DNAT peuvent être absents de `ss`. Les règles nftables
et iptables peuvent être des vues recouvrantes : ne pas additionner
aveuglément leurs nombres. Ne pas convertir un `ACCEPT` de politique de
base en « ouvert sur Internet ».

## Découpage des preuves à produire

| Étape | Source et exécution envisagées | Sortie publique autorisée | Condition de fin |
| --- | --- | --- | --- |
| 1. Candidats hôte | Collecteur `ss` existant, utilisateur non-root | Compteurs TCP/UDP, portées anonymisées | **Fait**, 95/95, unknown=0 |
| 2. Publications Docker | Inventaire *local* avec accès spécifique au moteur, après revue des privilèges | Comptage des publications par scope `loopback` / `lan-only` / `all-addresses` / `unknown`, IPv4/IPv6 séparés ; **jamais de nom de conteneur/port/IP** | Aucun socket Docker interrogé avant autorisation et revue du collecteur |
| 3. Règles de filtrage | Parseur agrégé des verdicts et saut `FORWARD` → `DOCKER-USER` déjà codé ; lecture privilégiée **seulement avec autorisation renouvelée** | Verdicts comptés et existence du saut ; aucune règle brute | Contrats PASS et résultat runtime sans divulgation |
| 4. LAN | Probes depuis **une autre machine LAN autorisée**, uniquement sur une allowlist privée de cibles/ports définis par l'opérateur | Comptage `expected_allowed`, `unexpected_open`, `expected_denied`, `inconclusive` ; aucun endpoint | Comparaison avec intention de service, IPv4 et IPv6 séparés |
| 5. WAN | Probes depuis une machine explicitement hors LAN, sur **la même allowlist**, avec accord opérateur | Les mêmes quatre états ; aucune adresse ni identité | Aucune exposition imprévue ; preuves de blocage ou échec documenté |
| 6. Décision | Confronter écoute + publication + règles + observation LAN/WAN | `conformant`, `drift`, `unknown` par classe d'usage, sans détails privés | Décision sur politique OS uniquement si preuves suffisantes |

L'étape 2 (Docker, facultatif) a été **exécutée localement** : 12
conteneurs recensés et 9 segments TCP IPv4 wildcard. La mesure localhost
a confirmé 2/2 attentes. Le contrôle LAN a ensuite mesuré deux ports TCP depuis l'observateur
TrueNAS **déclaré par l'opérateur** : 2 `refused`, 0 `connected`,
0 `inconclusive`. Les autres ports et publications Docker n'ont pas
été mesurés de manière exhaustive depuis le LAN. Le code ne prouve pas
la provenance du script ; aucun test WAN n'a été exécuté.
La suite locale de contrats a passé **116/116** avec `.venv/bin/python`.
Le protocole d'exécution est documenté
[dans le runbook de mesure](workstation-network-measurement.md).
Le fichier des cibles demeure privé, hors Git, avec permissions `0600`.
Les tests TCP ne démontrent ni UDP, ni TLS/applicatif, ni le chemin
réel derrière un proxy. La collecte Docker exige une autorisation
spécifique à cause des privilèges équivalents à root du daemon.

### Attestation limitée du chemin LAN — 28 octobre 2026

Le contrôle ponctuel TrueNAS → workstation sur deux ports connus
(OpenClaw TCP 18789, SSH TCP 22) a donné `{'refused': 2}`.
Cela atteste **seulement** l'échec de ces deux connexions TCP depuis
l'observateur indiqué, sous réserve de la provenance déclarée.
La cause du refus n'est pas caractérisée. Aucun des **9 segments TCP
IPv4 Docker wildcard** recensés n'a encore été vérifié depuis le LAN.

**Décision de sécurité :** conserver `lan_other_targets=not_verified`
et `wan_direct=not_verified`. Les refus ne certifient pas l'effet d'une
politique `DROP`, le routage IPv6, ni l'absence de ports publiés
accessibles. L'étape suivante est une comparaison contrôlée des
publications Docker avec les règles et des attentes réseau privées.

### Ajustement de séquence — pas d'observateur WAN disponible (28 octobre 2026)

L'opérateur ne dispose d'aucun autre ordinateur hors du LAN.
La gate P0 LAN reste exécutable avec un **autre hôte du LAN**,
par exemple TrueNAS, sur une allowlist privée ciblant la workstation.
L'origine indépendante et les ports testés doivent être attestés
seulement si le test a réellement été exécuté.

Le contrôle direct WAN ne constitue donc **pas un prérequis** à la
clôture des tests de connectivité LAN ni à l'étude des règles :
il reste `not_verified` et **différé**. Ne pas demander un VPS ou
un service tiers pour compléter artificiellement une case de rapport.

Un téléphone en données cellulaires, Wi-Fi et VPN désactivés,
peut servir ponctuellement d'observateur externe **HTTP(S)** sur des
URLs explicitement autorisées ; cela n'est pas un test de connexion
TCP vers des ports arbitraires. Les accès Cloudflare Tunnel/Access
valident le chemin via Cloudflare, pas l'exposition directe de l'hôte.
Sans origine externe, poursuivre la revue NAT pfSense, filtrage IPv6,
règles Docker et Cloudflare. **Ne pas déclarer une preuve WAN**.

L'étape 4 dispose d'une **preuve LAN partielle (2 ports refusés)** ;
les étapes 3, 5 et 6 restent non vérifiées en situation réelle, et
l'étape 4 n'est pas complète pour les autres ports ;
le comptage Docker (étape 2) ne prouve ni la publication effective vers
le LAN ni l'exposition WAN. Aucune sonde WAN n'a été exécutée par cette PR. Ne pas créer de
sonde réseau opportuniste vers des IP ou ports devinés, ni déployer une
action permanente sans mandat. Une conclusion `unknown` est valide et
préférable à un faux `secure`.

## Politique souhaitée à définir, pas à appliquer

- **Services personnels locaux** : loopback par défaut ; exposition LAN
  seulement pour les services explicitement nécessaires.
- **Services homelab** : rattacher chaque publication à une justification,
  une interface attendue, une source autorisée et une procédure de reprise.
- **Docker** : préserver NAT, chaînes Docker et connexions établies ;
  `DOCKER-USER` (backend iptables) n'est pas un équivalent universel de
  règles nftables, qui disposent de leurs propres hooks et priorités.
- **IPv6** : traiter séparément les interfaces, forwarding et publications ;
  ne pas considérer une protection IPv4 comme preuve de protection IPv6.
- **Entrants SSH/PAM** : le serveur SSH est actuellement arrêté ; ne pas
  l'activer ni modifier PAM à partir de ce plan.
- **DNS/Cloudflare** : conserver les règles de résolution pfSense/split DNS
  et les restrictions Cloudflare Access ; ne pas changer ingress pour
  faire réussir artificiellement les probes.

### Critères obligatoires avant un futur `apply` Ansible

1. Inventaire privé des cibles/ports et attentes par origine
   (`localhost`, LAN, WAN), stocké **hors Git** ; identifiants/secrets
   exclus des comptes rendus publics.
2. Accès console ou chemin de secours, sauvegarde testée des règles et
   configuration, plan de rollback clair.
3. Contrôle de la connectivité au NAS/homelab, au DNS pfSense et aux
   services Docker essentiels **avant puis après** une éventuelle action.
4. Dry-run/validation indépendante, changement explicitement opt-in,
   jamais à l'ouverture d'un shell ou au démarrage d'Ansible.
5. Passage `secure-by-default` seulement sur preuve de règles et
   de connectivité ; aucun statut vert simplement issu de `changed=0`.

**Ne pas exécuter en guise de correction** : `ufw enable`,
`iptables -P DROP`, `nft flush ruleset`, désactivation de
`ip_forward` ou modification de `/etc/docker/daemon.json`.

## Documentation technique de référence

- [Docker — packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
- [Docker — iptables/DOCKER-USER](https://docs.docker.com/engine/network/firewall-iptables)
- [Docker — nftables hooks/priorities](https://docs.docker.com/engine/network/firewall-nftables)
- [Docker — port publishing](https://docs.docker.com/engine/network/port-publishing/)

La gestion des configurations finales demeure dans **ansible-workstation**.
Les endpoints et diagnostics du homelab appartiennent à
**nabla-compose** ; les configurations utilisateurs au dépôt **dotfiles**.
