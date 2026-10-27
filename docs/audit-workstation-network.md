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

## P0 suivant — audit approfondi sur autorisation

Préparer un chemin **séparé** de lecture privilégiée des politiques effectives et des publications de ports, avec identité contrôlée, commande exacte et filtre de sortie prouvé. Ne pas exécuter `nft list ruleset` ou `iptables-save` en root et publier la sortie brute ; elle peut contenir des adresses et des informations internes. Ne jamais activer UFW ni désactiver IPv4 forwarding avant de caractériser les chaînes Docker et le chemin de retour.
