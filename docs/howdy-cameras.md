# Howdy et motion : une caméra chacun

**Statut :** APPLIQUÉ le 16/11/2026, enrôlement et activation PAM à faire —
9 contrats offline PASS (`tests/test_howdy_cameras_contract.py`), `ansible-lint`
(profil production) PASS, playbook convergé sans changement PAM au second passage.

Playbook : [`playbooks/howdy-cameras.yml`](../playbooks/howdy-cameras.yml),
opt-in, jamais importé par le rôle global (qui n'installe plus Howdy).

## Objectif

| Caméra | Usage |
|---|---|
| A | `motion` au démarrage, **arrêté automatiquement après 5 min**, puis libre pour les visios |
| B | Howdy uniquement |

Une webcam UVC ne sert qu'un flux à la fois : si motion et Howdy pointent
sur la même caméra, l'un des deux échoue (« device busy »).

**PAM n'est jamais modifié ici.** Howdy est installé avec `disabled = true` :
même si le paquet ajoutait une ligne PAM, le module l'ignorerait. L'activation
relève de `nabla-yubikey` (voir `playbooks/harden-os.yml`).

## État observé (30 octobre 2026)

- Deux Logitech C310 (`046d:081b`) identiques : port USB `3.3` →
  `/dev/video0`, port USB `9` → `/dev/video2` (`video1`/`video3` =
  métadonnées). Les numéros peuvent s'inverser au démarrage : le playbook
  exige des liens stables `/dev/v4l/by-path/...`.
- `howdy` en état `rc` (supprimé, configuration conservée) ; source
  `ubuntuhandbook1` présente mais sans candidat (désactivée par l'upgrade).
- Aucune ligne Howdy active dans PAM (seulement dans des sauvegardes).

## Procédure

```bash
cd /workspace/users/albandrieu30/ansible-workstation

# 1. Audit (lecture seule, sans sudo)
mise run howdy-cameras-audit

# 2. Identifier physiquement chaque caméra
ls -l /dev/v4l/by-path/*video-index0
ffplay /dev/v4l/by-path/<lien-port-3.3>   # ou cheese ; fermer ensuite

# 3. Appliquer (double approbation)
.venv/bin/ansible-playbook -i localhost, -c local playbooks/howdy-cameras.yml \
  -e howdy_cameras_apply=true -e howdy_cameras_apply_approved=true \
  -e motion_camera_device=/dev/v4l/by-path/<caméra-A> \
  -e howdy_camera_device=/dev/v4l/by-path/<caméra-B>

# 4. Enrôlement et test (sans PAM)
sudo howdy add
sudo howdy test

# 5. Vérifier l'arrêt automatique de motion
sudo systemctl start motion && systemctl list-timers motion-autostop.timer
```

Le playbook : réactive la source Howdy existante (aucun PPA ajouté), limite
son origine à la priorité APT 100 (les paquets Ubuntu gardent la priorité),
installe `howdy`, fixe `device_path`, `certainty = 3.5` et `disabled = true`,
fixe `video_device` de motion, installe `motion-autostop.timer` /
`motion-autostop.service` (`Conflicts=motion.service`), puis **échoue
volontairement si le paquet a modifié PAM**.

Pour garder motion actif plus longtemps : `sudo systemctl stop motion-autostop.timer`
après l'avoir démarré, ou `-e motion_autostop_after=15min`.

## Remise en route du 16 novembre 2026

**Symptôme :** Howdy ne fonctionnait plus.

**Causes :**

1. `howdy` était en état `rc` : supprimé par la mise à niveau vers 26.04, sans
   binaire ni module PAM.
2. `python3-dlib 19.24+slimbook9` (source tierce, compilé pour Python 3.12) :
   `import dlib` échoue sous Python 3.14 (`No module named '_dlib_pybind11'`).
   Ubuntu ne fournit pas `python3-dlib` ; le PPA Howdy en a un pour 3.14.
3. Un ImageMagick 7.0.10 et une `libheif` 1.9.1 compilés à la main en 2020 dans
   `/usr/local` masquaient la `libheif` d'Ubuntu : OpenCV (`cv2`) échouait sur
   `libx265.so.179`. Ce même ImageMagick, cassé (`libIlmImf-2_3.so.24`
   absente), masquait aussi dans le `PATH` l'ImageMagick 7.1.2 d'Ubuntu.

**Corrections :**

| Changement | Retour arrière |
| --- | --- |
| Playbook appliqué : Howdy sur le port USB 3.3, motion sur le port 9 (liens `by-path`), `disabled = true` | Voir plus bas |
| `python3-dlib` du PPA épinglé en priorité 1001, puis contrôle `import dlib, cv2, numpy` (playbook) | Retirer la section `python3-dlib` du `.pref` |
| ImageMagick et `libheif` de 2020 déplacés (89 entrées) dans `/usr/local/quarantine-imagemagick-2020/`, arborescence conservée, puis `ldconfig` | Remettre les fichiers à leur place, puis `sudo ldconfig` |

**PAM :** le paquet ajoute Howdy à `/etc/pam.d/common-auth` (profil
`pam-auth-update` `howdy`, avant `pam_unix`), donc aussi à `sudo`, à la
connexion et au verrouillage d'écran. Avec `disabled = true`, le module ne fait
rien.

**Pour activer :**

1. Avec de la lumière (la C310 n'a pas d'infrarouge ; `dark_threshold = 60`) :
   `sudo howdy add`, puis `sudo howdy test`.
2. `sudo howdy config` et passer `disabled = false`.
3. Choisir où Howdy suffit. Via `common-auth`, une photo ouvrirait aussi
   `sudo` : préférer le seul écran de verrouillage, en décochant Howdy dans
   `sudo pam-auth-update` et en l'ajoutant au seul service GDM (activation
   détenue par `nabla-yubikey`).

## Retour arrière

- Fichiers modifiés sauvegardés par Ansible à côté de l'original
  (`config.ini.*~`, `motion.conf.*~`).
- `sudo rm /etc/systemd/system/motion-autostop.{timer,service}
  /etc/systemd/system/motion.service.d/10-autostop.conf && sudo systemctl daemon-reload`
- `sudo apt remove howdy`, supprimer `/etc/apt/preferences.d/ubuntuhandbook1-howdy.pref`.

## Limites de sécurité

- La C310 n'a **pas de capteur infrarouge** : une photo peut tromper Howdy.
  À réserver au confort (verrouillage d'écran), jamais comme facteur unique.
- L'audit remonte `stream_localhost` / `webcontrol_localhost` de motion :
  `off` expose le flux et le contrôle web au LAN (le template historique le
  faisait). Recommandation : `on`.
- Les deux caméras portent le même nom dans les applications de visio ; les
  liens `by-path` dépendent du port USB : ne pas permuter les câbles.
