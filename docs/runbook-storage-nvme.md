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

## 1. Basculer `/home` sur le NVMe (devant la machine)

Bloqué pour l'agent : la session graphique tient `/home` ouvert. Une copie à chaud est déjà sur
le LV (`/mnt/home-nvme`) ; la passe finale ne recopie que ce qui a changé.

1. Fermer la session graphique, passer sur un TTY (`Ctrl+Alt+F3`), se connecter en root.
2. Vérifier que plus rien ne tient `/home` :

   ```bash
   fuser -vm /home
   ```

3. Passe finale, puis basculer :

   ```bash
   mountpoint -q /mnt/home-nvme || mount /dev/vg-nvme-crypt/home /mnt/home-nvme
   rsync -aHAXS --numeric-ids --delete /home/ /mnt/home-nvme/
   umount /mnt/home-nvme
   mv /home /home.sda-old && mkdir /home
   echo '/dev/vg-nvme-crypt/home /home ext4 defaults,nofail,x-systemd.device-timeout=30s 0 0' >> /etc/fstab
   systemctl daemon-reload && mount /home
   ```

4. Redémarrer (premier boot à froid avec `/etc/crypttab` : seule la phrase de passe de `sda3_crypt`
   doit être demandée), ouvrir la session, puis :

   ```bash
   systemctl status systemd-cryptsetup@nvme2_crypt systemd-cryptsetup@nvme5_crypt --no-pager
   findmnt /home /data/models/ollama
   ```

   Les deux volumes doivent être `active (exited)`, `/home` sur `vg--nvme--crypt-home` et les
   modèles sur `vg--nvme--crypt-models`.
5. Une semaine plus tard, si tout va bien : `rm -rf /home.sda-old` (environ 150 Go libérés sur
   `sda`), puis ajouter `/home` à `stabilize_nvme_mounts`.

Retour arrière : retirer la ligne `/home` de `/etc/fstab`, `rmdir /home && mv /home.sda-old /home`,
redémarrer.

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
