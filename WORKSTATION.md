# Workstation Ubuntu — Option A

Ce dépôt possède **l'état souhaité de l'OS** et les audits locaux en lecture seule :
paquets, services systemd système, DNS, SSH, pare-feu, sysctl, montages et
politique de sauvegarde chiffrée Restic.

- [Contrat de responsabilités et séparation YubiKey/PAM](docs/workstation-ownership-option-a.md)
- [Roadmap de ce dépôt](docs/roadmap-workstation.md)
- [Audit local Ubuntu P0, sans sudo ni mutation](docs/audit-workstation.md)
- [Audit P0 réseau : visibilité sans privilèges, données expurgées](docs/audit-workstation-network.md)
- [Plan P0 : validation des flux LAN/WAN et des publications Docker](docs/workstation-network-exposure-plan.md)
- [Inventaire matériel historique](workstation-hardware-inventory.md)
- [Runbook des runtimes mise/uv et DNS](docs/mise-uv-cloudflare-workstation.md)

Les configurations utilisateur relèvent de [dotfiles](https://github.com/AlbanAndrieu/dotfiles)
et les opérations matérielles YubiKey de [nabla-compose](https://github.com/AlbanAndrieu/nabla-compose).

**Pas de lancement global du `workstation.yml` historique pour un audit.**
La sauvegarde n'est validée qu'après `restic check` et restauration de test
depuis un dépôt chiffré indépendant. Secrets et snapshots privés hors Git.
