# LAN split-DNS sur la workstation — reprise du 27 octobre 2026

## Réception NetworkManager reapply — 28 octobre : événement confirmé

**Preuve opérateur après installation du dispatcher :**

- `just workstation-dnssec-dispatcher-test` :
  **17/17 tests PASS** (0,016 s) ;
- `just workstation-dnssec-dispatcher-check` :
  `lan_profile=MATCH`,
  `dispatcher=ROOT_EXECUTABLE`,
  `link_nta=EXPECTED_ONLY`,
  `private_dns=PASS`,
  `public_dnssec=AUTHENTICATED` ;
- `just workstation-dnssec-dispatcher-exercise` :
  **NTA privée initiale effacée temporairement et
  suppression attestée** ;
  `nm_reapply=PASS`,
  **`nta_restored_by_event=PASS`**,
  `private_dns=PASS`,
  `public_dnssec=AUTHENTICATED`,
  `diagnosis=PASS_REAPPLY_PERSISTENCE` ;
- nouvelle exécution read-only après exercice, puis
  seconde vérification : mêmes contrôles **PASS**.

**Conclusion technique :** l'installation via
`playbooks/homelab-dns.yml` et la restauration par
l'événement NetworkManager `reapply` sont maintenant
**reçues sur le poste réel**, au-delà des contrats
hors ligne. La NTA privée reste limitée au
lien `eno1` : aucun désarmement global DNSSEC.
La validation DNSSEC du domaine public
`cloudflare.com` reste authentifiée.

**P0 restant — persistance après reboot :**
lors du **prochain redémarrage planifié**
(pas de reboot anticipé), exécuter :

```bash
cd ~/w/nabla-compose
just workstation-dnssec-dispatcher-check
```

Attendu : `lan_profile=MATCH`,
`dispatcher=ROOT_EXECUTABLE`,
`link_nta=EXPECTED_ONLY`,
`private_dns=PASS`,
`public_dnssec=AUTHENTICATED`.
Aucune nouvelle exécution `-exercise`
n'est nécessaire pour prouver le boot.
**Ne pas déclarer la persistance post-reboot DONE**
avant cette mesure réelle.

Le `nss_default=A_CONFIRMED (4,8s)` mesuré avant
l'installation et les erreurs historiques
`no-signature` sur d'autres domaines publics
restent des sujets indépendants, non clos
par la NTA privée.



## Réception installation effective — 28 octobre 2026, 00:38 CET

**Preuve opérateur après application ciblée** depuis le worktree
`/tmp/ansible-dns-gate.xLS990` à `d0b93e8` :
le playbook `playbooks/homelab-dns.yml` a terminé avec
`ok=12 changed=1 unreachable=0 failed=0 skipped=9`.
La seule modification rapportée est
`Install LAN-only DNSSEC NTA NetworkManager dispatcher`.
Le test `sudo test -x` confirme l'installation réelle de
`/etc/NetworkManager/dispatcher.d/90-nabla-private-dnssec-nta`.

Après application :

- `resolvectl nta eno1` → `int.albandrieu.com` ;
- `defectdojo.int.albandrieu.com` → `172.17.0.24` en
  **25,3 ms**, réponse privée normalement
  **non authentifiée DNSSEC** ;
- `cloudflare.com` → A publics en **56,2 ms**,
  `Data is authenticated: yes` : validation DNSSEC
  publique confirmée sur ce domaine ;
- warning découverte Python 3.14 sans échec de tâche ;
- `direnv allow` a été exécuté par l'opérateur
  dans le worktree isolé et n'a créé qu'un environnement
  virtuel Python vide. Cet événement n'est pas une
  preuve de dysfonctionnement DNS.

**Statut :** dispatcher **INSTALLÉ ET FONCTIONNEL**
pour la résolution courante, mais la NTA peut encore être
celle de l'application manuelle antérieure. L'exécution
du gestionnaire d'événements NetworkManager n'a pas
encore été démontrée : **persistance après `reapply`
et après reboot `NOT_VERIFIED`**.

