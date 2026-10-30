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
| Code de contrôle local OpenClaw, heartbeat et automations publiques | **ansible-workstation** *candidate* après parité | Runtime et base `~/.openclaw` restent locaux/privés |
| Images/Compose OpenClaw sur TrueNAS, serveurs LiteLLM, DB, stockage, clés virtuelles, quotas | **nabla-compose** | Contrats inter-hôtes communs, pas de recopie de credentials |
| Matériel YubiKey, PIV, OTP2, recovery age, escrow client | **futur nabla-yubikey** | Contrôles de sécurité et validation explicite |
| Packages `pcscd`/`libfido2`/`ykman` | **ansible-workstation** (futur rôle opt-in) | Pas de PAM ni de mutation du token |
| Serveur d'escrow TrueNAS, NFS ACL et datasets | **nabla-compose** | Le client YubiKey s'interface par sonde |

Le nom `nabla-yubikey` est une **proposition** de repo absent à ce jour.
Il faut créer le dépôt avec revue de confidentialité/licence avant
une extraction. Ne pas y copier d'archives `.age`, de secrets
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

**P3 — cron/heartbeat :** transférer la politique/version non
secrète et le réconciliateur `plan/check/apply`. Ne pas toucher
directement aux tables SQLite/aux agents ; la CLI native conserve
l'état, les archives privées et rollback.

**P4 — intégrations :** scinder
`OpenClaw Workstation → LiteLLM TrueNAS` (client local ici)
et les probes de LiteLLM côté TrueNAS (restent Compose).
Le tunnel SSH et les clés virtuelles doivent être validés avant
toute bascule.

**P5 — cutover :** tests locaux et parité sur Workstation ET
TrueNAS, puis seulement suppression du code historique dans
Compose. Pas de sous-module Git obligatoire ni de propagation
de `git pull` à travers les dépôts.

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
