# P0 — Visibilité du filtrage réseau (lecture seule)

**Statut : CODE ADDED / RUNTIME NOT VERIFIED** (27 octobre 2026).
Ce contrôle complète l'[audit système P0](audit-workstation.md) et l'architecture [Option A](workstation-ownership-option-a.md). Il n'est **pas** une certification d'exposition réseau et ne crée pas de sauvegarde.

## Situation observée

L'audit précédent a établi :

- `net.ipv4.ip_forward=1` sur la workstation.
- `ufw.service=inactive/disabled` et `nftables.service=stopped/disabled`.
- `ssh.service=stopped/disabled`, Fail2ban actif.
- **AppArmor noyau enabled**, sans preuve sur les profils individuels.
- **3 timers APT/fstrim actifs** via `systemctl show`.

Ces états ne permettent **pas** d'affirmer qu'aucune règle firewall n'est appliquée. Docker crée des règles iptables ou nftables pour les réseaux bridge, les ports publiés et la traduction NAT ; le backend utilisé dépend de Docker et de sa configuration. Voir [documentation Docker](https://docs.docker.com/engine/network/packet-filtering-firewalls/).

## Périmètre du contrôle

Le script `scripts/audit-workstation-network.py` n'utilise que :

- `/proc/sys/net/ipv4/ip_forward` et `/proc/sys/net/ipv6/conf/all/forwarding` : valeurs `enabled`, `disabled`, `unknown`.
- `/usr/sbin/nft -j list ruleset` : si autorisé, *compte* des règles et politiques des chaînes de base filter (input/forward/output).
- `/usr/sbin/iptables-save -t filter` et `/usr/sbin/ip6tables-save -t filter` : si autorisés, politiques des chaînes standard, présence des chaînes Docker et compte de règles.
- Le socket Docker **n'est jamais interrogé**. Aucun `docker ps`, accès réseau, shell ou `sudo`.

Toutes les commandes sont lancées avec des chemins absolus, des arguments constants et un délai maximum. Les erreurs et sorties brutes ne sont jamais imprimées : aucun nom d'interface, adresse IP/MAC, port, DNAT ou règle complète ne sort du collecteur.

Le schéma `workstation-network-filter-audit/v1` contient la visibilité de chaque backend (`ok`, `access_denied`, `missing`, `timed_out`, `error`), les petits résumés filtrés disponibles et **`effective_filtering: not_verified`**. Cette dernière valeur est intentionnelle même lorsque des politiques de chaîne ont été observées. La vérification réelle des politiques et des ports publiés nécessitera un audit privilégié explicite, ciblé, avec compte rendu expurgé.

## Procédure sur la workstation

Depuis la branche de revue du projet :

```bash
cd /workspace/users/albandrieu30/ansible-workstation

python3 -m unittest discover -s tests -p 'test_*contract.py' -v
mise run audit-network-syntax
mise run audit-network
```

Exécution directe sans Ansible, en alternative :

```bash
.venv/bin/python -B scripts/audit-workstation-network.py
```

Ne pas lancer avec `sudo`. Ne pas utiliser `docker` en root ; l'accès au socket Docker équivaut souvent à un privilège hôte élevé. Ne pas coller les règles brutes dans un ticket public. Aucun fichier de sortie n'est créé.

La commande peut afficher `access_denied` pour les deux backends : **ce n'est ni une panne du collecteur ni la preuve d'une absence de filtrage**. Le bon statut reste `not_verified`. Il est interdit de corriger ce résultat par `sudo chmod`, par l'ajout automatique à un groupe Docker ou par une modification UFW/nftables.

## Conditions d'acceptation

1. Les huit contrats `tests/test_workstation_network_audit_contract.py` passent.
2. `mise run audit-network-syntax` valide le playbook limité à localhost sans `become`.
3. `mise run audit-network` retourne `changed=0 failed=0` avec le rapport expurgé.
4. Les politiques effectives restent **non attestées** quand la lecture n'est pas autorisée.
5. Aucun socket Docker, aucune configuration ou règle système n'a été modifié.

## Relevé workstation validé (27 octobre 2026)

La branche de la PR #16 jusqu'au commit `43bed04` a été validée par
l'opérateur : **68/68 contrats PASS**, `mise run audit-network-syntax`
PASS et `mise run audit-network` **`ok=2 changed=0 failed=0`**.
Le rapport `workstation-network-filter-audit/v1` classe les trois
sondes nftables, iptables et ip6tables `access_denied`.
Le forwarding **IPv4 et IPv6** est `enabled`.
L'état du filtrage reste `not_verified` ; ni un pare-feu absent ni une
exposition de service n'est prouvé par cet audit sans privilèges.

## Étape facultative : lecture privilégiée, sans exécuter le collecteur comme root

