# P0 — Mesurer la joignabilité TCP depuis localhost, LAN et WAN

**Statut : mesures localhost et inventaire Docker exécutés le 27 octobre 2026 ; preuves LAN/WAN indépendantes non encore effectuées.**
L'[audit d'écoute](audit-workstation-network.md) est accepté (95/95 tests),
mais `ss` et les politiques firewall ne prouvent pas qu'un port soit
accessible. Ce protocole implémente la
[gate de mesure réseau](workstation-network-exposure-plan.md) sans
modifier Docker, le pare-feu ou la workstation.

## Preuves opérateur et correction du runner — 27 octobre 2026

- `mise run measure-network-local` : exécution répétée avec résultat
  identique, **2/2 connexions conformes aux attentes** ; 1 TCP
  `connected` (`expected_allowed`) et 1 `refused`
  (`expected_denied`). Aucun timeout, résultat `unexpected_open=0`.
  Cette preuve est **uniquement locale**.
- `mise run measure-docker-publishing` : **`status=ok`**,
  **12 conteneurs recensés** et **9 segments TCP IPv4 publiés en
  `wildcard`**, 0 IPv6/UDP dans ce résumé et 3 segments uniquement
  exposés dans les conteneurs. Un segment Docker ne signifie pas
  nécessairement un port unique, ni une ouverture réellement joignable
  depuis le LAN/WAN.
- Nouveau module de tests : l'opérateur a exécuté
  `python3 -m unittest discover ...` et obtenu **84 tests lancés,
  3 erreurs d'import de `yaml`**, car l'interpréteur global de
  `mise` ne contient pas PyYAML ; les autres **81 cas exécutés
  passent**. Ce n'est pas un échec du collecteur réseau.
- `PyYAML` figure déjà dans `pyproject.toml`. Le runner canonique
  `mise run test-offline` a été corrigé pour vérifier
  `scripts/uv-project.sh check` puis utiliser **`.venv/bin/python`**
  sans installer de paquets globalement.

**Dernière preuve locale (révision `23f5628`, 27 octobre 2026) :**
`mise run test-offline` a exécuté les **116 tests avec succès** en
1,461 s, sans erreur ni échec. `PyYAML` a été chargé depuis la
`.venv` vérifiée ; aucune installation de paquet global n'a été nécessaire.
Les messages `--ack-* required` pendant deux tests sont attendus : ils
vérifient le refus d'exécution sans consentement. Statut du runner :
**ACCEPTED RUNTIME**.

Cette preuve ne valide **aucune mesure depuis un observateur LAN ou WAN**.
Le prochain jalon reste un relevé indépendant depuis chacun de ces
segments, sur un manifest privé strictement limité aux services autorisés.

## Trois origines d'observation

| Origine | Machine qui doit exécuter le collecteur | Ce que l'observation démontre |
| --- | --- | --- |
| `local` | Workstation elle-même | Connexion à son propre loopback, **pas** une preuve LAN |
| `lan` | **Autre** machine LAN explicitement autorisée | Connexion vers l'adresse LAN choisie ; ne démontre rien sur le WAN |
| `wan` | **Autre** machine réellement hors LAN (VPS ou autre origine maîtrisée) | Connexion vers l'IP publique autorisée ; une adresse Cloudflare/proxy ne démontre pas que le trafic atteint la workstation |

Le paramètre `--observer` est une déclaration **de l'opérateur**, et ne
vérifie pas l'indépendance ni la localisation réelle de la machine.
Ne jamais déclarer `lan` ou `wan` pour une commande qui tourne sur
la workstation elle-même et revendiquer une preuve distante.

## Manifest privé et strict

Le fichier **ne doit jamais être enregistré dans Git**. Il contient les
IP, les ports et les attentes : permissions `0600`, propriétaire courant,
chemin **absolu hors dépôt**, pas de lien symbolique et taille maximale
16 Kio. Il autorise au maximum **12 endpoints** au total.

Exemple **local uniquement**, à ajuster en fonction des services réellement
autorisés avant de mesurer ; aucune cible LAN/WAN n'est définie
automatiquement :

```bash
umask 077
mkdir -p "$HOME/.config/workstation-audit"
cat > "$HOME/.config/workstation-audit/targets.json" <<'JSON'
{
  "schema": "workstation-connectivity-allowlist/v1",
  "targets": [
    {"observer":"local","address":"127.0.0.1","port":18789,"expected":"allow"},
    {"observer":"local","address":"127.0.0.1","port":22,"expected":"deny"}
  ]
}
JSON
chmod 600 "$HOME/.config/workstation-audit/targets.json"
```

Les valeurs proposées correspondent aux deux **hypothèses** suivantes :
OpenClaw sur 127.0.0.1:18789 et absence de serveur SSH local.
Elles doivent être confirmées ou ajustées par l'opérateur ; elles ne
constituent pas un contrat permanent pour l'hôte.

