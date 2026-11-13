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

## 1. Bascule de `/home` sur le NVMe — faite le 13/11

Au boot de 10:33, `home-nvme-switch.service` a fait la passe finale en 5 min 14 s, renommé
l'ancien `/home` en `/home.sda-old`, monté le LV et ajouté la ligne à `/etc/fstab`. Au boot de
10:50, l'unité est sautée (`ConditionPathExists=!/home.sda-old`) et `/home` vient de `fstab`.
Preuves et mesures : [relevé du 13/11](roadmap-workstation.md#13-novembre-2026--après-la-bascule-de-home).
L'unité, son script et leurs tests sont retirés du dépôt (dans l'historique Git, commit `c09d3dc`) ;
le montage est codifié dans `stabilize_nvme_mounts` (`--check` : `ok`, aucun changement).

Unité retirée du système le 13/11 à 18:16, avec l'accord de l'opérateur (`systemctl disable`,
unité et script supprimés, `daemon-reload`) : elle ne peut plus repasser une fois
`/home.sda-old` supprimé. Les 47 images de `motion` écrites pendant la passe finale (10:38:06 à
10:38:27 ; `motion.service` manquait au `Before=` de l'unité) restent dans l'ancienne copie :
l'opérateur n'en a pas besoin.

Reste à faire : le 20/11, après une sauvegarde Restic réussie depuis la bascule,
`sudo rm -rf /home.sda-old` (160 Go libérés sur `sda`, `/` de 77 % à environ 42 %).

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
