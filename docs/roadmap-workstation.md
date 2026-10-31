# Roadmap ansible-workstation — Ubuntu secure-by-default

**Périmètre :** seulement `ansible-workstation`. Contrat : [Option A](workstation-ownership-option-a.md). La vue homelab/YubiKey reste dans [nabla-compose](https://github.com/AlbanAndrieu/nabla-compose/blob/master/docs/roadmap-workstation-yubikey.md) ; shell utilisateur dans [dotfiles](https://github.com/AlbanAndrieu/dotfiles/blob/main/docs/roadmap-workstation.md).

| Priorité | Livrable | Gate de validation | Statut |
| --- | --- | --- | --- |
| P0 | Retirer le bundle YubiKey/PAM historique du rôle global | Aucune importation `yubikey.yml`, aucune mutation PAM, aucune action matériel | **ACCEPTED** : ancien PPA + templates PAM retirés ; couverture des dépendances OS restaurée séparément en mode opt-in |
| P0 | Nouveau [`playbooks/audit-workstation.yml`](../playbooks/audit-workstation.yml), distinct de `workstation.yml` | Tests Python + `mise run audit-syntax` + exécution avec `changed=0` | **ACCEPTED runtime** : 60/60, `ok=14 changed=0`, noyau AppArmor enabled, 3 timers actifs ; [preuves](audit-workstation.md) |
| P0 | [Visibilité Docker/nftables/iptables sans privilèges](audit-workstation-network.md) | 8 tests ciblés, lecture locale, résultat `not_verified` si accès refusé, aucune donnée brute | **ACCEPTED runtime** : 68/68 tests, 3 sondes `access_denied`, forwarding IPv4/IPv6 activé, filtrage `not_verified` |
| P0 | [Lecture privilégiée **optionnelle** des métadonnées réseau](audit-workstation-network.md) | Aucun script Python root ; commandes fixes `sudo -n`, données brutes non publiées | **ACCEPTED runtime** : 77/77 tests et 3 sondes `ok`, 79+10 règles filter et 151 nft ; politiques observées ACCEPT |
| P0 | [Sauts DOCKER-USER et verdicts explicites](audit-workstation-network.md) | Compter ACCEPT/DROP/REJECT et prouver le saut FORWARD vers DOCKER-USER sans exposer de règle | **CODE ADDED / RUNTIME NOT VERIFIED** |
| P0 | [Sockets TCP/UDP par portée d'écoute](audit-workstation-network.md) | Lecture de la colonne locale, IPv6 zoné, rapport agrégé sans ports ni adresses | **ACCEPTED runtime** : 95/95 tests, `ok=2 changed=0` ; TCP 54 et UDP 135, `unknown=0` |
| P0 | Motifs UDP `unknown` et contrôle des formats `ss` | `malformed_row` / `unparsed_local_endpoint` uniquement, aucun endpoint affiché | **CLOS** : 32 inconnues reclassées, 0 restant au dernier audit |
| P0 | [Parsing IPv6 avec zone d'interface après le crochet](audit-workstation-network.md) | Scénarios `[IPv6]%iface:port`, `[IPv6%iface]:port` et refus des formats invalides | **ACCEPTED runtime** : 95/95 tests, 32 UDP reclassées dans `interface_specific` |
| P0 | [Contrat de preuves LAN/WAN, publications Docker et firewall](workstation-network-exposure-plan.md) | Plan de vérification depuis des origines autorisées, inventaire privé, résultat expurgé, rollback avant apply | **PLAN DOCUMENTÉ, EXÉCUTION NON FAITE** ; `not_verified` |
| P0 | [Mesures TCP par allowlist privée : local/LAN/WAN](workstation-network-measurement.md) | Cibles préautorisées, aucune découverte ; observateurs séparés requis | **LOCAL ACCEPTED** : 2/2 attendus ; **LAN TWO TARGETS OBSERVED** : 2/2 `refused` depuis TrueNAS déclaré ; autres ports LAN et WAN `not_verified` |
| P0 | [Observateur Docker local, optionnel](workstation-network-measurement.md) | Collecte `docker container ls` expurgée après autorisation explicite | **ACCEPTED runtime (collecte)** : 12 conteneurs, 9 segments publiés TCP IPv4 wildcard, 3 exposed-only ; exposition WAN `not_verified` |
| P0 | [Exécuteur de contrats Python isolé](../mise.toml) | `mise run test-offline` vérifie puis utilise `.venv/bin/python` avec PyYAML ; aucun fallback global | **ACCEPTED runtime** : 116/116 PASS sur `23f5628`, 0 erreur PyYAML ; aucune CI payante |
| P0 | Audit **effectif** des flux LAN, des publications Docker, de SSH et de Fail2ban | Mesures allowlist sur chaque exposition approuvée, revue du pare-feu sans modification | **P0 PARTIEL** : 2 ports TCP LAN refusés depuis observateur TrueNAS déclaré ; **9 segments Docker wildcard encore non testés depuis LAN** |
| P0 | Accessibilité WAN **facultative** en l'absence d'observateur extérieur | Téléphone en données cellulaires pour HTTP(S) autorisé, ou origine externe contrôlée ; vérifications NAT/IPv6/Cloudflare en attendant | **DIFFÉRÉ / WAN NOT VERIFIED** : aucun autre ordinateur disponible hors LAN ; ne bloque pas P0 LAN |
| P0 | Corriger le périmètre Ubuntu 26.04 du playbook historique | Plus de faux « unsupported » ; profil OS explicite, aucun apply global | À faire |
| P1 | Transférer l'inventaire JSON v1 de dotfiles ici | Contrat JSON équivalent et collecteur unique ; date/source par champ | À faire |
| P1 | Comparer état observé et politique `policies/home-desktop.yml` | Drift classé attendu/inconnu/non conforme, sans secrets | À faire |
| P1 | Profil minimal des paquets/services opt-in ; retirer vieilles distributions | `--check` non destructif, tasks idempotentes, rollback | À faire |
| P1 | Restic : configuration chiffrée hors Git, sauvegarde /etc ciblée + état privé | `restic check` + restauration isolée réussie + copie indépendante | À faire |
| P1 | Nettoyer `tasks/security.yml` et mises à jour unattended | Pas de `dpkg-reconfigure` non conditionné ni écrasement de config arbitraire | À faire |
| P2 | Auditer Secure Boot / TPM / module NVIDIA | Diagnostic seulement, aucun changement firmware sans consentement | À faire |
| P0 | [Prérequis OS YubiKey Ubuntu autonomes](yubikey-os-prerequisites.md) | Audit sans sudo/PAM/PPA, package_facts et candidats APT ; installation doublement autorisée mais non exécutée | **ACCEPTED runtime (audit seul)** : 131/131 PASS, syntaxe PASS, `ok=8 changed=0 failed=0`, **7/7 paquets présents** ; aucun apply |
| P2 | Pipeline audit → plan → apply + rétablissement éprouvé | Aucune modification système non déclarée ; rollback local testé | À faire |

**Faits ne sont pas sauvegardes.** Les snapshots machine restent hors Git avec rétention ; Restic assure la conservation chiffrée et la restauration. Il faut conserver une copie indépendante de TrueNAS.

**Déjà livré :** PR #13 fusionnée (mise/uv/Direnv, DNS opt-in, règles fail-safe), 49/49 contrats locaux PASS. Ces preuves ne démontrent pas le playbook d'installation complet.

**YubiKey :** l'opérateur a validé le nouveau playbook Ubuntu OS : **131/131 contrats offline PASS**, syntaxe Ansible PASS, audit `ok=8 changed=0 failed=0 skipped=3`. Les 7 prérequis runtime sont tous installés et disponibles en APT ; **pas d'installation nécessaire**. Aucun apply ni mutation PAM/carte effectuée. Le signalement `mise WARN missing` concerne des outils de développement supplémentaires, pas une absence de paquets YubiKey ; [détails](yubikey-os-prerequisites.md).

**Pas de CI payante ni de fusion automatique.** Preuves du 27 octobre : audit système 60/60 ; réseau sans privilèges 68/68 ; lecture filtrage avec autorisation 77/77 et 3 sondes `ok` ; sockets 90/90, `ok=2 changed=0 failed=0`. IPv4/IPv6 forwarding actif, politiques de base ACCEPT. **Suivant :** rapprocher les **9 segments Docker TCP IPv4 wildcard** des services réellement autorisés, créer une allowlist privée, puis vérifier uniquement ces chemins depuis TrueNAS. Deux ports LAN (OpenClaw et SSH) ont déjà produit `refused` ; le reste du LAN est `not_verified`. Aucun observateur WAN disponible : WAN reste `not_verified` sans bloquer la suite. [Procédure](workstation-network-measurement.md). Les **116/116 contrats** sont validés sur la `.venv` ; le localhost **2/2** et la collecte Docker ont déjà réussi. Ne pas relancer ces vérifications sans raison. Les 95 tests du parseur et le relevé sans sudo sont désormais **validés**. Le comptage des verdicts Docker existe dans le code mais n'a pas été réexécuté avec l'audit privilégié. Les protections réseau effectives restent `not_verified`.

| P1 | [Extraire le code Workstation de nabla-compose](migration-from-nabla-compose-20261030.md) | Test d'équivalence des sondes, versions mise/Node/systemd, secrets hors dépôt, contrat OpenClaw 2026.10.7 | **PREPARED / NO CUTOVER** : fichier de migration et garde sur ancien template Node25 ; pas de code déplacé |
| P2 | Transférer les contrats matériels vers `nabla-yubikey` | Dossier migratoire avec scripts + tests hermétiques, aucun secret/PAM, règles NFS séparées | **DÉPÔT CRÉÉ / PREMIER LOT EN PR DRAFT** ; pas de PAM ou d'actions matérielles |

| P1 | [OpenClaw : audit de la Workstation source, cible TrueNAS](openclaw-workstation-to-truenas.md) | Contrats offline, syntaxe Ansible, aucune mutation, état CLI/unit sans secrets | **CODE ADDED / RUNTIME NOT VERIFIED** ; Gateway cible géré par `nabla-openclaw`, pas Ansible |
| P2 | Découpler les scripts OpenClaw/TrueNAS | Définir API de sonde entre `nabla-openclaw` et `nabla-compose`, wrappers temporaires | **À FAIRE** après image/dataset/modèles validés |

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