`scripts/audit-workstation-network-privileged.py` est un **autre programme
Python, exécuté par l'utilisateur normal**. Il réutilise les parseurs qui
retirent les détails sensibles. Seules trois commandes système fixes
(`/usr/sbin/nft -j list ruleset`, `/usr/sbin/iptables-save -t filter` et
`/usr/sbin/ip6tables-save -t filter`) utilisent `/usr/bin/sudo -n --`.
Les arguments sont fixés par le code, sans entrée utilisateur et sans shell.
Le Python dans le checkout Git n'est **jamais élevé**.

**Ne pas activer cette étape si tu ne souhaites pas autoriser une lecture
privilégiée.** La commande ne configure pas sudoers, ne demande pas de mot
de passe et ne s'authentifie pas à Docker. `sudo -n` échoue sans
autorisation déjà active. Pour cette session seulement, l'opérateur peut
facultativement valider l'authentification via `sudo -v` dans son terminal,
puis appeler la tâche. Ne jamais mettre de mot de passe en argument ou en
fichier. Cela utilise les privilèges déjà attribués, sans en octroyer
de nouveaux.

```bash
cd /workspace/users/albandrieu30/ansible-workstation
python3 -m unittest discover -s tests -p 'test_*contract.py' -v

# Étape manuelle et facultative, avec accord explicite :
sudo -v
mise run audit-network-privileged
```

**Ne jamais** lancer `sudo python3 scripts/audit-workstation-network-privileged.py`
ou `sudo ansible-playbook`. Le programme refuse une exécution root.
En cas de refus de droits, le rapport retourne `access_denied` et garde
`effective_filtering=not_verified`. Ne pas modifier sudoers pour
faire passer ce contrôle.

Même en cas de lecture autorisée, la sortie ne contient que des politiques
de chaînes de base, des comptages bornés et des indicateurs Docker.
Les adresses, ports, noms de chaînes privées, règles brutes, stdout/stderr
privilégiés et secrets ne sont jamais émis ni enregistrés.
Le rapport doit **toujours** indiquer `effective_filtering=not_verified` :
la présence d'une politique DROP/ACCEPT ne prouve pas l'accessibilité
WAN/LAN, les règles NAT ni leur ordre d'application.

Les commandes priviligiées sont limitées à **5 secondes chacune** et à
**1 Mio maximum** de résultat utile ; au-delà, le statut devient
`error` sans rendre les données. Cela n'est pas une garantie de
limitation mémoire stricte pendant la capture, mais borne les données
acceptées par le parseur.