### Réception événementielle (sans redémarrage)

La [PR Compose #289](https://github.com/AlbanAndrieu/nabla-compose/pull/289)
contient `scripts/workstation/accept-private-nta-dispatcher.py`
et les recettes Just :

```bash
cd ~/w/nabla-compose
git pull --ff-only

# Contrats offline, aucun changement réseau.
just workstation-dnssec-dispatcher-test

# Confirme NTA / DNS privé / DNSSEC public sans mutation.
just workstation-dnssec-dispatcher-check

# Test explicite de reapply, avec garde et réparation bornée
# si l'événement ne réinstalle pas l'ancre privée.
just workstation-dnssec-dispatcher-exercise

# Vérification après exercice.
just workstation-dnssec-dispatcher-check
```

`workstation-dnssec-dispatcher-exercise` est une **action
réseau réelle**. Elle exige un privilège administrateur,
un profil `Wired eno1`, le DNS `172.17.0.1`,
le domaine `~int.albandrieu.com`, un dispatcher
root:root exécutable, et une **unique** NTA
`int.albandrieu.com`. Elle retire brièvement
cette seule NTA, utilise `nmcli device reapply eno1`,
puis attend que NetworkManager la recrée.
Si la réapplication échoue et que le LAN est toujours
conforme, elle tente de restaurer **uniquement
la NTA initiale**, sans toucher aux NTA étrangères.
Une brève perturbation DNS est possible ; éviter
de lancer ce test pendant une opération réseau critique.

**Résultats encore attendus :** tests offline du script,
`nta_restored_by_event=PASS`,
`private_dns=PASS`, `public_dnssec=AUTHENTICATED`
et `diagnosis=PASS_REAPPLY_PERSISTENCE`.
Les logs réels ne sont pas encore reçus.
Après un **prochain reboot contrôlé**, relancer
seulement `just workstation-dnssec-dispatcher-check`
pour attester la persistance après démarrage, sans
forcer un reboot pour cette seule preuve.

Référence :
[NetworkManager-dispatcher](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/NetworkManager-dispatcher.html),
[resolvectl NTA](https://www.freedesktop.org/software/systemd/man/latest/resolvectl.html).



## Réception finale du preflight Ansible — 28 octobre 2026

**Exécution réelle opérateur sur le worktree `ansible-workstation` à `d0b93e8` :**

- `test_homelab_dns_gate.py` : **14/14 PASS** ;
- `scripts/check_homelab_dns_gate.py --dry-run` :
  `repository=ansible-workstation (role-root)`,
  garde DNS **8/8 PASS**, dispatcher **17/17 PASS** ;
- `--list-tasks --tags dns` : **PASS**, les trois tâches DNS
  requises sont trouvées ;
- `ansible-playbook --check --diff` : **PASS**, les tâches
  DNS sont exécutées en mode simulation ;
  `localhost: ok=11 changed=1 failed=0 skipped=10`.
  `changed=1` correspond **uniquement à la création prévue**
  de `/etc/NetworkManager/dispatcher.d/90-nabla-private-dnssec-nta`
  (diff `before -> after`, script 43 lignes) ; aucun fichier
  n'a été réellement écrit.
- Avertissement de découverte Python
  `/home/albandrieu/.linuxbrew/bin/python3.14` : non bloquant
  dans cette exécution ; pas de migration de Python à faire
  dans ce chantier.

**Décision :** la gate de qualité locale (39 tests) et le
précontrôle Ansible sont **validés**. Le dispatcher est
**PRÊT pour une application ciblée, mais NON INSTALLÉ**.
L'exception DNSSEC runtime `eno1` reste active d'après
la précédente réception. Aucun reboot ni test de
persistance n'a été réalisé.

### Commande d'application ciblée (action explicite, non lancée)

Uniquement depuis ce worktree déjà synchronisé, après revue
du `--check --diff` et confirmation du profil LAN :

```bash
ansible-playbook -i 'localhost,' playbooks/homelab-dns.yml \
  --tags dns \
  -e workstation_split_dns_enabled=true \
  -e workstation_split_dns_nta_dispatcher_enabled=true \
  -e workstation_split_dns_nta_dispatcher_remove_enabled=false \
  -e workstation_split_dns_persistent_nta_enabled=false \
  -e workstation_split_dns_persistent_nta_remove_enabled=false
```

La commande est **mutatrice** et nécessite l'approbation de
l'opérateur ; elle peut demander le mot de passe sudo.
Elle conserve la politique DNSSEC globale et n'installe
pas de fichier `.negative`. Les tâches de réconciliation
NetworkManager peuvent aussi corriger un *drift*
apparu depuis le `--check` : si le profil DNS a changé,
refaire un preflight avant toute application.

### Acceptance après application (lecture seule)

```bash
test -f /etc/NetworkManager/dispatcher.d/90-nabla-private-dnssec-nta
resolvectl nta eno1
resolvectl dns eno1
resolvectl domain eno1
resolvectl query -4 defectdojo.int.albandrieu.com
resolvectl query -4 cloudflare.com
getent ahostsv4 defectdojo.int.albandrieu.com
```

La validation de la réinstallation automatique de la NTA
sur `reapply`, changement de profil et reboot
reste **à exécuter** ultérieurement, sans forcer de
redémarrage pour cette seule réception.



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

## Correction du point d'entrée Ansible — 28 octobre 2026

**Preuve opérateur sur le worktree exact de la PR à `f71c2f9` :**

- Nouvelle suite `test_homelab_dns_gate.py` : **13/13 PASS**.
- Garde split-DNS `test_homelab_dns_guard_contract.py` :
  **8/8 PASS**.
- Dispatcher `test_homelab_dns_nta_dispatcher.py` :
  **17/17 PASS**.
- La sélection Ansible a échoué avec
  `Could not find specified file in role, its 'tasks/' is not usable`.
  Les 3 marqueurs attendus dans `--list-tasks` sont absents.
  **La gate a donc correctement bloqué le déploiement.**
- `direnv` a signalé que le nouveau worktree contenait un
  `.envrc` non approuvé. C'est un avertissement distinct,
  **pas l'explication de l'erreur Ansible**. Ne pas exécuter
  `direnv allow` automatiquement.

**Cause confirmée dans le code :**
`playbooks/homelab-dns.yml` utilisait
`ansible.builtin.import_role: name: ../`, chemin interprété
comme un rôle introuvable ou inutilisable par Ansible.
Il n'était pas correct de relancer le playbook générique.

**Correction [skip ci] :**

- `playbooks/homelab-dns.yml` utilise désormais
  `ansible.builtin.import_tasks: ../tasks/network_split_dns.yml`
  depuis `playbooks/` et `vars_files: ../defaults/main.yml`.
  Il ne charge aucun installateur général `tasks/workstation.yml`.
- `tasks/network_dnssec_nta_dispatcher.yml` résout le
  fichier `src` via `role_path` ou le parent du
  `playbook_dir`, afin de fonctionner dans le rôle
  complet **et** le playbook DNS ciblé.
- `tests/test_homelab_dns_gate.py` contient désormais
  **14 tests**, dont un contrat sur le chemin du
  dispatcher et le nouvel import. **Ces changements
  ne sont pas encore exécutés sur la workstation.**

### Relancer depuis le worktree Ansible existant

```bash
# Depuis /tmp/ansible-dns-gate.xLS990 ou le worktree
# détaché précédemment créé (pas nabla-compose) :
git fetch origin fix/preserve-homelab-split-dns-20261027
git merge --ff-only origin/fix/preserve-homelab-split-dns-20261027

python3 -m unittest discover -s tests \
  -p 'test_homelab_dns_gate.py' -v

python3 scripts/check_homelab_dns_gate.py --dry-run
```

Le script réexécute automatiquement 8 tests du garde
split-DNS, 17 tests dispatcher, vérifie la sélection
Ansible des tâches DNS et effectue un `--check --diff`
**sans application réelle**.
Si le `--list-tasks` ou le `--check` échoue,
**ne pas passer en mode application**.
La NTA runtime sur `eno1` reste opérationnelle ;
la persistance du dispatcher n'est pas encore appliquée.

## Gate Ansible corrigée — 28 octobre : zéro test / zéro tâche n'est pas PASS

**Dernière preuve opérateur :**
`python3 -m unittest discover -s tests -p test_homelab_dns_guard_contract.py -v`
a renvoyé `Ran 0 tests` ; le playbook général
`playbooks/workstation.yml --list-tasks --tags dns`
ne listait aucune tâche, et `--check` n'exécutait
que `Gathering Facts` (`ok=1`).
**Ces commandes n'ont rien validé**. La cause
exacte du chemin courant n'a pas été mesurée ;
mauvais dépôt, worktree obsolète et filtrage de
tâches sont les premières hypothèses.
Ne pas utiliser ce résultat pour autoriser l'application.

**Correctif versionné :**

- `playbooks/homelab-dns.yml` est un point
  d'entrée Ansible **ciblé** :
  `import_role: name: ../, tasks_from: network_split_dns`,
  `tags: [dns]`, `gather_facts: false`,
  `connection: local`, et
  `when: workstation_split_dns_enabled | bool`.
  Contrairement au playbook workstation générique,
  il n'importe pas l'ensemble du rôle.
- `scripts/check_homelab_dns_gate.py` vérifie d'abord
  la racine du dépôt (origin Ansible attendu) et
  l'existence des fichiers ; exécute les suites
  `test_homelab_dns_guard_contract.py` (minimum 8)
  et `test_homelab_dns_nta_dispatcher.py` (minimum 17)
  en échouant si aucun test n'est découvert ;
  puis exige dans le `--list-tasks` du playbook ciblé
  les marqueurs des tâches DNS et du dispatcher.
  L'option `--dry-run` ajoute une exécution
  `ansible-playbook --check --diff`, sans apply,
  et refuse un succès limité à Gathering Facts.
- `tests/test_homelab_dns_gate.py` :
  **13 tests hors ligne supplémentaires**, à exécuter
  avant de déclarer la nouvelle gate valide.

### Exécution sur la branche exacte, sans écraser le checkout courant

Depuis un checkout existant de `ansible-workstation`,
utiliser un worktree indépendant de la PR (aucun
`git switch` du poste courant) :

```bash
cd /workspace/users/albandrieu30/ansible-workstation
git fetch origin fix/preserve-homelab-split-dns-20261027

WT="$(mktemp -d /tmp/ansible-dns-gate.XXXXXX)"
rmdir "$WT"
git -c submodule.recurse=false worktree add --detach \
  "$WT" origin/fix/preserve-homelab-split-dns-20261027
cd "$WT"

git remote get-url origin
git rev-parse --show-toplevel
git rev-parse --short HEAD

# Interdit zéro tests et zéro tâches DNS :
python3 scripts/check_homelab_dns_gate.py

# Contrôle Ansible sans mutation, seulement APRÈS gate normale :
python3 scripts/check_homelab_dns_gate.py --dry-run
```

Cette entrée est **plus fiable** que les trois
anciennes commandes lorsque l'utilisateur se trouve
dans `nabla-compose` ou dans une ancienne branche
`ansible-workstation` : la vérification du dépôt
et des nombres de tests est bloquante.

**Le paramètre d'opt-in dans la gate est fourni
uniquement via `-e`** pendant le listing et le
dry-run ; `workstation_split_dns_enabled=false`
et `workstation_split_dns_nta_dispatcher_enabled=false`
restent les valeurs du dépôt par défaut.
La NTA globale par fichier `.negative` reste
également désactivée.

**Avant tout déploiement réel :** examiner le
`--check --diff` et refuser toute tâche non DNS,
erreur d'élévation, mutation de sécurité hors NTA,
ou autre profil que `Wired eno1`. Aucune commande
`--apply` n'est encapsulée par la gate.
Si la gate échoue, ne pas interpréter
`changed=0` comme une confirmation de convergence.

## Réception tests dispatcher — 28 octobre 2026 à 00:06 CET

**Preuve exécutée par l'opérateur sur sa workstation :**
`python3 -m unittest discover -s tests -p 'test_homelab_dns_nta_dispatcher.py' -v`
a terminé avec **17 tests / 17 PASS (0,907 s), zéro échec**.

La suite vérifie les événements NetworkManager `up`,
`dhcp4-change`, `reapply`, `down`, la protection
d'`eno1` et du profil `Wired eno1`, l'absence d'écriture
pour un autre DNS ou domaine, la conservation des NTA
tierces, la suppression limitée à l'ancre attendue en cas de
changement de profil/DNS/route, et les paramètres
d'activation/rollback par défaut désactivés.

**Cela atteste les contrats hors ligne, PAS un déploiement
réel du dispatcher**. La NTA `eno1` a été appliquée
manuellement et fonctionne en runtime, mais l'installation
Ansible, la relance automatique et le comportement après
redémarrage restent `NOT_VERIFIED`. La suite précédente
`test_homelab_dns_guard_contract.py` (8 tests, dont l'un
ajouté pour la NTA) n'a pas encore été rejouée sur ce HEAD.
Ne pas la déclarer PASS.

### Prochain gate Ansible en lecture seule

Dans le checkout de **ansible-workstation**, une fois
la branche de PR synchronisée :

```bash
python3 -m unittest discover -s tests \
  -p 'test_homelab_dns_guard_contract.py' -v

ansible-playbook playbooks/workstation.yml \
  --list-tasks --tags dns \
  -e workstation_split_dns_enabled=true \
  -e workstation_split_dns_nta_dispatcher_enabled=true

ansible-playbook playbooks/workstation.yml \
  --check --diff --tags dns \
  -e workstation_split_dns_enabled=true \
  -e workstation_split_dns_nta_dispatcher_enabled=true
```

Ces paramètres sont **éphémères pour la commande**
et ne changent pas les défauts Ansible dans Git.
En `--check`, Ansible doit montrer le plan de création
de `/etc/NetworkManager/dispatcher.d/90-nabla-private-dnssec-nta`,
**sans réellement l'écrire**. Vérifier que le plan ne
crée aucun fichier `.negative` global et qu'aucune
autre tâche destructive n'est sélectionnée.
Ne pas supprimer la NTA runtime qui fonctionne
avant la réception de la persistance.

**Critère DONE restant :** application ciblée et
explicitement autorisée du seul dispatcher, vérification
du profil actif et de l'ancre sur `eno1`, contrôle DNSSEC
privé/public puis confirmation de réapplication sur
renouvellement DHCP, reapply et prochain démarrage.

## Réception 27/10 — NTA privée runtime PASS et persistance LAN par interface

**Preuve opérateur :** `just workstation-dnssec-nta-test` **10/10 PASS**.
Avant application : `nta_state=EMPTY` et requête validée privée
`UNVERIFIED` après 5,0 s. Ensuite l'utilisateur a exécuté
`just workstation-dnssec-nta-try` ; le script a répondu
`runtime_applied=true` puis `validated_private=A_CONFIRMED (0.2s)`.
Une requête DNS normale **sans `--validate=no`** a ensuite confirmé :

- `defectdojo.int.albandrieu.com → 172.17.0.24` en **33,4 ms** ;
- `getent ahostsv4` résout de nouveau le même nom ;
- `cloudflare.com` répond en **43,1 ms**, avec
  `Data is authenticated: yes` : DNSSEC public reste actif
  pour **ce domaine testé** ;
- `just workstation-nss-path` retourne `diagnosis=PASS`,
  mais `nss_default=A_CONFIRMED (4.8s)` :
  la lenteur NSS **n'est pas entièrement résolue**.
  Le module `nss-resolve` forcé reste sans réponse,
  ce qui ne prouve pas sa présence sur le poste.

L'expérience NTA *sur le seul lien eno1* est donc validée.
**Elle n'est pas persistante.** Le fichier `.negative` déjà
préparé est désactivé par défaut et a un périmètre plus large :
toutes les interfaces. Ne pas l'activer automatiquement, notamment
en présence de VPN.

### Persistance recommandée : NetworkManager dispatcher par lien

Préférer l'implémentation **opt-in** ci-dessous à la NTA
`.negative` globale pour préserver l'isolation LAN :

- [files/networkmanager-homelab-nta-dispatcher.sh](../files/networkmanager-homelab-nta-dispatcher.sh)
  — observe uniquement les événements
  `up`, `dhcp4-change` et `reapply` de `eno1`
  avec `CONNECTION_ID=Wired eno1` et confirme
  `DNS 172.17.0.1` et `~int.albandrieu.com`.
  Il applique `resolvectl nta eno1 int.albandrieu.com`
  sans écraser une NTA étrangère et retire uniquement sa NTA
  si le profil ou le DNS privé change. Lors d'un `down`
  propre, il efface uniquement cette NTA **si elle est seule**.
  Il ne modifie ni DNSSEC, ni DoT, ni le résolveur global ;
- [tasks/network_dnssec_nta_dispatcher.yml](../tasks/network_dnssec_nta_dispatcher.yml)
  — install/removal idempotent, fichier root:root mode `0700`,
  sans redémarrer NetworkManager ni `systemd-resolved` ;
- [tests/test_homelab_dns_nta_dispatcher.py](../tests/test_homelab_dns_nta_dispatcher.py)
  — **17 tests hors ligne**, ajoutés mais pas encore
  exécutés sur la workstation.

Les options sont **false par défaut** :

```yaml
workstation_split_dns_enabled: false
workstation_split_dns_nta_dispatcher_enabled: false
workstation_split_dns_nta_dispatcher_remove_enabled: false
workstation_split_dns_persistent_nta_enabled: false
workstation_split_dns_persistent_nta_remove_enabled: false
```

Pour un futur déploiement explicite :
activer `workstation_split_dns_enabled=true` et
`workstation_split_dns_nta_dispatcher_enabled=true`,
laisser toutes les autres variantes NTA désactivées,
limiter les tâches Ansible au tag `dns`.
D'abord inspecter `--list-tasks` puis `--check`.
Une fois l'application autorisée, exécuter
`sudo nmcli device reapply eno1`, vérifier
`resolvectl nta eno1`, la résolution privée
et le DNSSEC public. NetworkManager déclenche
un événement `reapply` au dispatcher ;
[documentation officielle](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/NetworkManager-dispatcher.html).

**Rollback :** configurer
`workstation_split_dns_nta_dispatcher_enabled=false`
et `workstation_split_dns_nta_dispatcher_remove_enabled=true`
sur un passage limité au tag `dns`, puis utiliser
`just workstation-dnssec-nta-rollback` dans nabla-compose
si le runtime contient toujours uniquement
`int.albandrieu.com`. Aucune désactivation globale DNSSEC.

**DONE à confirmer :** installation du dispatcher
par Ansible, réapplication `eno1`, restauration de
la NTA après redémarrage ou réactivation du profil
et maintien DNSSEC public. Ne pas redémarrer
inutilement la workstation : un prochain reboot
contrôlé suffira à la réception finale.

## Résolution DNSSEC de la zone privée — NTA scoped, opt-in (27 octobre)

**Preuve décisive utilisateur :** les **13 tests locaux DNSSEC passent**.
Sur deux cycles : la requête **validée** pour
`defectdojo.int.albandrieu.com` a expiré **4,0 s**,
tandis que `resolvectl query -4 --validate=no`
a immédiatement résolu `172.17.0.24`.
Un domaine public DNSSEC signé a été résolu avec et sans
validation, et Unbound pfSense `172.17.0.1`
a renvoyé `RRSIG=yes, AD=yes` pour des enregistrements
publics signés ; `dnssec-failed.org` a reçu `SERVFAIL`.

**Diagnostic :** le chemin de **validation DNSSEC du sous-arbre
privé `int.albandrieu.com`** est maintenant le défaut
reproduit. L'absence réelle des RRSIG dans la zone privée
n'a pas encore été directement vérifiée ; la cause
architecturale probable est une zone interne non signée
sous le domaine public.

**Règle :** ne pas désactiver `DNSSEC=yes` à l'échelle du
poste et ne pas dégrader DoT ou les autres zones.
Systemd offre des *Negative Trust Anchors* ciblées,
prévues pour les DNS privés non signés :
[per-link `resolvectl nta`](https://www.freedesktop.org/software/systemd/man/latest/resolvectl.html),
[fichier `.negative`](https://www.freedesktop.org/software/systemd/man/latest/dnssec-trust-anchors.d.html).

### 1. Réception d'abord en mode runtime, réversible

Depuis la workstation, dans **nabla-compose** :

```bash
cd ~/w/nabla-compose
git pull --ff-only
just workstation-dnssec-nta-test
just workstation-dnssec-nta-check || true   # TIMEOUT attendu avant correction

# Opération explicite, limitée au lien eno1 et à la zone privée :
just workstation-dnssec-nta-try

# Vérifier désormais une requête VALIDÉE sans --validate=no :
resolvectl query -4 defectdojo.int.albandrieu.com
getent ahostsv4 defectdojo.int.albandrieu.com
resolvectl query -4 cloudflare.com
just workstation-nss-path
```

`recover-split-dns-nta.py` refuse l'opération si le lien
n'est pas `eno1` avec `Wired eno1`, DNS pfSense
`172.17.0.1`, routage `~int.albandrieu.com`,
ou si des ancres NTA supplémentaires seraient remplacées.
**Cette NTA par lien est runtime et n'est pas persistante.**

Revenir en arrière **si la NTA de lien était initialement
vide et qu'aucun autre service n'en a ajouté** :

```bash
cd ~/w/nabla-compose
just workstation-dnssec-nta-rollback
```

La commande de retour en arrière efface uniquement la
liste NTA du lien si elle contient exactement le domaine
attendu ; elle refuse si des domaines supplémentaires sont
déclarés. Elle n'est **pas** une suppression globale de
trust anchors DNSSEC.

### 2. Persistance Ansible facultative après confirmation

Variables dans `defaults/main.yml`, toutes désactivées
par défaut :

```yaml
workstation_split_dns_enabled: false
workstation_split_dns_persistent_nta_enabled: false
workstation_split_dns_persistent_nta_remove_enabled: false
```

Après la preuve **runtime PASS**, l'opérateur peut
explicitement activer le rôle split-DNS et
`workstation_split_dns_persistent_nta_enabled=true`.
Les tâches `network_dnssec_nta.yml` écrivent uniquement
`/etc/dnssec-trust-anchors.d/90-nabla-int-albandrieu.negative`
avec `int.albandrieu.com`.
**Attention :** contrairement à l'essai NTA par lien,
le fichier `.negative` s'applique à ce domaine privé sur
**tous les liens DNS du poste**. Il ne désactive pas
la validation DNSSEC d'autres domaines mais il faut
vérifier que ce périmètre est acceptable (VPN inclus).
Ne pas déployer à l'aveugle si l'utilisateur veut
une portée strictement `eno1`.

Le handler `systemd-resolved` ne redémarre le service
que si le fichier est réellement créé/modifié/supprimé,
à la suite de cet opt-in ; il ne s'exécute pas au
provisionnement courant. Ne pas déclencher le rôle
complet sans revoir ses autres tâches : prévoir
`--tags dns`, `--check` puis une exécution ciblée
hors CI et contrôler le résultat.

Rollback déclaratif explicite : activer
`workstation_split_dns_persistent_nta_remove_enabled=true`
avec `workstation_split_dns_persistent_nta_enabled=false`
(et `workstation_split_dns_enabled=true`) puis
exécuter **uniquement les tâches DNS**. Le rôle supprime
uniquement son fichier `.negative`, préserve les autres
ancres et ne redémarre resolved que si le fichier change.
Mettre les deux flags à `true` est refusé.

La documentation de
[nabla-compose PR #289](https://github.com/AlbanAndrieu/nabla-compose/pull/289)
recueille le diagnostic et la réception ; **le code
Ansible n'a pas été appliqué**, PR toujours Draft.

**Point indépendant à surveiller :** les échecs
`DNSSEC validation failed: no-signature` sur certains
domaines publics sont également visibles dans les
journaux et ne doivent pas être considérés réparés
par cette NTA exclusivement privée.

## Nouvelle preuve DNSSEC (27 octobre vers 23:01 CET)

L'opérateur a transmis le journal de
`systemd-resolved` : **1 141 erreurs
`DNSSEC validation failed: no-signature`**
dans l'extrait, sur de nombreux domaines publics.
Les statistiques cumulées depuis le 24/10
montrent **46 468 verdicts DNSSEC `Bogus`**
et **5 077 timeouts**.
L'interface `eno1` utilise toujours pfSense
`172.17.0.1` et la route privée
`~int.albandrieu.com`, avec
`DNSSEC=yes/supported` et
`DNSOverTLS=opportunistic`.
Ces faits expliquent pourquoi limiter
l'investigation au module NSS est insuffisant ;
ils ne démontrent pas encore si pfSense/Unbound
transmet ou retire les signatures attendues.

**Diagnostic propriétaire Compose :**
[PR #289](https://github.com/AlbanAndrieu/nabla-compose/pull/289)
et [runbook](https://github.com/AlbanAndrieu/nabla-compose/blob/fix/nexus-wan-haproxy-acl-evidence-20261027/docs/runbooks/workstation-split-dns-recovery.md).
Lancer depuis `~/w/nabla-compose` :

```bash
just workstation-dnssec-test
just workstation-dnssec-check
```

Le script compare `resolvectl query` avec
`--validate=no` **sur une seule requête**, et vérifie
les `RRSIG` via `dig +dnssec @172.17.0.1`,
sans écrire ni redémarrer quoi que ce soit.
La suite ajoutée comprend 13 tests
**pas encore exécutés** par l'opérateur.

**Politique Ansible :** ne pas supprimer la protection
DNSSEC globalement par défaut. Une fois les preuves
comparées reçues, corriger au niveau le plus
précis possible (réponse/signatures côté Unbound
ou politique scoped de liaison avec rollback).
Ne pas réactiver `hide-location` ni remplacer
pfSense par un DNS public. Une désactivation
DNSSEC à l'aveugle n'est pas autorisée.

## Mise à jour 22:51 — ne pas appliquer de correctif NSS prématuré

La nouvelle comparaison multi-chemin depuis la workstation
révèle désormais `resolved_native=TIMEOUT (6,0s)`
**en même temps** que `nss_default=TIMEOUT (6,0s)`.
La sonde `stub_udp` v1 retournait
`NO_ANSWER (2,0s)` sans préciser SERVFAIL,
NODATA ou non-réponse ; le module NSS `dns` forcé
a répondu en **3,4 s**. Cela réfute l'hypothèse
d'une panne exclusivement liée à l'ordre `hosts:`.

La source d'autorité de la politique DNS persistante reste
ce dépôt Ansible, mais **aucune modification DNSSEC,
DNS-over-TLS, `/etc/nsswitch.conf` ou module `nss-resolve`
ne doit être appliquée sans preuve**. Le code
[Compose PR #289](https://github.com/AlbanAndrieu/nabla-compose/pull/289)
contient désormais le diagnostic v2 du stub (RCODE) et
des sondes séquentielles :
`just workstation-nss-path-test`,
`just workstation-nss-path-samples`.
Les tests complémentaires v2 sont **à recevoir localement**.

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
