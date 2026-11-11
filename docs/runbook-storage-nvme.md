# Runbook : stockage NVMe chiffré

**11 novembre 2026.** Suite des étapes 3 à 6 de la [roadmap](roadmap-workstation.md) : ce qui
reste à faire devant la machine ou hors de ce dépôt. Rayer une section une fois faite.

## État

- `nvme0n1p2` et `p5` : LUKS2, clé `/etc/cryptsetup-keys.d/nvme_crypt.key` (root, 0400) sur la
  racine chiffrée, déverrouillées par `/etc/crypttab` (`nofail`). Copie de la clé et des
  en-têtes LUKS sur la clé USB d'escrow, dans `luks-escrow/`.
- VG `vg-nvme-crypt` (382 Go) : LV `home` 250 Go, LV `models` 40 Go, 92 Go libres.
- Modèles ollama sur le LV `models`, monté sur `/data/models/ollama` : chargement à froid de
  `qwen3.5:4b` 17 s → 5,7 s. Ancienne copie gardée dans `/data/models/ollama.hdd-20261111`.
- Codifié dans [`stabilize-workstation.yml`](../playbooks/stabilize-workstation.yml)
  (`stabilize_nvme_crypt`, `stabilize_nvme_mounts`).

Restaurer un volume si la racine est perdue : brancher la clé d'escrow, puis
`cryptsetup open --key-file luks-escrow/nvme_crypt.key /dev/nvme0n1p2 nvme2_crypt` (idem `p5`) ;
en-tête abîmé : `cryptsetup luksHeaderRestore /dev/nvme0n1p2 --header-backup-file luks-escrow/nvme0n1p2.luks-header`.

## 1. Reboot et bascule de `/home` sur le NVMe

Vérifié le 11/11, avant le reboot :

- noyau `7.0.0-43-generic` installé le matin (`/var/run/reboot-required` : `linux-image`,
  `linux-base`, `gnome-shell`) ; module NVIDIA 595.71.05 construit par DKMS pour ce noyau ;
- son initramfs ne contient que `sda3_crypt` dans `cryptroot/crypttab` : une seule phrase de passe
  au boot, les volumes NVMe s'ouvrent ensuite avec la clé de la racine ;
- `/boot` : 410 Mo libres ; `systemctl --failed` vide, à comparer après le reboot ;
- copie à chaud resynchronisée en fin de journée : 3,8 millions de fichiers, 13 872 recopiés
  (12,8 Go), LV `home` à 146 Go sur 246. La passe du boot reparcourt tout, mais ne copie que le
  delta.

La bascule se fait au boot, une seule fois, par
[`home-nvme-switch.service`](../files/home-nvme-switch.service) : il passe avant GDM, les sessions
(gestionnaire utilisateur en *lingering* compris), Docker, containerd, cron et ollama, donc rien
n'écrit dans `/home` pendant la passe finale. Le [script](../files/home-nvme-switch.sh) refait
`rsync -aHAXS --delete` (la copie à chaud est faite, seul le delta passe), renomme l'ancien `/home`
en `/home.sda-old`, monte le LV sur `/home` et ajoute la ligne à `/etc/fstab`. Si le montage
échoue, il remet l'ancien `/home` en place et le boot continue dessus. Il ne tourne plus dès que
`/home.sda-old` existe.

1. Avant le reboot, une fois les sessions Claude en cours au repos : installer et activer l'unité
   (l'agent n'a pas le droit de poser une unité de boot) :

   ```bash
   sudo install -m 0755 files/home-nvme-switch.sh /usr/local/sbin/home-nvme-switch
   sudo install -m 0644 files/home-nvme-switch.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable home-nvme-switch.service
   ```

2. Redémarrer. Seule la phrase de passe de `sda3_crypt` est demandée ; la console affiche la passe
   finale (quelques minutes) avant l'écran de connexion.
3. Après connexion :

   ```bash
   systemctl status home-nvme-switch systemd-cryptsetup@nvme2_crypt systemd-cryptsetup@nvme5_crypt --no-pager
   findmnt /home /data/models/ollama
   uname -r; nvidia-smi -L; systemctl --failed
   ```

   Attendu : les trois unités en `active (exited)`, `/home` sur `vg--nvme--crypt-home`, les modèles
   sur `vg--nvme--crypt-models`, noyau `7.0.0-43-generic`, GPU listé, aucune unité en échec.
4. Une semaine plus tard, si tout va bien (environ 140 Go libérés sur `sda`), puis ajouter `/home`
   à `stabilize_nvme_mounts` :

   ```bash
   sudo systemctl disable home-nvme-switch.service
   sudo rm /etc/systemd/system/home-nvme-switch.service /usr/local/sbin/home-nvme-switch
   sudo rm -rf /home.sda-old
   ```

Sans l'unité : fermer la session, se connecter en root sur un TTY (`Ctrl+Alt+F3`), vérifier que
`fuser -vm /home` ne liste rien, lancer
`/usr/local/sbin/home-nvme-switch /dev/vg-nvme-crypt/home /home /mnt/home-nvme /etc/fstab`, puis
redémarrer.

Retour arrière (TTY root, session fermée) : `umount /home && rmdir /home && mv /home.sda-old /home`,
retirer la ligne `/home` de `/etc/fstab`, redémarrer. Ce qui a été écrit dans `/home` depuis la
bascule reste sur le LV (`mount /dev/vg-nvme-crypt/home /mnt/home-nvme` pour le récupérer).

## 2. Alertes SMART et usure (dépôt `nabla-compose`)

Bloqué pour l'agent : le checkout `nabla-compose` est sur la branche d'une autre tâche, avec des
changements indexés. Les métriques existent déjà (job `workstation_node`, fichiers
`smartmon.prom` et `nvme.prom`). Ajouter dans `apps/prometheus/rules/node-exporter.rules.yml` :

```yaml
  - name: WorkstationDisks
    rules:
      - alert: WorkstationSsdWearHigh
        expr: smartmon_wear_leveling_count_value{job="workstation_node"} < 20
        labels:
          severity: warning
        annotations:
          summary: "Worn SATA SSD {{ $labels.disk }} on the workstation"
          description: "Wear_Leveling_Count normalized value is {{ $value }} (33 on 10 Nov 2026): plan its replacement."

      - alert: WorkstationDiskSectorsFailing
        expr: |
          max by (disk) (
            smartmon_reallocated_sector_ct_raw_value{job="workstation_node"}
            or smartmon_current_pending_sector_raw_value{job="workstation_node"}
            or smartmon_offline_uncorrectable_raw_value{job="workstation_node"}
          ) > 0
        labels:
          severity: warning
        annotations:
          summary: "Failing sectors on workstation disk {{ $labels.disk }}"
          description: "Reallocated, pending or uncorrectable sectors: back up and replace the disk (lvconvert --repair for the RAID1)."

      - alert: WorkstationNvmeDegraded
        expr: nvme_critical_warning{job="workstation_node"} > 0 or nvme_media_errors_total{job="workstation_node"} > 0
        labels:
          severity: critical
        annotations:
          summary: "NVMe {{ $labels.device }} reports a critical warning or media errors"
```

Vérifier : `promtool check rules`, déployer (skill `truenas-ops`), puis une alerte de test
(`amtool alert add WorkstationSsdWearHigh disk=/dev/sda`) doit arriver.
