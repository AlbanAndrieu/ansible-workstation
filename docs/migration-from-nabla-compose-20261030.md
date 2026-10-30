# Préparer l'extraction Workstation de nabla-compose

**30 octobre 2026 — PLAN, pas de cutover.** Extension de l'Option A
acceptée en PR #16. Voir le [contrat](workstation-ownership-option-a.md)
et l'[ADR Compose](https://github.com/AlbanAndrieu/nabla-compose/blob/fix/openclaw-diagnostics-fail-closed-20261030/docs/adr/adr-repository-split-workstation-yubikey-20261030.md).

## État existant : ne pas réinstaller à l'aveugle

La Workstation utilise un OpenClaw Gateway versionné
Node **24** / OpenClaw **2026.10.7** et un LiteLLM Workstation distinct
du LiteLLM TrueNAS. `ansible-workstation/mise.toml` déclare bien
`node = "24"` mais le template *historique*
`templates/openclaw-gateway-systemd.sh-Ubuntu.j2`
mentionne **Node 25.4.0** et **OpenClaw 2026.4.15**.
Il est hors contrat et **ne doit pas être installé**, même
dans un playbook `--check` global qui chargerait des tâches legacy.

Le `workstation.yml` historique contient de nombreuses tâches de
configuration et de durcissement ; ce n'est **pas** un outil d'audit
ni de migration à lancer globalement. Utiliser les playbooks
`playbooks/audit-workstation*.yml` spécifiques, sans sudo.

## Propriété prévue

| Élément | Nouveau propriétaire | Dépendance conservée |
| --- | --- | --- |
| Ubuntu/mise/Node et programmes système | **ansible-workstation** | Pinning `mise.toml`, playbooks opt-in |
| Audits de readiness systemd, DNS, services Workstation | **ansible-workstation** | Observations expurgées ; pas d'écriture de secrets |
| Configuration shell, starship, Terminator, unités utilisateur existantes | **dotfiles** | Option A, référentiel utilisateur |
| Gateway cible OpenClaw, heartbeat et automations non secrètes | **nabla-openclaw** (TrueNAS cible) | Instance Workstation conservée comme source/repli ; Ansible n'en fait que l'audit |
| Compose parent, LiteLLM serveur, datasets, réseau et quotas TrueNAS | **nabla-compose** | Le Gateway Docker cible et ses politiques sont dans **nabla-openclaw**, futur submodule piné |
| Matériel YubiKey, PIV, OTP2, recovery age, escrow client | **nabla-yubikey** (dépôt créé, transfert progressif) | Aucun secret ni mutation matérielle par import |
| Packages `pcscd`/`libfido2`/`ykman` | **ansible-workstation** ([playbook OS autonome](../playbooks/yubikey-os-prerequisites.yml), opt-in) | Audit sans privilèges par défaut ; installation doublement autorisée, pas de PAM ni de mutation du token |
| Serveur d'escrow TrueNAS, NFS ACL et datasets | **nabla-compose** | Le client YubiKey s'interface par sonde |

Les dépôts publics `nabla-yubikey` et `nabla-openclaw` ont été créés.
Les premiers transferts sont ouverts en PR Draft, sans cutover. Les licences
et les fichiers privés doivent rester contrôlés avant chaque lot. Ne pas y copier d'archives `.age`, de secrets
PIV/OTP, de fichiers `.sops.yaml` ou de sessions réelles.

## Phases de migration du code

**P0 — inventory, dry-run seulement :** dans nabla-compose
`python3 scripts/ops/plan-repository-split.py`. Comptes issus
des 370 recettes : 84 YubiKey, 98 OpenClaw, 15 Workstation.
Examiner les imports, `justfile`, scripts enfants et runbooks
avant de sélectionner des lots de déplacement.

**P1 — préflight Ubuntu :** audit `mise`, unité OpenClaw
effective, version Node/OpenClaw et symlinks/permissions,
sans lecture des variables d'environnement ni des jetons. Vérifier
que le vieux template est obsolète ; ne pas l'appliquer.

**P2 — premiers transferts :** démarrer par les tests hermétiques
et collecteurs qui ne dépendent pas de `scripts/truenas/`,
par exemple classification de l'hôte et contrat Gateway.
Préserver output, exit codes 0/2, `NO_COLOR`, redaction et
les commandes anciennes comme wrappers temporaires.

**P3 — cron/heartbeat :** transférer politique/version non secrète,
contrats de validation et futur réconciliateur vers `nabla-openclaw`,
**pas** vers le rôle Ansible Workstation. Ne pas toucher directement à
SQLite/aux agents ; snapshots et rollback restent privés.

**P4 — intégrations :** migrer le Gateway `OpenClaw Workstation →
OpenClaw TrueNAS` et valider LiteLLM **local au NAS** ; garder les
sondes serveur, les quotas et secrets dans Compose. Le Gateway source
Workstation reste en service tant que les modèles, clés virtuelles,
stockage et réseau du Gateway cible ne sont pas prouvés.

**P5 — cutover :** tester sur Workstation ET TrueNAS, puis épingler un
tag/commit du nouveau `nabla-openclaw` comme submodule de Compose sur
un chemin ne chevauchant pas `apps/openclaw/compose.yml`. Stopper toute
duplication des crons avant démarrage de production ; rollback local
vérifié avant retrait de l'ancien code. Pas de propagation implicite
de `git pull` entre dépôts.

## Gate indépendant pour template obsolète

```bash
python3 scripts/check-openclaw-template-ownership.py
python3 -m unittest discover -s tests -p 'test_openclaw_template_ownership_contract.py' -v
```

Le script refuse la promotion du template tant que la version
Node du template diffère du pin `mise.toml` ou que son état est
explicitement legacy. Un `exit=2` est la sortie attendue
avant modernisation, **pas** une panne Gateway.

Aucun job GitHub Actions, aucun `ansible-playbook --become`,
aucune modification des PIN/PUK/PIV, aucune copie de `~/.openclaw`.

## Contrôle source ajouté à la PR #16 (2026-10-30)

Le collecteur non privilégié [audit-openclaw-source.py](../scripts/audit-openclaw-source.py)
compare seulement la CLI Node 24/OpenClaw 2026.10.7 et l'état de
`openclaw-gateway.service`, sans lire `openclaw.json` ni l'environnement.
Le verdict `source_cli_and_unit_observed` **ne prouve pas** la
readyz du Gateway ni le modèle effectif. Voir le
[runbook source → TrueNAS](openclaw-workstation-to-truenas.md).

```bash
python3 -m unittest discover -s tests -p 'test_openclaw_source_audit_contract.py' -v
mise run audit-openclaw-source-syntax
mise run audit-openclaw-source
```
