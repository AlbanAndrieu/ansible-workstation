# Ownership workstation Ubuntu — Option A (accepté)

**Date :** 27 octobre 2026. **Source de gouvernance :** [ADR Compose](https://github.com/AlbanAndrieu/nabla-compose/blob/master/docs/adr/adr-workstation-option-a.md).

## Sources d'autorité

- **dotfiles** : configuration utilisateur dans `$HOME` (`.bashrc`, Starship, Terminator, Git, unités systemd `--user` non sensibles). Ne constitue ni un inventaire de l'OS ni une sauvegarde.
- **ansible-workstation (ce dépôt)** : configuration souhaitée et audit de la workstation Ubuntu ; paquets, services systemd *système*, /etc, DNS, SSH, pare-feu, sysctl, mounts, politique de sauvegarde. Les données d'observation n'appartiennent pas à Git.
- **nabla-compose** : architecture transversale, YubiKey hardware/policy diagnostics/escrow, intégrations homelab et runbooks.
- **Restic chiffré** : sauvegarde hors Git de fichiers utiles, snapshots privés et des artefacts de reprise ; contrôle d'intégrité et essai de restauration. Le dépôt Restic doit inclure une destination indépendante de la workstation **et du NAS principal**.

`mise.toml`, `uv.lock` et `package-lock.json` restent dans le projet qui les consomme. Les versions des outils de gestion Ansible ne sont pas une preuve des versions présentes sur l'hôte.

## Audit, convergence et stockage

```text
policies/ (état voulu, sans secret) ─────┐
                                       ├─ audit read-only → diff expurgé
inventaire observé (facts filtrés) ─────┘          │
                                                   ├─ aucune mutation (par défaut)
                                                   └─ apply opt-in + plan + rollback
                                                      │
                                   privé hors Git : snapshots datés
                                                      │
                                      Restic chiffré → check + restore test
```

L'inventaire contient *seulement* les attributs allowlistés. Les faits complets Ansible ou les fichiers `/etc` bruts peuvent dévoiler identité, adresses, secrets et tokens : ils ne doivent jamais être committés, envoyés en CI ou inclus dans un rapport public.

Le prototype `dotfiles/bin/inspect-workstation-system.py` est conservé comme compatibilité. Le collecteur canonique sera déplacé ici après un test d'équivalence JSON v1, puis `dotfiles` pourra fournir un wrapper. Ne pas dupliquer des sondes Python si `ansible.builtin.setup`, `package_facts`, `service_facts` ou `stat` fournissent déjà la valeur.

## YubiKey : frontière clarifiée

**La configuration matérielle et les credentials YubiKey appartiennent exclusivement à `nabla-compose`.** Cela comprend OTP2/HMAC-SHA1, FIDO2/WebAuthn/SSH-sk, OpenPGP, PIV (9A, 82, AES256), age, escorte/escrow, attestations et diagnostics matériels. Ne jamais changer PIN, PUK, OTP, slots PIV ou clés sans approbation et contrôle local.

Le bundle historique `tasks/yubikey.yml` est **retiré du rôle général** et supprimé : il couplait installation de paquets à l'ajout du PPA Yubico et à la copie de `/etc/pam.d/common-auth` lorsque `pam_enabled: true`. Les deux templates PAM historiques, sans autre appel actif, sont également supprimés. La suppression concerne le **code Ansible**, pas la machine : aucune désinstallation de paquet, aucune modification de PAM, aucun changement de YubiKey.

En cas de besoin de `libfido2`, `pcscd`, `ykman` ou `opensc`, créer plus tard un rôle **OS prerequisites uniquement**, explicitement activable ; il ne touche pas PAM et ne manipule jamais les applets. L'authentification Ubuntu/PAM peut être audité séparément, mais tout changement nécessite secours local, backup validé et phase opt-in dédiée.

## Évolution proposée (30 octobre 2026), sans changer Option A active

Un dépôt YubiKey spécialisé `nabla-yubikey` est **proposé**, mais
n'existe pas encore. Jusqu'à la création, au contrôle des licences et
à la validation des tests, `nabla-compose` reste le propriétaire
effectif des diagnostics matériels. Seules les tâches OS optionnelles
(`pcscd`, `libfido2`, `ykman`) seraient éventuellement Ansible.
Les agents/cron/heartbeat OpenClaw publics peuvent ensuite être
transférés vers le nouveau périmètre Workstation, tandis que
`~/.openclaw` et les unités utilisateur déjà gérées par dotfiles
restent privées et ne sont pas automatiquement remplacées.

Voir le [plan d'extraction](migration-from-nabla-compose-20261030.md).
En particulier, le vieux template systemd OpenClaw (Node 25.4.0,
version 2026.4.15) reste interdit au déploiement.

## Première preuve observée, 27 octobre 2026

L'opérateur a exécuté le collecteur dotfiles : Ubuntu 26.04.1, noyau 7.0.0-38, NVIDIA RTX 2060/595.71.05, AppArmor/auditd/fail2ban/unattended-upgrades actifs, Secure Boot désactivé, nftables/ufw services inactifs, `ip_forward=1`. **Aucun état de filtrage réseau n'est déduit des états systemd.** L'ancien inventaire nommait la carte mère Z390-E ; l'observation indique Z390-F : ne pas changer la référence sans preuve matérielle supplémentaire.

## Contraintes d'exploitation

- Audit uniquement par défaut ; ne pas exécuter le playbook historique `workstation.yml` comme collecteur.
- Pas de `--diff` contenant des secrets, de dump réseau, ni de `sudo tar /etc` automatique.
- DNS pfSense, UFW/DOCKER-USER, PAM, Secure Boot, SSH, Tailscale et cloudflared : changements **opt-in** après plan, rollback et accès console.
- `[skip ci]`, tests locaux, PR Draft, pas de rerun Actions et aucun automerge.

Voir [roadmap propre à ce dépôt](roadmap-workstation.md).
