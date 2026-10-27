# Workstation Ubuntu — plan P0 de validation de l'exposition réseau

**Statut : collecteurs de mesure ajoutés — aucune sonde TCP LAN/WAN effectivement exécutée.** Aucun changement de règle réseau n'est appliqué. Le protocole opérateur se trouve dans [le runbook de mesure](workstation-network-measurement.md).
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

Les collecteurs des étapes 2 (Docker, facultatif) et 4–5 (TCP allowlist
depuis observateurs indépendants) sont désormais **codés, mais pas exécutés
en runtime**. Le protocole d'exécution est documenté
[dans le runbook de mesure](workstation-network-measurement.md).
Le fichier des cibles demeure privé, hors Git, avec permissions `0600`.
Les tests TCP ne démontrent ni UDP, ni TLS/applicatif, ni le chemin
réel derrière un proxy. La collecte Docker exige une autorisation
spécifique à cause des privilèges équivalents à root du daemon.

Les étapes 2 à 6 **ne sont pas exécutées** par cette PR. Ne pas créer de
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
