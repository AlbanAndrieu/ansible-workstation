# Architecture DNS du homelab — split-DNS, DNSSEC et NetworkManager Dispatcher

**État documenté : 28 octobre 2026.**  
**Propriétaire de la configuration :** [ansible-workstation, PR #15](https://github.com/AlbanAndrieu/ansible-workstation/pull/15).  
**Propriétaire des contrôles et des preuves :** [nabla-compose, PR #289](https://github.com/AlbanAndrieu/nabla-compose/pull/289).  
**Périmètre :** workstation Linux sur le LAN, interface \`eno1\`. Ne pas généraliser la configuration à d'autres hôtes ou interfaces.

## 1. Objectif et état réel

Le but du *split-DNS* est de résoudre les noms privés en \`*.int.albandrieu.com\` à partir du LAN, avec le résolveur pfSense/Unbound \`172.17.0.1\`, sans désactiver la validation DNSSEC des noms publics.

**Réception réelle :**

| Contrôle | État | Preuve |
| --- | --- | --- |
| Profil NetworkManager \`Wired eno1\` et DNS pfSense | **PASS** | \`lan_profile=MATCH\` |
| Dispatcher installé, fichier exécutable sécurisé | **PASS** | \`dispatcher=ROOT_EXECUTABLE\` |
| NTA DNSSEC privée sur \`eno1\` uniquement | **PASS** | \`link_nta=EXPECTED_ONLY\` |
| Résolution privée DefectDojo | **PASS** | \`private_dns=PASS\`, \`172.17.0.24\` |
| Validation DNSSEC publique sur \`cloudflare.com\` | **PASS** | \`public_dnssec=AUTHENTICATED\` |
| Restauration de NTA sur événement \`reapply\` | **PASS** | \`nta_restored_by_event=PASS\`, \`diagnosis=PASS_REAPPLY_PERSISTENCE\` |
| Restauration après démarrage complet du poste | **À confirmer** | Test read-only au prochain reboot planifié |

Le **dernier contrôle read-only fourni** a retourné les cinq premiers états PASS. Il ne contient **aucune nouvelle preuve de reboot**. Ne pas confondre une NTA persistée *par mécanisme* (script installé) avec une persistance *après démarrage* déjà observée.

## 2. Architecture et chemins de résolution

\`\`\`mermaid
flowchart TD
    A["Applications LAN : navigateur, curl, getent"] --> B["NSS / systemd-resolved<br/>stub 127.0.0.53 selon le chemin client"]
    B --> C{"Nom DNS à résoudre"}
    C -->|"*.int.albandrieu.com"| D["Règle de routage ~int.albandrieu.com<br/>sur eno1"]
    D --> E["pfSense / Unbound<br/>172.17.0.1"]
    E --> F["Réponse privée : exemple<br/>defectdojo.int.albandrieu.com → 172.17.0.24"]
    C -->|"Nom public : cloudflare.com"| G["Sélection du résolveur selon<br/>DefaultRoute et les autres liens"]
    G --> H["Résolution publique et<br/>validation DNSSEC"]
    D -.-> I["NTA par lien pour<br/>int.albandrieu.com"]
    I -.->|"Exempte uniquement cette zone<br/>de la validation DNSSEC"| B
    J["NetworkManager<br/>Wired eno1"] -->|"up / dhcp4-change / reapply"| K["Dispatcher Nabla<br/>/etc/NetworkManager/dispatcher.d/"]
    K -->|"Après contrôles LAN"| I
\`\`\`

**Attention à la portée du routage :** \`~int.albandrieu.com\` est un *domaine de routage*, et non un suffixe de recherche ordinaire. Il privilégie le serveur DNS configuré sur ce lien pour les noms de cette zone. Il ne garantit **pas à lui seul** qu'un nom public utilisera un résolveur extérieur : cela dépend des autres liens et de \`DNSDefaultRoute\`. Le rôle Ansible configure également pfSense comme **seul DNS IPv4 de ce profil NetworkManager**. Vérifier \`resolvectl status eno1\` avant d'affirmer un chemin de résolution public.

| Élément | Valeur connue | Rôle |
| --- | --- | --- |
| Workstation | \`172.17.0.57\` | Client LAN |
| Interface | \`eno1\` | Lien géré par NetworkManager |
| Profil | \`Wired eno1\` | Profil autorisé par le dispatcher |
| DNS LAN | \`172.17.0.1\` | pfSense/Unbound |
| Domaine route-only | \`~int.albandrieu.com\` | Oriente les requêtes privées vers le lien |
| Domaine NTA | \`int.albandrieu.com\` | Exempt la zone privée de validation DNSSEC sur ce lien |
| Service d'exemple | \`defectdojo.int.albandrieu.com\` | Résolution attendue \`172.17.0.24\` (TrueNAS) |
| Domaine de contrôle public | \`cloudflare.com\` | Doit rester **DNSSEC authentifié** |

Le domaine routé \`~int.albandrieu.com\` et le domaine NTA \`int.albandrieu.com\` sont **deux paramètres distincts**. Le premier sélectionne le résolveur ; le second contrôle la validation cryptographique.

## 3. Pourquoi une Negative Trust Anchor (NTA) ?

Sur la workstation, deux mesures répétées avaient montré :

- Requête \`resolvectl query -4 defectdojo.int.albandrieu.com\` avec validation normale : **TIMEOUT** (4 secondes, deux fois).
- Même nom avec \`resolvectl query --validate=no\` : \`172.17.0.24\` immédiatement.
- Les signatures \`RRSIG\` et le bit \`AD\` avaient été observés depuis pfSense pour des noms publics signés ; un domaine DNSSEC volontairement invalide recevait \`SERVFAIL\`.

**Interprétation opérationnelle :** la validation DNSSEC du sous-arbre privé provoquait le blocage reproduit. Une zone interne non signée sous un domaine public est une explication plausible ; les sorties disponibles **ne prouvent pas directement** l'absence de toutes les signatures de cette zone.

La solution retenue utilise :

\`\`\`bash
resolvectl nta eno1
# Link 2 (eno1): int.albandrieu.com
\`\`\`

Une *Negative Trust Anchor* évite la validation DNSSEC **pour cette zone privée sur ce lien**. Elle ne rend pas le réseau privé cryptographiquement authentifié et **ne remplace pas TLS**. En revanche, elle laisse la validation DNSSEC des autres noms en place. Les sorties reçues confirment \`Data is authenticated: yes\` pour \`cloudflare.com\`.

**Ne pas remplacer cette correction** par \`DNSSEC=no\` global, une réécriture de \`/etc/resolv.conf\`, une désactivation de DoT ou la suppression d'ancres DNSSEC publiques.

## 4. Dispatcher NetworkManager : fonctionnement exact

**Fichier installé sur la workstation :**

\`\`\`text
/etc/NetworkManager/dispatcher.d/90-nabla-private-dnssec-nta
\`\`\`

**Source versionnée :** \`files/networkmanager-homelab-nta-dispatcher.sh\` dans \`ansible-workstation\`.  
**Installation Ansible :** \`tasks/network_dnssec_nta_dispatcher.yml\`, permissions **root:root / 0700**.

NetworkManager lance les scripts exécutables du répertoire \`dispatcher.d\` lorsqu'un événement survient. Il fournit le nom de l'interface, l'action et notamment \`CONNECTION_ID\`. Notre script ne tourne pas en boucle et **n'est pas un nouveau résolveur DNS**.

Le script est *fail-closed* : il refuse une mutation en dehors du lien \`eno1\` ; pour appliquer l'ancre, il exige \`Wired eno1\`, DNS effectif \`172.17.0.1\`, domaine \`~int.albandrieu.com\`, et aucune NTA tierce. Il utilise \`/usr/bin/resolvectl nta eno1\`, sans modifier DNSSEC global ni redémarrer NetworkManager.

| Événement | Comportement du script |
| --- | --- |
| \`up\` | Ajoute la seule NTA privée si le profil, le DNS et le routage concordent |
| \`dhcp4-change\` | Même contrôle ; remet la NTA si elle a disparu au renouvellement |
| \`reapply\` | Même contrôle ; test **PASS** après \`nmcli device reapply eno1\` |
| \`down\` | Efface la NTA **uniquement** si elle est exactement \`int.albandrieu.com\` |
| \`up/reapply\` avec un autre profil, DNS ou domaine | Retire l'ancre privée **si elle est seule**, afin de ne pas l'étendre à un autre réseau |
| Une autre interface ou une action non prévue | N'effectue aucune mutation |
| NTA contenant un autre domaine | Préserve la liste ; ne l'écrase pas |

**Limite importante :** un \`down\` propre n'est pas garanti lors d'une coupure réseau brutale. La sûreté repose aussi sur le contrôle de profil/DNS à la prochaine activation du lien. Il n'est pas démontré que toutes les transitions réseau ou VPN possibles ont été testées réellement.

## 5. GitOps : dépôt responsable et déploiement

### \`ansible-workstation\` : état désiré et persistance

- \`defaults/main.yml\` : variables, avec \`workstation_split_dns_enabled: false\` et \`workstation_split_dns_nta_dispatcher_enabled: false\` par défaut.
- \`tasks/network_split_dns.yml\` : valide le lien, lit les paramètres NetworkManager, fixe si nécessaire le DNS \`172.17.0.1\`, ajoute le domaine \`~int.albandrieu.com\` **sans écraser les autres domaines**, puis réapplique le profil en cas de dérive.
- \`tasks/network_dnssec_nta_dispatcher.yml\` : installe/retire le dispatcher **sur opt-in seulement**.
- \`playbooks/homelab-dns.yml\` : point d'entrée ciblé, qui importe les seules tâches DNS ; il ne lance pas le rôle workstation complet.
- \`tests/test_homelab_dns_guard_contract.py\` et \`tests/test_homelab_dns_nta_dispatcher.py\` : garde hors ligne.
- \`scripts/check_homelab_dns_gate.py\` : refuse zéro test découvert et zéro tâche Ansible.

Le fichier facultatif \`/etc/dnssec-trust-anchors.d/90-nabla-int-albandrieu.negative\` appartient à une **alternative non choisie** : son exception s'appliquerait au domaine sur **toutes les interfaces** du poste, y compris un VPN. Conserver \`workstation_split_dns_persistent_nta_enabled=false\` et \`workstation_split_dns_persistent_nta_remove_enabled=false\`.

**Installation déjà effectuée**, avec le playbook ciblé et cinq variables d'opt-in :

\`\`\`bash
ansible-playbook -i 'localhost,' playbooks/homelab-dns.yml \
  --tags dns \
  -e workstation_split_dns_enabled=true \
  -e workstation_split_dns_nta_dispatcher_enabled=true \
  -e workstation_split_dns_nta_dispatcher_remove_enabled=false \
  -e workstation_split_dns_persistent_nta_enabled=false \
  -e workstation_split_dns_persistent_nta_remove_enabled=false
\`\`\`

Preuve opérateur : **ok=12, changed=1, failed=0, skipped=9**, création du dispatcher confirmée, pas d'autre modification déclarée dans la réception. La commande ci-dessus **écrit réellement sur l'hôte** ; ne pas la relancer pour vérifier l'état. Utiliser les contrôles read-only ci-dessous.

### \`nabla-compose\` : diagnostics, acceptation et historique

| Recette Just | Effet |
| --- | --- |
| \`just workstation-dnssec-dispatcher-test\` | Tests hors ligne du smoke dispatcher (**17/17 PASS**) |
| \`just workstation-dnssec-dispatcher-check\` | Contrôle **read-only** du profil, du fichier, de la NTA, du DNS privé et de DNSSEC public |
| \`just workstation-dnssec-dispatcher-exercise\` | **Mutateur** : retire brièvement la seule NTA privée, lance \`nmcli device reapply eno1\`, mesure sa restauration et tente un rollback borné sur échec |
| \`just workstation-nss-path\` | Diagnostic séparé de performance NSS, sans changer la configuration |

## 6. Validation standard et critères d'acceptation

### Contrôle quotidien ou après redémarrage — lecture seule

Depuis **\`~/w/nabla-compose\`** :

\`\`\`bash
just workstation-dnssec-dispatcher-check

# Contrôles manuels facultatifs :
nmcli -g GENERAL.CONNECTION device show eno1
resolvectl dns eno1
resolvectl domain eno1
resolvectl nta eno1
resolvectl query -4 defectdojo.int.albandrieu.com
resolvectl query -4 cloudflare.com
getent ahostsv4 defectdojo.int.albandrieu.com
\`\`\`

Une sortie de réception conforme contient :

\`\`\`text
PRIVATE_NTA_DISPATCHER_ACCEPTANCE v1
  lan_profile=MATCH
  dispatcher=ROOT_EXECUTABLE
  link_nta=EXPECTED_ONLY
  private_dns=PASS
  public_dnssec=AUTHENTICATED
  mode=READ_ONLY
\`\`\`

- \`lan_profile=MATCH\` : profil \`Wired eno1\`, DNS du lien \`172.17.0.1\`, routage \`~int.albandrieu.com\`.
- \`dispatcher=ROOT_EXECUTABLE\` : fichier régulier, root:root, exécutable par root et inaccessible au groupe/aux autres.
- \`link_nta=EXPECTED_ONLY\` : le lien possède uniquement \`int.albandrieu.com\` comme NTA.
- \`private_dns=PASS\` : la requête IPv4 de DefectDojo renvoie l'adresse attendue \`172.17.0.24\`.
- \`public_dnssec=AUTHENTICATED\` : \`resolvectl query -4 cloudflare.com\` a confirmé la validation DNSSEC de **ce domaine testé**, et non de tous les domaines publics.
- \`mode=READ_ONLY\` : la sonde ne modifie aucune configuration.

### Contrôle de l'événement — déjà exécuté, ne pas rejouer sans nécessité

La réception active a temporairement effacé la seule NTA privée, puis déclenché \`reapply\`. Elle a rendu :

\`\`\`text
private_nta_temporarily_cleared=true
nm_reapply=PASS
nta_restored_by_event=PASS
private_dns=PASS
public_dnssec=AUTHENTICATED
diagnosis=PASS_REAPPLY_PERSISTENCE
\`\`\`

Le retour à l'état attendu a été confirmé par deux contrôles read-only supplémentaires. Ce résultat prouve **la réapplication automatique sur cet événement**, pas encore un redémarrage complet.

### Gate encore ouverte : le prochain redémarrage planifié

Ne pas forcer un reboot pour cette seule preuve. Après un redémarrage normal, lancer \`just workstation-dnssec-dispatcher-check\` **sans** \`--exercise\` et vérifier les cinq états. Si le poste a démarré sans action de réparation manuelle, cette preuve permettra de clôturer la persistance post-reboot.

## 7. Diagnostic d'un échec

| Symptôme | Vérification non mutatrice | Interprétation / suite |
| --- | --- | --- |
| \`lan_profile=UNVERIFIED\` | \`nmcli device status\`, \`resolvectl dns eno1\`, \`resolvectl domain eno1\` | Profil, DNS ou domaine inattendu : ne pas imposer une NTA sur ce lien |
| \`dispatcher=NOT_VERIFIED\` | \`sudo stat -c '%U:%G %a %n' /etc/NetworkManager/dispatcher.d/90-nabla-private-dnssec-nta\` | Vérifier installation et droits root:root / 700 avant tout déploiement ciblé |
| \`link_nta=OTHER_OR_MISSING\` | \`resolvectl nta eno1\` | Distinguer NTA absente et NTA étrangère ; ne jamais vider aveuglément la liste |
| DNS privé échoue malgré la NTA attendue | \`dig @172.17.0.1 defectdojo.int.albandrieu.com A\` puis \`resolvectl query -4 ...\` | Isoler Unbound, transport UDP/TCP, systemd-resolved et NSS séparément |
| DNS public non authentifié | \`resolvectl query -4 cloudflare.com\` et \`journalctl -u systemd-resolved --since '-15 min' --no-pager\` | Ne pas « réparer » le public en désactivant DNSSEC ; ouvrir un diagnostic distinct |
| Le dispatcher ne réinstalle pas la NTA | \`journalctl -u NetworkManager-dispatcher -u NetworkManager --since '-15 min' --no-pager\` | Vérifier l'événement \`reapply\`, \`CONNECTION_ID\` et le chemin du script |
| \`getent\` reste lent mais \`resolvectl\` rapide | \`just workstation-nss-path\` dans Compose | Piste glibc/NSS distincte ; ne pas changer \`/etc/nsswitch.conf\` sans preuve |

**Signaux encore ouverts :** l'ancienne mesure \`nss_default=A_CONFIRMED (4,8s)\` et les messages DNSSEC publics \`no-signature\` dans les anciens journaux. La réussite des sondes présentes ne prouve pas leur résolution générale.

## 8. Retour arrière et règles de sécurité

**Effets d'une suppression :** sans la NTA, le DNS privé peut redevenir lent ou expirer. Prévoir une session locale et une méthode de retour arrière avant toute désinstallation ; ne pas utiliser la désactivation globale DNSSEC pour compenser.

Pour retirer **uniquement le dispatcher installé**, utiliser le playbook DNS ciblé du dépôt Ansible avec l'option de retrait explicite :

\`\`\`bash
# MUTATEUR : seulement dans ansible-workstation / worktree de la PR.
ansible-playbook -i 'localhost,' playbooks/homelab-dns.yml \
  --tags dns \
  -e workstation_split_dns_enabled=true \
  -e workstation_split_dns_nta_dispatcher_enabled=false \
  -e workstation_split_dns_nta_dispatcher_remove_enabled=true \
  -e workstation_split_dns_persistent_nta_enabled=false \
  -e workstation_split_dns_persistent_nta_remove_enabled=false
\`\`\`

Cette opération supprime le **fichier du dispatcher**. Elle ne garantit pas de retirer la NTA déjà présente en mémoire. Pour retirer explicitement **uniquement** la NTA attendue (si elle est toujours seule, et seulement si la perte du DNS privé est acceptable), la recette séparée Compose est \`just workstation-dnssec-nta-rollback\`. Elle refuse des NTA supplémentaires. Pour rétablir le comportement voulu, réinstaller le dispatcher Ansible et revérifier le lien.

**À ne pas faire :** \`resolvectl revert eno1\` (supprime aussi d'autres réglages DNS du lien), \`DNSSEC=no\` global, édition directe de \`/etc/resolv.conf\`, modification pfSense/Unbound sans diagnostic, \`direnv allow\` sur un \`.envrc\` non inspecté, ou lancement du rôle workstation complet pour ce correctif.

## 9. Références

**Code / documents internes :**

- [Runbook de réception Ansible](homelab-split-dns-recovery.md) — preuves datées et étapes de dépannage.
- [Diagnostic et roadmap Compose](https://github.com/AlbanAndrieu/nabla-compose/blob/fix/nexus-wan-haproxy-acl-evidence-20261027/docs/runbooks/workstation-split-dns-recovery.md).
- [Source dispatcher](../files/networkmanager-homelab-nta-dispatcher.sh), [tâches d'installation](../tasks/network_dnssec_nta_dispatcher.yml), [playbook DNS-only](../playbooks/homelab-dns.yml).

**Documentation éditeur :**

- [NetworkManager-dispatcher : événements, chemin et variables](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/NetworkManager-dispatcher.html).
- [systemd resolvectl : commandes dns, domain, nta](https://www.freedesktop.org/software/systemd/man/latest/resolvectl.html).
- [systemd-resolved : routage des requêtes DNS](https://www.freedesktop.org/software/systemd/man/latest/systemd-resolved.service.html).

**Séparation des responsabilités :** la documentation architecturale et la persistance sont gérées dans **ansible-workstation** ; les diagnostics de production, les preuves runtime et les recettes Just appartiennent à **nabla-compose**.
