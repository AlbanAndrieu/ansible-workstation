# Workstation Ubuntu — Option A

Ce dépôt possède **l'état souhaité de l'OS** et les audits locaux en lecture seule :
paquets, services systemd système, DNS, SSH, pare-feu, sysctl, montages et
politique de sauvegarde chiffrée Restic.

- [Contrat de responsabilités et séparation YubiKey/PAM](docs/workstation-ownership-option-a.md)
- [Prérequis YubiKey Ubuntu — audit et installation APT uniquement sur autorisation](docs/yubikey-os-prerequisites.md)
- [Roadmap de ce dépôt](docs/roadmap-workstation.md)
- [Politique et contrôle offline des skills Ansible](docs/agent-skills-workstation.md)
- [Audit local Ubuntu P0, sans sudo ni mutation](docs/audit-workstation.md)
- [Audit P0 réseau : visibilité sans privilèges, données expurgées](docs/audit-workstation-network.md)
- [Plan P0 : validation des flux LAN/WAN et des publications Docker](docs/workstation-network-exposure-plan.md)
- [Mesures P0 : tests TCP privés depuis local/LAN/WAN et publications Docker (opt-in)](docs/workstation-network-measurement.md)
- [Inventaire matériel historique](workstation-hardware-inventory.md)
- [Runbook des runtimes mise/uv et DNS](docs/mise-uv-cloudflare-workstation.md)
- [Préparation de l'extraction Workstation depuis nabla-compose](docs/migration-from-nabla-compose-20261030.md)
- [Audit de la source OpenClaw Workstation → cible TrueNAS](docs/openclaw-workstation-to-truenas.md)

Les configurations utilisateur relèvent de [dotfiles](https://github.com/AlbanAndrieu/dotfiles)
et les opérations matérielles YubiKey du nouveau [nabla-yubikey](https://github.com/AlbanAndrieu/nabla-yubikey) (migration en cours). La cible OpenClaw est [TrueNAS via nabla-openclaw](https://github.com/AlbanAndrieu/nabla-openclaw) ; Ansible ne gère que l'audit de l'instance Workstation existante.

**Pas de lancement global du `workstation.yml` historique pour un audit.**
La sauvegarde n'est validée qu'après `restic check` et restauration de test
depuis un dépôt chiffré indépendant. Secrets et snapshots privés hors Git.
