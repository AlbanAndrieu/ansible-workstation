# Inventaire sûr de /etc, DNS et services systemd (30 octobre 2026)

## Objectif

Le dépôt **ansible-workstation** devient la source de vérité de la configuration **OS Ubuntu** ; le contenu privé et les données utilisateur restent hors Git. La PR #16 a posé les contrats d'audit. Cette extension ajoute un inventaire **read-only** par allowlist, non une copie de `/etc`.

## Exécution locale

```bash
cd /workspace/users/albandrieu30/ansible-workstation
git fetch origin
git switch audit/workstation-etc-systemd-dns-20261030
mise run check-venv
.venv/bin/python -B -m unittest tests/test_workstation_configuration_audit_contract.py -v
mise run audit-configuration
mise run audit-openclaw-source
```

Ces commandes ne requièrent ni sudo ni accès au socket Docker. Les sondes DNS collectent uniquement les métadonnées de configuration de `eno1`, **pas** un résultat de résolution : `dns_resolution=not_tested` est intentionnel. Elles ne prouvent aucune accessibilité WAN.

## DNS : séparer trois propriétés

1. **Route :** `resolvectl dns eno1` doit porter exclusivement `172.17.0.1` sur le lien ; `resolvectl domain eno1` doit porter `~int.albandrieu.com`.
2. **Réponse de pfSense :** après audit, exécuter `dig @172.17.0.1 sample.int.albandrieu.com A +time=2 +tries=1` et `getent ahostsv4 sample.int.albandrieu.com`, sans modifier les DNS.
3. **DNSSEC :** valider indépendamment le NTA de la zone privée et la protection vers l'amont. L'usage de UDP/TCP 53 entre station et pfSense n'est pas du DoT de bout en bout.

Si les résultats divergent, examiner les overrides `/etc/systemd/resolved.conf.d`, `/etc/NetworkManager/conf.d`, dispatcher, VPN et profil actif. Ne jamais réécrire `/etc/resolv.conf` ou modifier le firewall automatiquement.

## Contrat systemd et OpenClaw

Le rapport renseigne seulement `LoadState`, `ActiveState` et `UnitFileState` pour des unités système explicitement connues et pour `openclaw-gateway.service` en scope utilisateur. Il **ne lit pas** `ExecStart`, `Environment`, `EnvironmentFile`, les drop-ins ou les credentials. Par conséquent, **aucune parité n'est attestée** entre la configuration systemd chargée et les templates Git.

Le template historique `templates/openclaw-gateway-systemd.sh-Ubuntu.j2` contient Node 25.4.0 et OpenClaw 2026.4.15 : **apply interdit**. La référence runtime attendue de la workstation est Node 24 et OpenClaw 2026.10.7. Les éventuelles unités utilisateur appartiennent à `dotfiles` selon l'Option A ; le dépôt Ansible n'en prend que l'inventaire OS/contrat. La migration vers TrueNAS relève de `nabla-openclaw`.

## /etc : promotion contrôlée

| Domaine | Candidats | Traitement |
| --- | --- | --- |
| DNS et LAN | NetworkManager, resolved, dispatcher | Ansible opt-in + drift |
| Sécurité | sshd_config.d, sysctl.d, nftables, ufw, fail2ban, apparmor.d | Contrats et rôle ciblé après revue |
| Démarrage | systemd/system, journald.conf, logind.conf, fstab, crypttab | Inventory, jamais remplacement global |
| Paquets | apt/apt.conf.d, modprobe.d, modules-load.d | Paramètres souhaités déclaratifs |
| Containers | docker/daemon.json, containerd/config.toml | Auditer sans socket Docker |
| Privilèges | sudoers.d | Examiner seulement, pas de copie ni de sudo automatique |

**Interdiction de collecter ou commiter** `/etc/shadow`, `/etc/gshadow`, `/etc/ssh/ssh_host_*`, `/etc/NetworkManager/system-connections/*`, `/etc/wireguard/*`, certificats/clefs privées, jetons, mots de passe, fichiers `.env`, secrets OpenClaw ou identités personnelles. La présence d'un fichier ne garantit pas sa sûreté : la collecte de contenu doit être une seconde phase avec revue et suppression des secrets avant publication.

La sauvegarde chiffrée (Restic) est distincte de Git : conserver une copie indépendante et prouver une restauration isolée avant de la considérer achevée.

## État de validation

**CODE ADDED / WORKSTATION RUNTIME NOT VERIFIED**. Les scripts et tests présents dans cette branche ne sont pas la preuve d'une exécution sur la station. Aucun sudo, apply Ansible, changement DNS/systemd, ou test réseau externe réalisé.
