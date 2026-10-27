# Audit Ubuntu workstation — P0 (lecture seule)

Ce playbook appartient **uniquement** à `ansible-workstation`. Il ne charge
pas `tasks/workstation.yml`, les rôles de provisioning, YubiKey/PAM, les
secrets, Restic ni le réseau du homelab. L'[architecture Option A](workstation-ownership-option-a.md)
conserve l'état souhaité dans Git et les observations sensibles hors Git.

## Procédure locale

Exécuter dans le checkout Ansible local, **sans sudo** et sans ajouter de
`--become`. Le projet Ansible doit déjà disposer d'une `.venv` validée.

```bash
cd /workspace/users/albandrieu30/ansible-workstation

# Aucune installation, synchronisation ni exécution de rôles.
python3 -m unittest discover -s tests -p 'test_*contract.py' -v

# Vérification statique du nouveau playbook seulement.
mise run audit-syntax

# Audit explicite : sortie anonymisée dans le terminal.
mise run audit-workstation
```

Équivalent sans mise :

```bash
.venv/bin/ansible-playbook -i localhost, -c local \
  --syntax-check playbooks/audit-workstation.yml
.venv/bin/ansible-playbook -i localhost, -c local \
  playbooks/audit-workstation.yml
```

Le playbook utilise `hosts: localhost`, `connection: local`,
`gather_facts: false` et `become: false`. Il appelle les modules
`ansible.builtin.setup`, `service_facts`, `package_facts`, `slurp`
et des opérations en mémoire `set_fact`/`assert`. Seule la dernière
tâche `debug` affiche une structure réduite. Tous les faits bruts et les
résultats intermédiaires utilisent `no_log: true`.

Les faits sont utilisés en mémoire dans le playbook et ne sont pas archivés
par ce projet. **Ansible peut créer ses fichiers de modules temporaires sous
`~/.ansible/tmp`**, puis les nettoyer ; cela ne constitue pas un snapshot ni
une sauvegarde. Aucune configuration système ni rapport persistant n'est écrit
par les tâches de ce playbook. Ne pas rediriger la sortie de la commande
Ansible vers le dépôt. Les paramètres noyau sont lus dans une **liste
fermée** de chemins sous `/proc/sys`. Le contrôle `failed_when: false`
ne masque que les lectures manquantes de ces paramètres : les valeurs
absentes sont affichées `unknown`, jamais `0` par défaut.

## Rapport approuvé

Schéma `workstation-ansible-audit/v1` : date UTC, nom et version Ubuntu,
noyau, architecture, mémoire, **10 services** (état + type de démarrage),
**10 paquets** (version si installé), **9 sysctls** et présence de **5
points de montage** attendus. Aucun hostname, utilisateur, IP, MAC,
UUID, numéro de série, unité complète, variables d'environnement, règle
de pare-feu, token ni fichier PAM n'est affiché.

Le collecteur Python historique
[`dotfiles/bin/inspect-workstation-system.py`](https://github.com/AlbanAndrieu/dotfiles/blob/main/bin/inspect-workstation-system.py)
reste disponible ; ce playbook n'est **pas** encore son remplaçant JSON.
L'équivalence du schéma et le transfert définitif seront traités à P1.

**Interprétation :** `nftables.service: stopped` et
`ufw.service: stopped` ne démontrent pas l'absence de filtrage, notamment
avec Docker. `ip_forward=1` est une observation, pas une instruction de
désactivation. Un montage présent ne prouve ni RAID1 sain ni sauvegarde.
Une version de paquet installée ne prouve pas l'absence de vulnérabilité.

## Sécurité et limites

- L'audit **n'exécute pas** `workstation.yml` ni de playbook d'apply.
- Pas de root, pas de modification PAM, SSH, DNS, UFW, nftables, Secure Boot,
  YubiKey, services systemd ou paquets.
- Aucun snapshot privé, coffre, Restic ou sauvegarde de données n'est créé.
- Un changement de politique système nécessite un plan, la validation
  d'un rollback et une action **opt-in** séparée.
- L'absence de faits OS ou d'un gestionnaire de paquets compatible peut
  interrompre l'audit ; la correction ne doit pas être une installation
  automatique au moment de l'exécution.
- Les futurs rapports privés devront définir lieu de stockage, contrôle
  d'accès, rétention et chiffrement Restic **avant** activation.

## Gates d'acceptation

1. `tests/test_workstation_audit_contract.py` vérifie la liste autorisée
   des modules, l'absence de privilège, les champs publiés et l'anonymisation.
2. `mise run audit-syntax` valide le YAML avec la version Ansible locale
   du projet.
3. `mise run audit-workstation` produit un rapport borné avec
   `changed=0`, sans échec ni écriture système.
4. Les valeurs sont comparées à l'inventaire du 27/10 et qualifiées
   `observed`, `unknown` ou `needs-review`. Pas de statut `secure`
   inventé par un résultat de commande.

Avant ces preuves, le statut du playbook est **CODE ADDED / RUNTIME NOT
VERIFIED**.
