# Workstation — utiliser Nexus Repository comme cache de dépendances

**État du plan : 23 novembre 2026 — playbook client `CODED`, `TESTED` (plan et refus) ; HTTPS privé `nexus.int` et Maven `DEPLOYED`, miroir Maven de la workstation en HTTPS `nexus.int` ; dépôts APT/npm/PyPI/Docker toujours absents.** Le retrait de pfSense le 18/11 est pris en compte. Les scripts et politiques Ubuntu appartiennent ici ; les dépôts, TLS/Traefik, bases et snapshots Nexus restent dans [nabla-compose](https://github.com/AlbanAndrieu/nabla-compose/tree/master/terraform/nexus).

## État constaté dans Git, pas au runtime

- [Compose Nexus](https://github.com/AlbanAndrieu/nabla-compose/blob/master/apps/nexus/compose.yml) : image `sonatype/nexus3:3.92.3-alpine`, mémoire maximum 5 Gio, stockage persistant `/mnt/cpool/nexus3`, HTTP 8081 lié à `172.17.0.24` ; routeur Traefik privé `nexus.int` actif depuis la PR #438 (22/11).
- `nexus.albandrieu.com` passe par Cloudflare Access (service token CI) puis Traefik + CrowdSec : **réservée à la CI**. Les clients de la workstation utilisent `nexus.int.albandrieu.com`.
- [OpenTofu Nexus](https://github.com/AlbanAndrieu/nabla-compose/tree/master/terraform/nexus) déclare déjà `apt-ubuntu-26-04`, `npm-all`, `pypi-all`, `docker-all`, `terraform-proxy`, Hugging Face et d'autres dépôts. **Créé dans le code ≠ présent dans l'instance** : contrôler l'API des dépôts avec des droits read-only, puis `tofu plan` avant toute écriture.
- `repo-apt.tofu` cible `archive.ubuntu.com/ubuntu/` (`resolute`) et, depuis le 22/11, `security.ubuntu.com/ubuntu/` (`apt-ubuntu-26-04-security`, `resolute-security`).
- **Bloquants du premier `tofu plan`** (relevé du 23/11) : le module hérite d'un gabarit 1Password (`data "onepassword_vault"`, `onepassword_item` pour les utilisateurs `home-ops`/`albandrieu`) alors que les secrets sont dans Vaultwarden/`pass` ; `sonatyperepo_security_realms` remplace la liste des realms actifs ; tout le module (7 proxies Docker, Hugging Face, Terraform) s'applique d'un bloc, sans pilote par format. À corriger dans `nabla-compose` avant l'`apply`.
- `repo-docker.tofu` configure `path_enabled=true` et `v1_enabled=true` pour les proxies (groupe V1 désactivé). Étudier la désactivation V1 sur tous les proxies après avoir vérifié les clients requis, sans casser le cache existant.

## État constaté au runtime (22/11/2026, lecture seule depuis la workstation)

| Contrôle | Résultat |
| --- | --- |
| `http://172.17.0.24:8081/service/rest/v1/status` | 200, `Server: Nexus/3.92.3-01 (COMMUNITY)` |
| Dépôts visibles en anonyme | 9 : `maven-central`, `maven-public`, `maven-releases`, `maven-snapshots`, `nabla-releases`, `nabla-snapshots`, `nuget-group`, `nuget-hosted`, `nuget.org-proxy` |
| `apt-ubuntu-26-04`, `npm-all`, `npm-proxy`, `pypi-all`, `pypi-proxy`, `docker-all`, `terraform-proxy` | **404 : jamais créés** ; l'OpenTofu `nabla-compose/terraform/nexus` n'a pas été appliqué |
| `maven-central` en anonyme | 200 : lecture anonyme active |
| `nexus.int.albandrieu.com` | résolu par Pi-hole vers `172.17.0.24` ; HTTPS avec certificat valide (Traefik), puis 404 : le routeur privé est désactivé (`NEXUS_PRIVATE_INGRESS_ENABLED`) |

### Relevé du 23/11/2026 (lecture seule depuis la workstation)

| Contrôle | Résultat |
| --- | --- |
| `https://nexus.int.albandrieu.com/service/rest/v1/status` | 200, certificat vérifié |
| Dépôts visibles en anonyme | toujours les 9 Maven/NuGet ; `apt-ubuntu-26-04*`, `npm-all`, `pypi-all`, `docker-all` en 404 |
| `playbooks/nexus-clients.yml` (check) | 5 sondes en 404 : bascule refusée, aucun changement |
| Maven de la workstation (`~/.m2/settings.xml`, miroir `nexus`) | résolvait via `http://172.17.0.24:8081/repository/maven-public/` (**HTTP clair**) jusqu'à la bascule ci-dessous |
| Maven via `https://nexus.int.albandrieu.com/repository/maven-public/` (settings temporaire, anonyme) | `BUILD SUCCESS`, truststore Java OK |
| CI via `nexus.albandrieu.com` + service token Access | `200 application/java-archive` (22/11) |

**Maven de la workstation : `APPLIQUÉ` le 23/11 à 22 h 48.** Le miroir `nexus` (`mirrorOf *`) de `~/.m2/settings.xml` pointe `https://nexus.int.albandrieu.com/repository/maven-public/` (fichier utilisateur 0600, hors Git, seule l'URL a changé). Contrôle avec un dépôt local vide (`-Dmaven.repo.local`, `maven-dependency-plugin:3.8.1:get` de `commons-lang3:3.17.0`) : `BUILD SUCCESS`, 219 artefacts tous servis par `nexus.int` en HTTPS, aucune requête vers `172.17.0.24`. L'identifiant `nexus` ne change pas : le cache `~/.m2/repository` reste valide. Aucun autre client de la workstation (`.npmrc`, `pip.conf`, `uv.toml`, Gradle, Docker, `.terraformrc`) n'utilisait `:8081`. Retour arrière : `cp -p ~/.m2/settings.xml.bak-20261123 ~/.m2/settings.xml`. Le port 8081 reste exposé sur le LAN par Compose, pour le diagnostic sans secret (voir plus bas).

## Bascule des clients : `playbooks/nexus-clients.yml`

`mise run nexus-clients-check` sonde désormais **cinq chemins** en HTTPS : `resolute`, `resolute-updates`, `resolute-security`, npm et PyPI. Le mode par défaut affiche le plan sans sudo ni changement. L'écriture exige `-e nexus_apply=true -e nexus_apply_approved=true -K` et refuse toute réponse différente de **200**, tout hôte autre que `nexus.int.albandrieu.com`, ou des métadonnées Ubuntu `InRelease` qui ne commencent pas par `-----BEGIN PGP SIGNED MESSAGE-----`. Les réponses des sondes sont masquées dans les logs Ansible. Ce contrôle de format ne remplace **pas** la vérification cryptographique `Signed-By` par APT après activation. Aucun déploiement n'est attesté ici. Elle écrit :

- `/etc/apt/sources.list.d/ubuntu.sources` : mêmes suites, `-security` par son propre proxy, `Signed-By` Ubuntu conservé ; l'original est sauvegardé à côté (`backup`) ;
- `/etc/profile.d/nexus-package-cache.sh` : `NPM_CONFIG_REGISTRY`, `PIP_INDEX_URL`, `UV_DEFAULT_INDEX`. Les fichiers utilisateur `.npmrc`, `pip.conf` et `uv.toml`, qui peuvent porter des jetons, ne sont pas touchés.

Retour arrière : `sudo rm /etc/profile.d/nexus-package-cache.sh`, puis restaurer la sauvegarde de `ubuntu.sources` et `sudo apt-get update`. Un pilote limité à une session reste possible sans le playbook : `NPM_CONFIG_REGISTRY=… npm ci`.

Ordre pour lever le NO-GO : `tofu apply` de `terraform/nexus` (nabla-compose), routeur privé Traefik activé, `mise run nexus-clients-check` à 5 × 200, métadonnées `InRelease` reconnues, puis l'application.

Routes (nabla-compose [#438](https://github.com/AlbanAndrieu/nabla-compose/pull/438), `CODED` le 22/11) : la workstation et OpenTofu passent par `nexus.int.albandrieu.com` (routeur Traefik `nexus-private`, allowlist LAN), jamais par Cloudflare. La CI (Maven, jeton de service Access) garde `nexus.albandrieu.com`, qui passera par Traefik + CrowdSec (`nexus-public`) une fois `nexus_tunnel_via_traefik` appliqué. `nexus.albandrieu.com` ne convient pas aux clients APT/npm/pip : ils ne savent pas envoyer les en-têtes Access.

## Prérequis obligatoires — NO-GO tant que non prouvés

1. **DNS/TLS privé — fait le 22/11 pour `nexus.int` :** résoudre `nexus.int.albandrieu.com` sur Pi-hole TrueNAS `172.17.0.24`, activer le routeur Traefik privé seulement après preuve TLS/SNI et accès LAN ; certificat avec SAN exact, vérification activée, aucun `insecure-registries`, `trusted=yes`, `--trusted-host` ou `strict-ssl=false`.
2. **Édition et capacité :** relever l'édition réellement installée, version, métriques de composants et requêtes/jour. Community Edition : **40 000 composants / 100 000 requêtes par jour** ; Repository Firewall, quarantaine des malwares, conformité FIPS et SSO selon édition/licence. Un proxy n'est pas une analyse de vulnérabilités.
3. **Données :** test de sauvegarde/restauration du dataset `cpool/nexus3` et de la base réellement utilisée avant montée de version ; mesurer stockage, latence et mémoire JVM. L'édition 3.98.3 du 19/11/2026 corrige notamment CVE-2026-114938 et limite l'exécution Groovy par défaut : préparer une mise à jour **dans Compose**, pas sur la workstation.
4. **Accès :** lecture anonyme uniquement si le LAN et les repositories le justifient ; sinon jeton à droits minimaux stocké hors Git. Ne pas imprimer ou transmettre `.npmrc`, `pip.conf`, `auth.json` ou des `Authorization`.
5. **Résilience :** le proxy ne doit pas devenir une dépendance de démarrage bloquante si TrueNAS est indisponible. Procédure de rollback documentée vers les **sources officielles signées**, sans désactiver APT Secure.

## Déploiement proposé : pilotes successifs

| Lot | Configuration envisagée | Validation avant promotion |
| --- | --- | --- |
| N1 — APT Ubuntu 26.04 | Conserver `Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg` et les `InRelease` Ubuntu en mode passthrough ; sources `https://nexus.int.albandrieu.com/repository/apt-ubuntu-26-04/` pour `resolute`, `resolute-updates`, `resolute-backports` **uniquement si les trois suites sont effectivement servies**. Laisser `resolute-security` sur `security.ubuntu.com` tant que le proxy sécurité dédié n'est pas fonctionnel | Sur fichier `.sources` de test isolé : `apt-get update` et installation de test avec signature valide ; APT security, ESM et dépôts tiers restent fonctionnels. Appliquer via Ansible opt-in, jamais en remplaçant `/etc/resolv.conf` |
| N2 — npm | Registry `https://nexus.int.albandrieu.com/repository/npm-all/` pour une session pilote ; `npm ci` avec lockfile, vérifier les URL `resolved` qui peuvent contourner le proxy. Stocker l'authentification hors dépôt | Paquets `@scope`, somme `integrity`, `npm audit`/SCA indépendante, repli direct contrôlé |
| N3 — Python `uv`/`pip` | Index unique `https://nexus.int.albandrieu.com/repository/pypi-all/simple/` via `UV_INDEX_URL` ou `PIP_INDEX_URL` pour un pilote. Éviter un `extra-index-url` public avec les mêmes noms privés (dependency confusion) ; ne pas committer les jetons ni les URL avec credentials | `uv lock --check`, `uv sync --frozen`, `pip index versions` sur projet isolé ; comparer empreintes/hashes et comportement de résolution |
| N4 — Docker / OCI | `docker-all` dispose de `path_enabled=true` mais **Docker ne sait pas employer directement un chemin `/repository/docker-all` comme `registry-mirrors`**. Choisir et valider la stratégie officielle path-based, sous-domaine privé ou reverse-proxy `/v2/` avant configuration client. Pour Docker Hub seul, un miroir dédié peut être choisi ; GHCR, Quay, etc. gardent leurs noms de registre explicites | `docker manifest inspect` puis `pull` par digest signé, réponse `/v2/`, jeton DockerToken, TLS, pas de port public ajouté |
| N5 — Terraform, Ansible, Hugging Face | Étendre seulement après N1–N4 et inventaire des besoins ; vérifier les clients et les changements récents de protocoles | Cache utile mesuré, tests de compatibilité, SCA/SBOM toujours indépendants |

**Sécurité des clés APT :** `signed-by` vérifie une clé explicitement autorisée ; **ne pas** utiliser `apt-key add`, `trusted=yes` ou supprimer les contrôles de signature pour obtenir un cache fonctionnel. Le proxy APT sans signature locale transmet les métadonnées amont ; si une signature Nexus est activée, son changement de racine de confiance doit faire l'objet d'une revue distincte.

**Routage réseau actuel :** Freebox en routeur, R7000 `172.17.0.1` comme passerelle LAN, TrueNAS/Pi-hole `172.17.0.24`, workstation `172.17.0.57`. L'adresse du R7000 **ne doit plus être interprétée comme un résolveur pfSense**. Le split DNS du poste utilise Pi-hole et le DNS public Quad9 ; mesurer les effets sur les conteneurs avant changement de `daemon.json`.

## Consommation, sécurité et maintenance

- Community Edition : relever dans Usage Center le nombre de composants et les requêtes/jour **avant de multiplier les caches** ; surveiller le comportement de la télémétrie obligatoire (3.98 : délai de grâce 30 jours si échec d'envoi).
- Nettoyer **uniquement les proxies** après une période d'observation : preview de `unused-proxy-90d`, puis cleanup et compaction, jamais d'effacement automatique des hosted. Tenir compte des snapshots ZFS et de leur rétention.
- Ne pas présenter Nexus comme un WAF/EDR ou Repository Firewall gratuit : conserver CodeQL, Trivy, pip-audit, npm audit, SBOM et les résultats OpenSCAP/Lynis.
- Exposition : l'accès HTTP 8081 sur le LAN peut servir aux diagnostics sans secret, **pas comme source permanente authentifiée**. Refus WAN négatif depuis un observateur extérieur et protection du tunnel à vérifier séparément.

## Références vérifiées au 21/11/2026

- [Sonatype : notes 3.98.0–3.98.3](https://help.sonatype.com/en/sonatype-nexus-repository-3-98-0-release-notes.html)
- [Sonatype : formats APT proxy/hosted et signatures](https://help.sonatype.com/en/apt-repositories.html)
- [Sonatype : configuration Docker Registry et routage](https://help.sonatype.com/en/docker-registry.html)
- [Sonatype : configuration PyPI](https://help.sonatype.com/en/configure-pypi-with-nexus.html)
- [Sonatype : éditions et fonctionnalités](https://help.sonatype.com/en/nexus-repository-tiers-and-feature-availability.html)
- [Sonatype : Usage Center](https://help.sonatype.com/en/usage-center.html)

**État de validation :** source GitHub et documentation Sonatype consultées ; aucun accès à l'API Nexus TrueNAS, aucun `tofu plan`, aucune authentification CLI, aucun changement des fichiers APT, npm, pip ou Docker. Toutes les preuves de déploiement sont **NOT_RUN**.
