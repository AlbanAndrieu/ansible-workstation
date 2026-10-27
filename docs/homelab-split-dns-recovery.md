# LAN split-DNS sur la workstation — reprise du 27 octobre 2026

**Diagnostic d'exploitation et runbook consommateur :**
[nabla-compose / docs/runbooks/workstation-split-dns-recovery.md](https://github.com/AlbanAndrieu/nabla-compose/blob/fix/nexus-wan-haproxy-acl-evidence-20261027/docs/runbooks/workstation-split-dns-recovery.md),
[PR Compose #289](https://github.com/AlbanAndrieu/nabla-compose/pull/289).
Responsabilités : **ansible-workstation** gère la persistance de
NetworkManager et des unités systemd ; **nabla-compose** fournit les
recettes Just et le diagnostic des réponses DNS (UDP/TCP pfSense,
`systemd-resolved`, NSS et services HTTPS). Lancer les recettes
Just depuis le checkout nabla-compose, pas depuis ce worktree.
Le 27/10, `nmcli device reapply eno1` a fonctionné, mais
`dig @172.17.0.1` UDP a expiré alors que `resolvectl query`
a répondu en 11,5 s : le diagnostic pfSense DNS/transport
est **distinct** du précédent override Quad9.



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

## Cause racine définitivement attestée par les logs système

**Preuve opérateur du 27 octobre à 21:48 CET** : le journal
`journalctl --user -u hide-location.service` montre une suite
d'exécutions du service. Les écritures sont journalisées par
`sudo` avec la commande exacte
`/usr/bin/resolvectl dns eno1 9.9.9.9 149.112.112.112`
notamment à 21:21:00, 21:22:07, 21:24:07, 21:25:36,
21:27:01, 21:28:07, 21:29:52, 21:31:07, 21:33:05 et 21:34:07
(CET). Le timer apparaît activé jusqu'à 21:48:39. Ce sont
des **écritures DNS effectivement exécutées**, plus seulement
la présence du hook. L'ancienne inférence `sets_quad9=False`
ne peut pas réfuter les appels `sudo` enregistrés :
ce contrôle statique de l'ancien diagnostic était incomplet
pour identifier les paramètres du script déployé.

**Reprise autorisée par l'opérateur :** désactiver à la fois
l'unité et son timer, puis restaurer la configuration DNS du
LAN. L'ancienne unité `hide-location.service` est `oneshot` ;
`inactive` ne prouve pas qu'elle ne s'exécute plus, car le
timer peut la réactiver.

```bash
# Sur la workstation, opération explicite de désactivation :
systemctl --user disable --now \
  hide-location.timer hide-location.service

# Ne doit plus afficher le timer comme actif.
systemctl --user is-enabled hide-location.timer
systemctl --user is-enabled hide-location.service
systemctl --user list-timers --all hide-location.timer

sudo resolvectl dns eno1 172.17.0.1
sudo resolvectl domain eno1 '~int.albandrieu.com'
sudo resolvectl flush-caches

resolvectl dns eno1
resolvectl domain eno1
resolvectl query defectdojo.int.albandrieu.com
getent ahostsv4 defectdojo.int.albandrieu.com
```

La commande d'interface `resolvectl domain` doit recevoir
**`~int.albandrieu.com` sans antislash devant le tilde**.
Le succès de `resolvectl dns` seul ne prouve pas la
résolution NSS ou DNS Chrome. Si `resolvectl query` échoue
toujours, vérifier `resolvectl status`; si `resolvectl query`
réussit mais `getent` échoue, contrôler séparément
`/etc/nsswitch.conf` et la cible `/etc/resolv.conf`.
Si `getent` fonctionne mais Chrome reste en `NXDOMAIN`,
contrôler Chrome Secure DNS / DoH et vider son cache DNS.

**Code Ansible corrigé en complément :** nouveau défaut
`workstation_hide_location_dns_override_enabled: false`.
Lorsque le rôle est exécuté avec `macchanger_enabled`,
les tâches de gestion de service arrêtent/désactivent
**les deux unités** sauf si l'opérateur choisit explicitement
`workstation_hide_location_dns_override_enabled=true`.
Les templates historiques restent présents pour inspection
ou usage hors LAN opt-in.

**Tests :** l'opérateur avait validé les **6/6** tests
`test_homelab_dns_guard_contract.py` sur le commit initial
`1b0b5dd`. Depuis, un septième test de désactivation
par défaut a été ajouté : les tests du HEAD actuel
restent à rejouer. Aucun redéploiement TrueNAS nécessaire.

## Réception du 27 octobre — DNS restauré, DefectDojo accessible depuis Chrome

L'opérateur a désactivé les deux unités utilisateur avec
`systemctl --user disable --now hide-location.timer hide-location.service`.
Leurs statuts `is-enabled` retournent `disabled` et
`list-timers --all hide-location.timer` retourne **0 timers**.
Le message systemd concernant le timer « still active » apparaît
durant la désactivation simultanée ; le résultat final confirme
qu'aucun timer n'est resté programmé.

Après restauration de l'état DNS actif par `resolvectl` :

- `resolvectl dns eno1` = `172.17.0.1` ;
- `resolvectl domain eno1` = `~int.albandrieu.com` ;
- `resolvectl query` et `getent ahostsv4` retournent
  `172.17.0.24` ;
- `just defectdojo-workstation-dns-check` : **PASS** sur DNS,
  HTTPS 302, certificat TLS et redirection même origine ;
- l'opérateur a confirmé **DefectDojo opérationnel dans Chrome** ;
- `tests/test_homelab_dns_guard_contract.py` : **7/7 PASS**
  sur la PR à HEAD `d17154e` au moment de la validation.

**Persistance :** la désactivation `systemctl --user disable` est
enregistrée dans l'état d'activation systemd utilisateur, mais les
commandes `sudo resolvectl dns/domain` n'écrivent **pas** dans
un profil NetworkManager. La source permanente doit être le profil
NetworkManager associé à `eno1`, nommé `Wired eno1` dans la preuve.

Le lien `/etc/resolv.conf` pointe vers
`/run/systemd/resolve/stub-resolv.conf`. Les fichiers
`/etc/resolvconf/resolv.conf.d/head` et `base` montrent des
commentaires de configuration ancienne, mais ne définissent pas
le DNS effectif de `eno1`. Ne pas les modifier pour résoudre
ce problème de split-DNS.

### Réception de la persistance du profil (workstation)

```bash
# Observer la configuration enregistrée, sans modification.
nmcli -f ipv4.dns,ipv4.ignore-auto-dns,ipv4.dns-search \
  connection show 'Wired eno1'

# Uniquement si ~int.albandrieu.com est absent :
sudo nmcli connection modify 'Wired eno1' \
  +ipv4.dns-search '~int.albandrieu.com'

# Recharger le profil sur le device actif sans reconnecter la liaison :
sudo nmcli device reapply eno1

nmcli -f ipv4.dns,ipv4.ignore-auto-dns,ipv4.dns-search \
  connection show 'Wired eno1'
resolvectl dns eno1
resolvectl domain eno1
getent ahostsv4 defectdojo.int.albandrieu.com
```

NetworkManager conserve ces propriétés dans le profil de connexion
(généralement sous `/etc/NetworkManager/system-connections/` avec des
permissions restreintes). Le préfixe `~` indique un **domaine de
routage uniquement** : il n'est pas ajouté comme suffixe aux noms
non qualifiés. `+ipv4.dns-search` ajoute le domaine privé sans
effacer d'autres domaines existants.

Le DNS `172.17.0.1` et `ignore-auto-dns=yes` étaient déjà
confirmés dans le profil NetworkManager ; leur réécriture n'est
pas nécessaire ici. L'Ansible `tasks/network_split_dns.yml`
propose la même réconciliation, mais son activation reste opt-in.

**Point à surveiller séparément :** la résolution de ce FQDN par
`resolvectl query` a pris 22,4659 s, puis 10,7058 s dans les
preuves opérateur malgré une réponse correcte. Cela ne bloque pas
la réception fonctionnelle, mais exige une comparaison de la
latence DNS directe pfSense vs `systemd-resolved` avant de
conclure à une autre panne :

```bash
dig +time=3 +tries=1 @172.17.0.1 \
  defectdojo.int.albandrieu.com A +stats
time resolvectl query -4 defectdojo.int.albandrieu.com
```

**DONE actuel :** service web accessible dans Chrome, TLS vérifié,
conflit `hide-location` désactivé et 7/7 tests PASS.
**À vérifier :** route `~int.albandrieu.com` enregistrée dans
NetworkManager, reapply, maintien après redémarrage, temps de
résolution, parité des secrets Django/runtime/Vaultwarden.

## Régression NSS indépendante (27 octobre)

Le split-DNS NetworkManager `Wired eno1` reste
`MATCH / PERSISTED` et Unbound pfSense UDP/TCP
`A_CONFIRMED`. La résolution via `resolvectl query -4`
a répondu en **0,149 s**, tandis que `getent ahostsv4`
a pris **25,030 s sans sortie** ; le contrôle automatisé
précédent avait confirmé A, mais en **12,4 s**.
Ces preuves distinguent une latence **glibc/NSS**
de la précédente écriture Quad9 par `hide-location`.

**Propriétaire du diagnostic :** nabla-compose,
[runbook NSS / split-DNS](https://github.com/AlbanAndrieu/nabla-compose/blob/fix/nexus-wan-haproxy-acl-evidence-20261027/docs/runbooks/workstation-split-dns-recovery.md)
et [PR #289](https://github.com/AlbanAndrieu/nabla-compose/pull/289).
Lancer sur la workstation, depuis `~/w/nabla-compose` :

```bash
just workstation-nss-path-test
just workstation-nss-path
```

L'outil teste en lecture seule cinq chemins :
`resolvectl -4`, stub UDP `127.0.0.53`,
`getent -s hosts:dns`, `getent -s hosts:resolve`
(module optionnel) et `getent` normal.
**Aucune mutation de `/etc/nsswitch.conf` ou installation
de nss-resolve n'est approuvée à ce stade**. Si la source
de la latence est identifiée, préparer un correctif
déclaratif réversible dans ce dépôt Ansible et ses tests,
sans remplacer à l'aveugle `hosts:` ou l'état systemd.

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