Pour confirmer un filtrage effectif, il faudra un contrôle séparé des
ports exposés et des flux LAN/WAN (sans publication d'adresses),
après revue des politiques observées. **Aucun changement des règles
n'est autorisé par ce runbook.**

## Nouvelle preuve privilégiée reçue le 27 octobre 2026

L'opérateur a exécuté volontairement `sudo -v`, puis
`mise run audit-network-privileged`, enfin `sudo -k`. Les trois sondes
(`nft`, `iptables`, `ip6tables`) sont revenues **`ok`**.
Les politiques de base `INPUT`, `FORWARD`, `OUTPUT` IPv4/IPv6 et les
huit chaînes de base nftables observées sont toutes `accept`.
**79** règles `filter` IPv4, **10** règles `filter` IPv6 et **151**
règles nftables ont été recensées ; des chaînes `DOCKER` et
`DOCKER-USER` existent dans les deux vues iptables.
Le forwarding IPv4 **et IPv6** est activé.

**Interprétation prudente :** ces observations ne prouvent pas que le
trafic passe dans `DOCKER-USER` ou qu'une règle `DROP` existe ou non.
Le champ nftables `docker_table_present=false` ne peut pas contredire
la présence des chaînes Docker côté iptables : les noms des tables
nftables ne sont pas toujours ceux des chaînes Docker. Docker peut
utiliser iptables ou nftables et les règles par défaut ACCEPT ne
décrivent pas le filtrage effectif.
Documentation : [Docker iptables](https://docs.docker.com/engine/network/firewall-iptables),
[Docker nftables](https://docs.docker.com/engine/network/firewall-nftables).

## Suivi P0 — verdicts explicites et sockets en écoute

La collecte `scripts/audit-workstation-network.py` a été enrichie avec
des **compteurs syntaxiques** de verdicts terminaux `ACCEPT`, `DROP`,
`REJECT`, un indicateur `docker_user_jump_in_forward`, et les verdicts
directement présents dans `DOCKER-USER`. Ils ne reconstituent **pas** le
chemin d'un paquet et ne confirment pas la présence d'une règle effectivement
applicable à un flux donné.

En complément, `scripts/audit-workstation-listeners.py` et
`playbooks/audit-workstation-listeners.yml` exploitent `ss` sans
privilèges. Les sockets TCP et UDP sont comptées par catégorie :

- `wildcard` : écoute non liée à une adresse précise ;
- `loopback` : écoute locale ;
- `interface_specific` : écoute liée à une adresse non-loopback ;
- `unknown` : adresse ou format impossible à classifier.

**Aucun port, IP, PID, interface, application ni adresse liée n'est affiché.**
Les sockets `wildcard`/non-loopback ne prouvent pas une accessibilité
WAN ou LAN. Les ports Docker publiés via DNAT peuvent ne pas apparaître
comme sockets écoutant sur l'hôte. Aucun appel au socket Docker.

```bash
cd /workspace/users/albandrieu30/ansible-workstation

# Validations non privilégiées, sans modification du poste :
python3 -m unittest discover -s tests -p 'test_*contract.py' -v
mise run audit-network-syntax
mise run audit-listeners-syntax
mise run audit-listeners
```

Le nouvel inventaire des sockets ne nécessite **pas** de `sudo`.
Pour actualiser les nouveaux compteurs de verdicts du collecteur déjà
approuvé, `mise run audit-network-privileged` demeure **optionnel** ;
ne relance pas `sudo -v` sans besoin explicite.

### Correction du décodage des écoutes `ss` (27 octobre 2026)

L'opérateur a exécuté le commit `d22a5cf`. Le contrôle Ansible a terminé
avec `ok=2 changed=0 failed=0`, mais la suite des **88 contrats a échoué
sur 1 test** (`test_tcp_and_udp_counts_are_anonymized`).
Le parseur utilisait `values[4]` (colonne **Peer Address:Port**) au
lieu de `values[3]` (**Local Address:Port**) de la commande
`ss -H -ln[t|u]`. Les pairs étant fréquemment `0.0.0.0:*`,
il a attribué à tort `wildcard` aux **54 TCP et 135 UDP** observés.

**Données invalidées :** la répartition TCP/UDP entre `wildcard`,
`loopback`, `interface_specific` et `unknown` du relevé `d22a5cf`.
Les totaux 54 TCP et 135 UDP restent des observations valides, mais ne
permettent **pas** d'affirmer que ces sockets écoutent sur toutes les
interfaces. Aucun niveau d'exposition réseau ne doit être déduit de ce
rapport.

Le correctif utilise exclusivement `values[3]`, et les contrats
vérifient maintenant que des pairs wildcard ne masquent pas une adresse
locale loopback/interface-specific. Un local malformé demeure `unknown`.
**Runtime corrigé non encore validé** : refaire les contrats puis
`mise run audit-listeners` sans sudo ; n'enregistrer l'état comme
accepté qu'après 0 échec et une répartition plausible. Ne pas relancer
de collecte privilégiée pour ce défaut.

### Revalidation runtime du collecteur corrigé — 27 octobre 2026

L'opérateur a récupéré le commit `713d95c` et exécuté
`python3 -m unittest discover -s tests -p 'test_*contract.py' -v` :
**90/90 PASS**. `mise run audit-listeners` a terminé avec
`localhost ok=2 changed=0 unreachable=0 failed=0`, sans sudo.

Le rapport corrigé `workstation-listener-visibility/v1` donne :

| Famille | Total | Wildcard | Loopback | Adresse spécifique | Unknown |
| --- | ---: | ---: | ---: | ---: | ---: |
| TCP | 54 | 34 | 16 | 4 | 0 |
| UDP | 135 | 51 | 5 | 47 | 32 |

**Les colonnes `Local Address` et `Peer Address` sont maintenant
distinguées correctement.** Les comptes précédents classant
l'intégralité de TCP/UDP en wildcard restent **invalidés**.
Les 32 résultats UDP `unknown` ne sont pas classables à partir de la
seule sortie agrégée ; ils ne doivent pas être transformés en
`wildcard` ni interprétés comme une panne ou une exposition.

**Statut :** collecteur des portées TCP/UDP **ACCEPTED runtime** pour
le schéma courant ; sémantique des 32 `unknown` à qualifier.
`effective_reachability=not_verified` reste inchangé. Une nouvelle
analyse des formats `ss` doit rester purement agrégée, sans divulgation
d'adresses IP, ports, PID ni chemins de sockets.

**Validation obtenue :** 90 tests, classification des portées et
`changed=0 failed=0`. **À approfondir :** 32 sockets UDP `unknown`
et la portée effective des flux depuis d'autres segments du réseau.
Le statut de protection et d'accessibilité reste `not_verified`.

## P0 suivant — audit approfondi sur autorisation

Préparer un chemin **séparé** de lecture privilégiée des politiques effectives et des publications de ports, avec identité contrôlée, commande exacte et filtre de sortie prouvé. Ne pas exécuter `nft list ruleset` ou `iptables-save` en root et publier la sortie brute ; elle peut contenir des adresses et des informations internes. Ne jamais activer UFW ni désactiver IPv4 forwarding avant de caractériser les chaînes Docker et le chemin de retour.
