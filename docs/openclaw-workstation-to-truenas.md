# OpenClaw source on Ubuntu → TrueNAS target

**Owner Ubuntu: ansible-workstation PR #16.**
**Owner cible OpenClaw: [nabla-openclaw](https://github.com/AlbanAndrieu/nabla-openclaw).**
**Owner TrueNAS/LiteLLM/NFS: nabla-compose.**

L'audit est **source seulement** : ne déploie pas et ne déplace pas
le Gateway. `~/.openclaw/` reste un état privé. Le modèle
OpenClaw source est `systemd --user`, la destination est une
application Docker/TrueNAS SCALE qui n'est **pas encore déployée**.

```bash
cd ~/w/ansible-workstation
python3 -m unittest discover -s tests -p 'test_openclaw_source_audit_contract.py' -v
python3 scripts/audit-openclaw-source.py
mise run audit-openclaw-source-syntax
mise run audit-openclaw-source
```

Le verdict `source_cli_and_unit_observed` atteste uniquement que
l'unité utilisateur est active et les versions CLI Node/OpenClaw
attendues. Il **ne prouve pas** l'ExecStart effectif, la disponibilité
HTTP du Gateway, les clés LiteLLM, modèles, budgets ou les services
TrueNAS ; ces contrôles doivent conserver leurs gates propres.

`source_drift_or_unverified` ou `wrong_host_no_runtime_inference`
doivent rester des états inconclusifs à diagnostiquer, pas des
incidents TrueNAS. Pas de sudo, pas d'appel LLM, pas de
modification de PAM/YubiKey, cron, heartbeat, DNS ou systemd.

### Séquence de migration

1. Vérifier la source Workstation et garder sa sauvegarde chiffrée.
2. Valider et taguer la première release `nabla-openclaw`.
3. Préparer datasets, secrets et réseau TrueNAS dans Compose ;
   ajouter un submodule sur un chemin **non existant** une fois prêt.
4. Préparer le Gateway cible avec automations désactivées et tests.
5. Bascule manuelle puis rollback Workstation si besoin.
6. Retirer l'ancien runtime local seulement après preuve de stabilité.

Le vieux template systemd Workstation à base de Node25 reste bloqué.
