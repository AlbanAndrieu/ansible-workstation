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

Le point de montage vide de `/home` sur `/` est immuable depuis le 13/11 (D1, `chattr +i` posé à
travers un `mount --bind /` temporaire) : si le LV ne se monte pas, rien ne peut s'y écrire et la
session échoue au lieu de s'ouvrir sur un `/home` vide. `lsattr -d` sur ce point de montage :
`----i---------e-------`.

Retour arrière (TTY root, session fermée) :
`umount /home && chattr -i /home && rmdir /home && mv /home.sda-old /home`,
retirer la ligne `/home` de `/etc/fstab`, redémarrer. Ce qui a été écrit dans `/home` depuis la
bascule reste sur le LV (`mount /dev/vg-nvme-crypt/home /mnt/home-nvme` pour le récupérer).

## 2. Alertes SMART et usure — en PR le 13/11

Règles `WorkstationSsdWearHigh`, `WorkstationDiskSectorsFailing` et `WorkstationNvmeDegraded`
dans `apps/prometheus/rules/node-exporter.rules.yml` de `nabla-compose`
([PR #371](https://github.com/AlbanAndrieu/nabla-compose/pull/371)) : promtool valide, les trois
expressions renvoient les disques attendus sur le Prometheus de TrueNAS, aucune ne se déclenche.

Reste à faire après la fusion : faire relire ses règles à Prometheus (skill `truenas-ops`), puis
envoyer une alerte de test (`amtool alert add WorkstationSsdWearHigh disk=/dev/sda`), qui doit
arriver.
