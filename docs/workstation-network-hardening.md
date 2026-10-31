# Durcissement réseau de la workstation (31 octobre 2026)

**Constat (lecture seule, sans sudo) :** `ufw.conf` porte `ENABLED=yes` et des politiques DROP, mais
`ufw.service` est désactivé : aucun filtrage ufw au boot. Une trentaine de ports TCP écoutent sur toutes
les interfaces. Avec `userland-proxy: false`, les ports publiés par Docker passent en DNAT avant ufw.

[`playbooks/harden-network.yml`](../playbooks/harden-network.yml), décisions validées par l'opérateur :

| Action | Raison |
| --- | --- |
| Retirer `nfs-kernel-server`, masquer `rpcbind` | Client NFSv4.2 de TrueNAS uniquement, aucun export ; `nfs-common` dépend du paquet rpcbind |
| zabbix-agent2 : `Server`/`ServerActive` = TrueNAS `172.17.0.24` | L'agent pointait sur `127.0.0.1` |
| Supprimer `/etc/datadog-agent-2025-06-20` | Datadog n'est plus installé |
| ufw : entrée refusée sauf allowlist | Voir ci-dessous ; sortie et forwarding inchangés (Docker, libvirt) |

Allowlist : depuis le LAN `172.17.0.0/24` apache 8082/8087, minidlna 8200 + SSDP 1900/udp,
mDNS 5353/udp, rsyslog 514 tcp/udp, snmp_exporter 9116, Synergy/Deskflow 24800 + service Synergy
24802, Dropbox 17500 tcp/udp. Depuis TrueNAS
seulement : LiteLLM 4000 (openrag, litellm, langflow de `nabla-compose`), ollama 11434, zabbix 10050.
Depuis les bridges Docker locaux `172.16.0.0/16` : 4000 et 11434.

```bash
mise run harden-network-check   # plan seulement
# Depuis la console locale :
.venv/bin/ansible-playbook -i localhost, -c local playbooks/harden-network.yml \
  -e harden_apply=true -e harden_apply_approved=true -K
sudo ufw status verbose          # vérification ; retour arrière : sudo ufw disable
```

**Non couvert :** ports Docker publiés (le conteneur `telegraf` publie `0.0.0.0:8126`, pas Datadog) ;
postgres 5432, redis 6379 et les ports inconnus restent ouverts sur l'hôte mais deviennent
inaccessibles depuis le LAN une fois ufw actif. Le serveur Zabbix de TrueNAS doit connaître l'hôte
`albandrieu`.

Premier apply (31 octobre 2026) : NFS serveur, rpcbind, Zabbix et Datadog appliqués, puis échec de
`ufw-init`. Le bloc « UFW AND DOCKER » de `/etc/ufw/after.rules` avait été inséré avant le `COMMIT`
d'origine (deux `*filter` dans la même table). Le playbook ajoute ce `COMMIT` (copie de sauvegarde
gardée) ; la version corrigée passe `iptables-restore --test`. Le redémarrage de zabbix-agent2 n'a
pas eu lieu : `sudo systemctl restart zabbix-agent2`.

Second apply : **ufw actif** (`deny` en entrée et routé), allowlist en place, zabbix-agent2
redémarré, sortie hôte et Docker vérifiées. D'anciennes règles ouvertes à tous étaient encore
enregistrées : 8086, 2003, 22, 24800, 9000, **5432 (postgres en écoute)** et l'interface
`cni0` (k3s retiré). Le playbook les supprime désormais ; 24800 (Synergy, et Deskflow sur le même
port) reste ouvert, mais seulement depuis le LAN. **À rejouer** pour qu'elles disparaissent.

## Durcissement OS : devsec.hardening.os_hardening

[`playbooks/harden-os.yml`](../playbooks/harden-os.yml) applique `os_hardening` (collection figée en
10.5.0) en **mode check** tant que `harden_os_apply` et `harden_os_apply_approved` ne sont pas
vrais. Même la simulation demande sudo. Réglages adaptés à la workstation :

| Réglage dev-sec | Choix | Raison |
| --- | --- | --- |
| PAM (`os_pam_enabled`) | désactivé | YubiKey et howdy, gérés par nabla-yubikey |
| Expiration du mot de passe utilisateur | désactivée | poste mono-utilisateur |
| Suppression des `.netrc` | désactivée | effacement sans sauvegarde |
| `/etc/default/ufw` | non géré | appartient à `harden-network.yml` |
| `hidepid` sur `/proc` | `0` | `2` masque les processus à polkit et GNOME |
| `ip_forward`, `rp_filter`, IPv6 RA/SLAAC, SysRq | valeurs actuelles | Docker, libvirt, VPN, IPv6 |
| `kernel.unprivileged_userns_clone` | `1` | sandbox Chrome/Electron, flatpak, podman rootless |
| `ssh_hardening` : service sshd | désactivé | openssh-server installé mais inutilisé ; config durcie pour plus tard |
| `ssh_hardening` : client | non géré | `ssh_config.d/99-workstation.conf`, clés FIDO, agent |

Simulation du 31 octobre 2026 : `ok=89 changed=31 failed=0`. Changements prévus à relire avant
apply : auditd installé et configuré, `login.defs` réécrit (UMASK 027), limites core dump, `su` en
0750, `/dev`, `/dev/shm` et `/run` remontés `nosuid`/`noexec` dans `fstab`, modules de systèmes de
fichiers inutiles bloqués, bit suid retiré de `ssh-keysign`, `pppd`, `lockfile` et `dotlockfile`,
shell retiré aux comptes système, dossiers home en 0750, paquet `ypserv` retiré (service inactif
et désactivé ; la config NIS de `/var/yp` reste). Avec `ssh_hardening` : `ok=127 changed=37
failed=0` ; `sshd_config` réécrit (clé publique seule, pas de root), clé hôte RSA régénérée en
4096 bits, activation par socket et MOTD dynamique coupés, sshd laissé désactivé.

```bash
mise run harden-os-check   # simulation --diff, sudo demandé
# Apply, depuis la console locale, après relecture du diff :
.venv/bin/ansible-playbook -i localhost, -c local playbooks/harden-os.yml \
  -e harden_os_apply=true -e harden_os_apply_approved=true -K
```

Retour arrière : pas de rollback automatique ; les fichiers de `/etc` capturés dans `files/etc`
servent de référence. **RUNTIME NOT VERIFIED** : simulation seulement.
