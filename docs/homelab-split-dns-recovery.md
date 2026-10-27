# LAN split-DNS sur la workstation — reprise du 27 octobre 2026

## Faits observés (pas une hypothèse de panne pfSense)

La workstation Linux sur `eno1` a un serveur DNS **correct**
dans le bail DHCP, le profil et le device NetworkManager :
`172.17.0.1`. Pourtant `resolvectl dns eno1` a affiché
`9.9.9.9 149.112.112.112`. Le nom privé
`defectdojo.int.albandrieu.com` est résolu via
`dig @172.17.0.1` en `172.17.0.24`, mais la résolution NSS du client
a échoué avec `CLIENT_PRIVATE_SPLIT_DNS_PATH`. Chrome rapportait
`DNS_PROBE_FINISHED_NXDOMAIN`.

Depuis TrueNAS, DefectDojo, Traefik, le port 443, les labels,
le réseau Docker et le certificat TLS ont passé les sondes.
Le retour HTTP 302 via `curl --resolve` depuis la workstation
est confirmé. Ne pas modifier pfSense, HAProxy ni TrueNAS.

L'opérateur a appliqué temporairement :

```bash
sudo resolvectl dns eno1 172.17.0.1
sudo resolvectl domain eno1 '~int.albandrieu.com'
sudo resolvectl flush-caches
```

`getent ahostsv4 defectdojo.int.albandrieu.com` a alors renvoyé
`172.17.0.24`. Mais la configuration est redevenue Quad9 sur `eno1`
lors du contrôle suivant et la résolution système a échoué de nouveau :
**le dépannage n'est pas persistant.**

`hide-location.service` est activé et `hide-location.timer` est
activé ; le service a un timestamp de démarrage le 27 octobre à
21:27:01 CET. L'inspection statique du script installé a indiqué
`targets_interface=True`, `resolvectl_dns=True`, mais
`sets_quad9=False`. **Ne pas inférer que ce service est le
processus ayant injecté Quad9** : l'horodatage seul n'établit pas
la causalité. Une autre source peut être NetworkManager dispatcher,
VPN, script de confidentialité, un service systemd ou configuration
globale de resolved.

## Diagnostic non mutateur (workstation)

```bash
nmcli -g GENERAL.CONNECTION device show eno1
nmcli -g IP4.DNS device show eno1
resolvectl dns eno1
resolvectl domain eno1

systemctl --user list-timers --all hide-location.timer
systemctl --user show hide-location.service \
  -p ActiveState -p UnitFileState -p ExecMainStartTimestamp
journalctl --user -u hide-location.service \
  --since '2026-10-27 21:20:00' --until '2026-10-27 21:35:00' \
  --no-pager -o short-iso

dig +short @172.17.0.1 defectdojo.int.albandrieu.com A
getent ahostsv4 defectdojo.int.albandrieu.com
```

Aucun des relevés ci-dessus ne prouve à lui seul quel processus
a appelé `resolvectl dns`. Vérifier l'éventuel contournement
Chrome (Secure DNS / DoH) seulement **après** la restauration de
`getent`. Un résolveur Chrome public distinct peut encore afficher
NXDOMAIN lorsque le système Linux fonctionne.

## Correctifs déclaratifs proposés dans cette PR

1. `templates/hide-location.sh-Ubuntu.j2` refuse de remplacer les DNS
   d'un lien appartenant au LAN : soit NetworkManager indique
   `172.17.0.1`, soit le lien possède le domaine
   `int.albandrieu.com` / `~int.albandrieu.com`. La recherche du
   DNS d'origine est désormais limitée **à la bonne interface** ;
   aucune modification de `/etc/resolv.conf`. Les interfaces hors LAN
   conservent le comportement de confidentialité historique.
2. `tasks/network_split_dns.yml` reste opt-in via
   `workstation_split_dns_enabled: false` par défaut.
   Une fois activé, il ajoute le domaine de routage
   `~int.albandrieu.com` sans effacer les autres domaines, puis
   réapplique le profil NetworkManager **même s'il est déjà correct**
   mais que le DNS effectif dans `systemd-resolved` a dérivé.
   Il vérifie après application l'absence de Quad9 sur `eno1`.
3. `tests/test_homelab_dns_guard_contract.py` simule les commandes
   `nmcli`, `resolvectl` et `sudo` avec des fixtures locales. Aucun
   test ne contacte de réseau ni ne change la configuration du poste.

Le code versionné n'a **aucun effet sur la workstation** avant
un déploiement Ansible explicitement approuvé.

## Réception locale avant toute mutation

```bash
cd /workspace/users/albandrieu30/ansible-workstation

python3 -m unittest discover -s tests \
  -p 'test_homelab_dns_guard_contract.py' -v

# Pour inspecter les seules tâches tagguées « dns », si Ansible est installé :
.venv/bin/ansible-playbook playbooks/workstation.yml \
  --list-tasks --tags dns -e workstation_split_dns_enabled=true
```

Le mode de mise en œuvre Ansible est **opt-in** et ne doit être lancé
qu'après revue de la liste de tâches, de la configuration effective de
`hide-location` et de la possibilité de retour arrière. Une
réapplication du device par `nmcli device reapply eno1` est moins
intrusive qu'une reconnexion, mais peut modifier brièvement les DNS et
ne neutralise pas un autre processus qui réécrit le lien.

**Gate DONE** : `resolvectl dns eno1` reste égal à `172.17.0.1`
après exécution éventuelle des timers et après réinitialisation
contrôlée de la session réseau ; `getent` retourne `172.17.0.24` ;
`curl` HTTPS sans `--resolve` vérifie le certificat ;
Chrome ouvre le dashboard, et l'authentification réelle est validée.
Conserver les DNS privés hors des DNS publics.