Ajouter séparément, **dans le fichier privé**, des entrées pour `lan`
(IP RFC1918 ou IPv6 ULA) et `wan` (IP globalement routable), avec des
ports choisis et autorisés, une attente `allow` ou `deny`, sans
scan implicite de plages. **Aucun hostname** n'est accepté et aucun DNS
n'est appelé par le collecteur.

## Exécution locale immédiate

```bash
cd /workspace/users/albandrieu30/ansible-workstation
mise run test-offline

# Dry-run : lit seulement le manifest, 0 connexion TCP
.venv/bin/python -B scripts/measure-workstation-reachability.py \
  --observer local \
  --allowlist "$HOME/.config/workstation-audit/targets.json"

# Mesure locale autorisée : au plus 12 tentatives, une seule par entrée,
# 1,5 s maximum par tentative, sans données applicatives
mise run measure-network-local
```

Depuis un poste LAN distinct disposant du script contrôlé et du manifest
**privé propre à cet observateur** :

```bash
python3 scripts/measure-workstation-reachability.py \
  --observer lan \
  --allowlist "$HOME/.config/workstation-audit/targets.json" \
  --confirm-connect
```

Depuis une **autre origine WAN autorisée**, utiliser la même commande
avec `--observer wan`. Aucun VPN, Cloudflare Tunnel, reverse proxy ou
porte NAT n'est créé ou modifié pour la mesure.

**Ne pas lancer** `--confirm-connect` sur une machine non autorisée,
et ne pas copier le manifest de cibles sur Git ou dans une PR. Il n'y a
ni découverte réseau, ni retries, ni scan UDP, ni timeout illimité.

## Lecture du rapport public

Le schéma `workstation-reachability-measurement/v1` ne contient que
des nombres et l'origine déclarée :

| Résultat | Signification |
| --- | --- |
| `expected_allowed` | Connexion TCP réussie sur une cible dont l'accès est attendu |
| `expected_denied` | TCP explicitement refusé sur une cible dont l'accès doit être fermé |
| `unexpected_open` | TCP connecté malgré une attente `deny` — revue prioritaire |
| `unexpected_closed` | TCP refusé malgré une attente `allow` — disponibilité à vérifier |
| `inconclusive` | Timeout, erreur réseau ou autre échec ambigu ; **pas** classé comme refus prouvé |

Un refus TCP démontre uniquement que **cette tentative** a été refusée ;
il ne démontre pas que tous les autres ports sont filtrés. Une connexion
réussie ne démontre ni la réussite de TLS/auth, ni l'identité du
service visé, ni un défaut de configuration.

Le rapport marque `observer_independence_verified=false` et garde
une limite explicite : les connexions vers un proxy/tunnel peuvent aboutir
sans atteindre la workstation.

## Publications Docker (option explicite et indépendante)

`scripts/measure-workstation-docker-publishing.py` exécute uniquement :

```text
/usr/bin/docker --host unix:///var/run/docker.sock container ls --format '{{json .Ports}}'
```

Seuls des **compteurs de segments de publication** sont affichés par
famille IPv4/IPv6, protocole TCP/UDP et portée (`wildcard`, `loopback`,
`interface_specific`, `unknown`). Un segment couvrant une plage
de ports compte pour **un segment**, pas pour le nombre réel de ports
individuels. Les ports exposés uniquement dans le conteneur ne sont pas
des ports publiés sur l'hôte.

**⚠️ L'accès au socket Docker est un privilège équivalent à root dans
de nombreuses configurations.** Cette commande n'est ni obligatoire
ni lancée par l'audit d'écoute. Son utilisation nécessite une approbation
explicite de l'opérateur. Elle n'élargit pas les groupes utilisateurs,
n'appelle pas `sudo` et ne démarre ni ne modifie de conteneur.

```bash
# Facultatif, uniquement si l'accès Docker est déjà explicitement autorisé :
mise run measure-docker-publishing
```

Un résultat `access_denied` est acceptable. **Ne pas** ajouter
l'utilisateur au groupe `docker` ni modifier le socket pour le faire
réussir. Ne jamais publier `docker ps` ou `docker inspect` bruts.

## Critères d'acceptation et arrêt

1. Les contrats offline et le dry-run passent, sans réseau.
2. L'origine locale mesurée retourne au plus deux résultats selon les
   cibles locales choisies, sans fuite d'adresse/port.
3. Pour affirmer une observation LAN ou WAN, une **autre machine**
   correspondant à l'origine déclarée réalise les connexions explicitement
   autorisées.
4. Les résultats `unexpected_open` déclenchent une revue des règles
   et du chemin d'accès, **pas** un changement automatique de pare-feu.
5. `effective_reachability=not_verified` reste le statut des sondes
   d'écoute et des publications Docker ; le rapport TCP ne certifie que
   les cibles testées depuis l'origine déclarée.

**Aucun apply système et aucun changement UFW, nftables, Docker,
ip_forward, SSH, DNS ou Cloudflare** n'est autorisé par cette étape.

Références : [Docker container ls](https://docs.docker.com/reference/cli/docker/container/ls/),
[Docker daemon attack surface](https://docs.docker.com/engine/security/),
[Python socket](https://docs.python.org/3/library/socket.html).
