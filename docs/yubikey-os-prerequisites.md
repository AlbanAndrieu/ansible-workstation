# YubiKey sur Ubuntu — prérequis OS avec Ansible, sans PAM ni enrollment

**Propriétaire :** `ansible-workstation` (paquets et services Ubuntu).
**Statut : CODE ADDED / RUNTIME NOT VERIFIED — aucun paquet installé par la PR.**
**Audits/cryptographie matériels :** [nabla-compose](https://github.com/AlbanAndrieu/nabla-compose/tree/master/scripts/workstation), sans copie de ses scripts.

## Pourquoi le bundle historique a été retiré

Le code précédent [`tasks/yubikey.yml` sur `master`](https://github.com/AlbanAndrieu/ansible-workstation/blob/master/tasks/yubikey.yml)
mélangeait :

1. Un PPA `ppa:yubico/stable` ajouté même si `yubikey_enabled` était faux.
   Le champ `state` visible dans la version historique est en outre
   syntaxiquement cassé.
2. Une installation de paquets `libfido2-1`, `libpam-u2f`,
   `pamu2fcfg`, `libykpiv1`, `python3-ykman`,
   `yubikey-manager`, `yubico-piv-tool`, `yubikey-agent`.
3. La **copie de template** de `/etc/pam.d/common-auth` lorsque
   `pam_enabled=true`. L'ancien `defaults/main.yml` déclarait
   `pam_enabled: true`.

Il était donc justifié de **retirer ce bundle du rôle général** :
la copie de `common-auth` risquait de casser sudo ou l'ouverture de
session, et le PPA et certains noms de paquets historiques ne sont pas
appropriés comme base Ubuntu moderne. En revanche, supprimer
**également toute capacité Ansible de provisionner les bibliothèques
et outils du système** allait trop loin. Cette fonction revient ici
sous une forme sûre et indépendante.

**Aucune suppression Git ne désinstalle des paquets déjà présents et
aucune suppression ne restaure un `/etc/pam.d` précédemment modifié.**

## Code réellement réutilisable de nabla-compose

| Source existante dans Compose | Élément utile | Destination/owner |
| --- | --- | --- |
| [`bootstrap-yubikey-manager.sh`](https://github.com/AlbanAndrieu/nabla-compose/blob/master/scripts/workstation/bootstrap-yubikey-manager.sh) | Liste APT Ubuntu : `yubikey-manager pcscd libu2f-udev libpcsclite-dev pkg-config` ; vérification de `/usr/bin/ykman` | Dépendances APT gérées ici ; contrôles CLI spécifiques conservés dans Compose |
| [`inspect-yubikey-dependencies-readonly.py`](https://github.com/AlbanAndrieu/nabla-compose/blob/master/scripts/workstation/inspect-yubikey-dependencies-readonly.py) | Existence de `pcscd` / `scdaemon`, état agent GPG/SSH, outillage de restauration ; sortie expurgée | Diagnostic avancé toujours dans Compose, pas de seconde copie |
| [`docs/workstation-yubikey-full-capabilities.md`](https://github.com/AlbanAndrieu/nabla-compose/blob/master/docs/workstation-yubikey-full-capabilities.md) | PIV / OTP / FIDO2 / OpenPGP / SSH-sk / KeePassXC / age, chacun avec des gates de sécurité | Contrats d'usage et matériel restent dans Compose |
| [ADR-WKS-001](https://github.com/AlbanAndrieu/nabla-compose/blob/master/docs/adr/adr-workstation-option-a.md) | Séparation « Ubuntu OS chez Ansible ; matériels YubiKey et escrow chez Compose » | Conserve l'Option A acceptée |

**Incohérence en amont à corriger dans Compose, sans imposer une version
arbitraire :** son bootstrap affiche « Ubuntu Resolute fournit `ykman
5.9.2` » mais définit `NABLA_YKMAN_VERSION:-5.8.0`. Un paquet APT
légitime pourrait donc échouer au `--check` malgré une installation
correcte. Ce playbook ne vérifie que la présence du paquet et son
candidat dans les sources Ubuntu **déjà configurées**. Il ne modifie pas
la version imposée par Compose et ne télécharge pas de binaire Python.

## Paquets Ubuntu contrôlés

| Profil | Paquets | But |
| --- | --- | --- |
| **Runtime (base)** | `yubikey-manager`, `pcscd`, `libu2f-udev`, `libfido2-1`, `opensc`, `gnupg`, `scdaemon` | YKMan, PC/SC, udev/FIDO2, PKCS#11, GPG/OpenPGP |
| Build optionnel | `libpcsclite-dev`, `pkg-config` | En-têtes et détection PC/SC pour un éventuel `age-plugin-yubikey` géré hors Ansible |
| PAM outil optionnel | `libpam-u2f` | Mettre à disposition le module ; **aucun** enrollment, édition ou activation de PAM |

La présence des paquets ne démontre pas le fonctionnement des
appareils. `age-plugin-yubikey` construit avec Cargo, les liens
`~/.local/bin`, `sops` et les identités SSH/GPG ne sont pas gérés
par ce playbook. L'ancien PPA Yubico et la version historique
`libykpiv1` ne sont pas réintroduits. Aucune installation
`yubikey-agent` ou `python3-ykman` redondante par défaut.

## Audit sans modification (par défaut)

```bash
cd /workspace/users/albandrieu30/ansible-workstation

mise run test-offline
mise run yubikey-os-syntax
mise run yubikey-os-audit
```

Le playbook utilise exclusivement l'hôte local Ubuntu **24.04 ou
26.04**. Il lit `package_facts` et `apt-cache show` sur les noms de
paquets autorisés. La sortie contient uniquement :
`package_presence` et `ubuntu_repository_candidate` (booléens),
les profils optionnels et des limites. Pas de `sudo`, PPA, accès aux
tokens, interaction GPG ou écriture sur l'OS par défaut. Les résultats
privés intermédiaires restent `no_log` et ne sont pas enregistrés.

## Plan et installation — jamais implicites

L'étape ci-dessous **n'a pas été exécutée**. La conserver comme
procédure future lorsque l'opérateur accepte une mutation APT, et non
comme condition d'audit. Avant installation, inspecter le plan
et disposer d'un accès console local de secours. L'installation d'un
paquet APT peut déclencher des scripts de mainteneur et l'activation
du service `pcscd`, même si Ansible ne démarre pas de service lui-même.

```bash
# Simulation uniquement, après examen des noms de paquets :
.venv/bin/ansible-playbook -i localhost, -c local \
  playbooks/yubikey-os-prerequisites.yml \
  --check --ask-become-pass \
  -e yubikey_os_apply=true \
  -e yubikey_os_apply_approved=true

# Installation réellement autorisée, uniquement lors d'une séance séparée :
.venv/bin/ansible-playbook -i localhost, -c local \
  playbooks/yubikey-os-prerequisites.yml \
  --ask-become-pass \
  -e yubikey_os_apply=true \
  -e yubikey_os_apply_approved=true
```

**Important :** ces commandes sont des exemples de procédure pour un
opérateur consentant, **pas une approbation automatique**. Les deux
variables sont exigées. Les profils optionnels peuvent être ajoutés
par `-e yubikey_os_build_deps_enabled=true` et/ou
`-e yubikey_os_pam_tools_enabled=true`, après examen des paquets.
Les commandes ne modifient pas `/etc/pam.d` et ne provisionnent
aucune YubiKey. `--check` simule les actions du module APT mais
n'est pas un audit exact des scripts de post-installation.

Ne pas passer les flags d'apply au playbook historique
`playbooks/workstation.yml`, qui reste un provisionneur général.
Ne pas utiliser de `--tags` pour contourner des contrôles.

## Contrôles après une installation séparément autorisée

- Refaire `mise run yubikey-os-audit` ; vérifier les paquets installés.
- Utiliser dans **Compose** `bootstrap-yubikey-manager.sh --check`
  après correction ou paramétrage cohérent de la version, puis
  `just yubikey-dependencies-readonly` pour vérifier les processus et
  composants utilisateurs.
- Tester les utilisations une par une (KeePassXC OTP2, FIDO2 SSH,
  GPG/OpenPGP, PIV, SOPS/age) en lecture seule et sans imprimer
  secrets, numéros de carte ou identités.
- Toute activation de PAM, création de clé ou mutation de slot
  reste **NO-GO sans approbation explicite et retour arrière testé**.

**Aucun appel à `sudo`, APT, PAM, au socket Docker ou à une
YubiKey n'est lancé pendant la création de cette PR.**
