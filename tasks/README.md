# Workstation role – task layout

Tasks are organized by **category** and loaded from `workstation.yml` in this order:

| # | Category | Purpose |
|---|----------|---------|
| 1 | **System base** | Apt cache, apt utilities, software-properties-common, ubuntu-after-install, base packages |
| 2 | **Editor** | `editor.yml` |
| 3 | **Desktop & GUI** | Screenshot, health, gui, printing, pdf, docs, synergy deps, memory, asdf, desktop, time, cast |
| 4 | **Storage** | `storage_disk.yml`, brew, git |
| 5 | **Build tools** | `build_tools.yml` (gnuplot, scons, ant, ubuntu-make) |
| 6 | **Cloud & sharing** | AWS PPA/tools, Samba |
| 7 | **Communication & media** | Webcam, cloud, security, record, pidgin, zoom |
| 8 | **Development** | Perf, mail, `nodejs.yml`, `mount.yml`, keepass, laptop, cleaning |
| 9 | **Web & containers** | Apache, WebDAV, python, plank, `container.yml`, studio |
| 10 | **Apps & requirements** | Fonts, Eclipse JavaHL, Wine, X11, shellcheck |
| 11 | **System tuning & removals** | `system_tuning.yml`, screensaver, `system_remove.yml` |
| 12 | **Network, backup, misc** | VPN, network, backup, fun, variety, mobile, cpp, gnome, qt, gaming, dev, ai_tools, debug, optimization, php, services, yubikey |

## Extracted task files (from former inline blocks in `workstation.yml`)

- **nodejs.yml** – Node.js PPA, npm, grunt, bower
- **mount.yml** – NFS4 mount points (nabla server); list and opts from `mount_nfs_entries` / `mount_nfs_opts` in defaults
- **keepass.yml** – KeePass2 PPA and package
- **build_tools.yml** – gnuplot, scons, ant, ubuntu-make
- **storage_disk.yml** – Disk/recovery tools, LVM, software-center (legacy)
- **system_tuning.yml** – Grub, preload, ureadahead, perl-doc, galternatives, multisystem
- **system_remove.yml** – Purge avahi, whoopsie, zeitgeist, optional desktops, modemmanager, thunderbird

## Conventions

- **When conditions**: Prefer `ansible_os_family == 'Debian'` for Debian/Ubuntu.
- **Packages**: Use the `apt` module with `name`/`state` and `loop` for lists.
- **Naming**: Task names use `category | Short description` (e.g. `git | Install SCM packages`).
- **Toggles**: Behaviour is controlled by `*_enabled` variables in `defaults/main.yml`.
