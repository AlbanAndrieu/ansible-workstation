# Roadmap ansible-workstation — Ubuntu secure-by-default

**Périmètre :** seulement `ansible-workstation`. Contrat : [Option A](workstation-ownership-option-a.md). La vue homelab/YubiKey reste dans [nabla-compose](https://github.com/AlbanAndrieu/nabla-compose/blob/master/docs/roadmap-workstation-yubikey.md) ; shell utilisateur dans [dotfiles](https://github.com/AlbanAndrieu/dotfiles/blob/main/docs/roadmap-workstation.md).

| Priorité | Livrable | Gate de validation | Statut |
| --- | --- | --- | --- |
| P0 | Retirer le bundle YubiKey/PAM historique du rôle global | Aucune importation `yubikey.yml`, aucune mutation PAM, aucune action matériel | Code retiré en PR #16 ; 52/52 contrats locaux PASS le 27/10 ; aucun apply |
| P0 | Nouveau [`playbooks/audit-workstation.yml`](../playbooks/audit-workstation.yml), distinct de `workstation.yml` | Tests Python + `mise run audit-syntax` + exécution avec `changed=0` | **ACCEPTED runtime** : 60/60, `ok=14 changed=0`, noyau AppArmor enabled, 3 timers actifs ; [preuves](audit-workstation.md) |
| P0 | [Visibilité Docker/nftables/iptables sans privilèges](audit-workstation-network.md) | 8 tests ciblés, lecture locale, résultat `not_verified` si accès refusé, aucune donnée brute | **ACCEPTED runtime** : 68/68 tests, 3 sondes `access_denied`, forwarding IPv4/IPv6 activé, filtrage `not_verified` |
| P0 | [Lecture privilégiée **optionnelle** des métadonnées réseau](audit-workstation-network.md) | Aucun script Python root ; commandes fixes `sudo -n`, données brutes non publiées ; tests locaux | **CODE ADDED / RUNTIME NOT VERIFIED** |
| P0 | Audit **effectif** des règles firewall, des ports publiés, de SSH et de Fail2ban | Inventaire autorisé, politiques et chemins entrants vérifiés avec preuves expurgées | À faire ; exige une procédure de lecture privilégiée explicite |
| P0 | Corriger le périmètre Ubuntu 26.04 du playbook historique | Plus de faux « unsupported » ; profil OS explicite, aucun apply global | À faire |
| P1 | Transférer l'inventaire JSON v1 de dotfiles ici | Contrat JSON équivalent et collecteur unique ; date/source par champ | À faire |
| P1 | Comparer état observé et politique `policies/home-desktop.yml` | Drift classé attendu/inconnu/non conforme, sans secrets | À faire |
| P1 | Profil minimal des paquets/services opt-in ; retirer vieilles distributions | `--check` non destructif, tasks idempotentes, rollback | À faire |
| P1 | Restic : configuration chiffrée hors Git, sauvegarde /etc ciblée + état privé | `restic check` + restauration isolée réussie + copie indépendante | À faire |
| P1 | Nettoyer `tasks/security.yml` et mises à jour unattended | Pas de `dpkg-reconfigure` non conditionné ni écrasement de config arbitraire | À faire |
| P2 | Auditer Secure Boot / TPM / module NVIDIA | Diagnostic seulement, aucun changement firmware sans consentement | À faire |
| P2 | Rôle opt-in des **dépendances OS** YubiKey si besoin | Apt/pcsc uniquement, aucun PIN/PUK/PIV/FIDO2/PAM | À décider après couverture Compose |
| P2 | Pipeline audit → plan → apply + rétablissement éprouvé | Aucune modification système non déclarée ; rollback local testé | À faire |

**Faits ne sont pas sauvegardes.** Les snapshots machine restent hors Git avec rétention ; Restic assure la conservation chiffrée et la restauration. Il faut conserver une copie indépendante de TrueNAS.

**Déjà livré :** PR #13 fusionnée (mise/uv/Direnv, DNS opt-in, règles fail-safe), 49/49 contrats locaux PASS. Ces preuves ne démontrent pas le playbook d'installation complet.

**Pas de CI payante ni de fusion automatique.** Preuves du 27 octobre : audit système `60/60`, `ok=14 changed=0` ; audit réseau sans privilèges `68/68`, `ok=2 changed=0`, trois sondes `access_denied`, forwarding IPv4/IPv6 activé. Prochaine validation : contrats du collecteur optionnel. L'authentification `sudo` et la lecture privilégiée sont toujours **facultatives** et nécessitent une action explicite de l'opérateur ; la politique effective reste `not_verified`.
