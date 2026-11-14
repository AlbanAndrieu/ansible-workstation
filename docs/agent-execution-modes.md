# Modes d'exécution des agents — Ubuntu Workstation

Autorité : [AGENTS.md](../AGENTS.md). Le dépôt garde la configuration OS ;
`dotfiles` gère le shell, `nabla-openclaw` le Gateway et
`nabla-yubikey` le matériel. Une capacité annoncée par un agent
n'atteste jamais l'accès à la Workstation.

| Contexte | Actions possibles | Ce qu'il ne faut pas conclure |
| --- | --- | --- |
| **Claude Code local** avec checkout Ubuntu et droits attestés | `mise run agent-skills-check`, `mise run test-offline`, tests ciblés, `mise run audit-syntax`, puis audits **read-only** tels que `mise run audit-configuration` | Un audit OS n'autorise ni `ansible-playbook playbooks/workstation.yml`, ni sudo, PAM, DNS, SSH, pare-feu, clefs ou changement système |
| **Codex distant** ou API GitHub sans poste | PR Draft, correction des playbooks/scripts/docs, test hermétique dans son propre environnement si disponible, AST/inspection statique | Les sondes `systemd`, `resolvectl`, Docker, YubiKey, montage NFS, `mise` local et TrueNAS sont **NOT_RUN**, pas PASS |
| **Checkout isolé avec tests disponibles, mais sans homelab** | Validation syntaxique / unittest ciblé | Aucun succès ne prouve l'état du runtime Ubuntu |

## Boucle courte

1. Déterminer la PR et son HEAD exact, travailler dans une branche dédiée.
2. Consulter `AGENTS.md` et **uniquement** les skills pertinents dans
   `.agents/skills/<name>/SKILL.md` ; leurs alias `.claude/skills`,
   `.hermes/skills` et `skills/` sont des symlinks, **pas des copies**.
3. Exécuter le test minimal qui réfute le changement. Sur Workstation,
   élargir à `mise run test-offline`, puis `mise run quality` **une fois**
   avant publication ; les audits de l'hôte restent séparés et explicites.
4. Pour Codex distant, ne pas relancer d'outils indisponibles ; conserver
   un contrat testable et livrer la commande exacte que Claude Code pourra
   exécuter localement, avec état `NOT_RUN` (pas de faux succès).
5. Rendre uniquement : fichiers modifiés, test réellement exécuté et
   prochain contrôle runtime/GO-NO-GO. Aucun log complet positif en contexte.

## Sécurité et ressources

- L'agent local peut employer CPU/RAM/Node/Python d'Ubuntu pour tests,
  lint et analyse ciblée ; ne pas lancer tous les scans à chaque modification.
- `mise run audit-configuration` est **read-only** sur Workstation ;
  ne pas exécuter l'ancien playbook de configuration pour diagnostiquer.
- Aucun accès secret, PIN/PUK/PIV, YubiKey mutation ou modification PAM,
  sudo, DNS, réseau, firewall, systemd ou packages sans action approuvée.
- En mode distant, ni SSH/TrueNAS, ni GitHub Actions payantes, ni faux
  résultats de sonde pour remplacer l'accès hôte.
- Vérifier la provenance `skills-lock.json` et les liens avec
  `mise run agent-skills-check` sur Workstation ; ces vérifications
  n'exécutent pas les scripts des skills tiers.

Références : [contrat des skills](agent-skills-workstation.md),
[roadmap de la Workstation](roadmap-workstation.md).
