# GPU et LLM locaux de la workstation (relevé du 7 novembre 2026)

Matériel : RTX 2060 6 Go (Turing, compute 7.5, pas de bf16), pilote 595.71, i7-9700K 8 cœurs,
62 Go de RAM. Le bureau (GNOME, Chrome, Claude) occupe environ 550 Mio de VRAM.

Chaîne : LiteLLM (conteneur `litellm-litellm-1`, config `~/.litellm/litellm_config.yaml`, liée depuis
nabla-compose `litellm/config.yaml`, non versionnée) appelle ollama 0.40.15 sur `172.17.0.57:11434`.
Modèles dans `/data/models/ollama` : RAID1 de disques durs jusqu'au 11/11 (chargements à froid de 12 à
17 s), puis LV `vg-nvme-crypt/models` sur le NVMe (3 à 8 s). FastAPI Sample (staging TrueNAS) passe par le LiteLLM
de TrueNAS (`fastapi-qwen`), qui relaie vers l'entrée `qwen` de ce LiteLLM.

## Constats

- **Le GPU ne sert presque pas.** En 14 jours, ollama n'a reçu aucune requête de génération
  (3 `GET`, 2 `HEAD`). Les modèles locaux de LiteLLM (`qwen`, `llama3.2`, `embedding`, `rr-json`…)
  ne sont pas appelés.
- **Au-delà de 4B, les modèles débordent sur le CPU et deviennent 20 à 40 fois plus lents.** Mesure
  du 7/11 sous ollama 0.30.11, 256 tokens générés, `think: false`, température 0 :

  | Modèle | Contexte | Placement | Génération | Chargement à froid |
  | --- | --- | --- | --- | --- |
  | `qwen3:4b` | 8192 | 100 % GPU, 3,3 Go | 80 tok/s | 12,7 s |
  | `qwen3:4b` | 32768 | 23 % CPU, 5,4 Go | 1,7 tok/s | 7,4 s |
  | `qwen3.5:4b` | 8192 | 100 % GPU, 3,2 Go | 61 tok/s | 5 s |
  | `qwen3.5:4b` | 32768 | 100 % GPU, 3,7 Go | 61 tok/s | 4,5 s |
  | `qwen3.5:2b` | 8192 | 100 % GPU, 2,5 Go | 80 tok/s | 16,1 s |
  | `gemma3` (4B) | 8192 | 100 % GPU, 2,8 Go | 62 tok/s | 17 s |
  | `qwen2.5-coder:7b` | 8192 / 4096 | 18 % / 16 % CPU | 2,5 / 4,8 tok/s | 25,7 s |
  | `llama3.1:8b` | 8192 / 2048 | 27 % / 19 % CPU | 1,9 / 3 tok/s | 25 s |

  Les poids d'un 7-8B en Q4 (4,7 à 4,9 Go) dépassent ce qui reste une fois le bureau et la réserve
  `OLLAMA_GPU_OVERHEAD` (512 Mio) déduits, même à 2048 de contexte. Pendant la mesure, un `clamscan`
  nocturne occupait aussi un cœur ([stabilisation](stabilisation-workstation-truenas.md#workstation-reste-à-faire), n° 9).
- **ollama 0.40.15 n'accélère rien ici.** Même mesure après la mise à jour : `qwen3.5:4b` à 32k,
  57 tok/s (100 % GPU, 3,7 Go, 14 s à froid) ; `qwen3:4b` à 8k, 75 tok/s ; `llama3.2` à 8k, 98 tok/s.
- **`qwen3.5:4b` tient 32k de contexte dans la carte.** Seules 8 de ses 32 couches gardent un cache
  d'attention complet : passer de 8k à 32k ne coûte que 0,5 Go. Il ajoute la vision et l'appel
  d'outils, pour 57-61 tok/s au lieu de 75-80.
- **`qwen3-embedding:0.6b` ne tient pas à côté.** Avec `qwen3.5:4b` à 32k chargé, il prend 0,9 Go
  (2k de contexte) à 1,4 Go (8k) et passe à 86 % sur le CPU : 15 s pour 32 morceaux de 400 tokens,
  contre 0,5 s pour `nomic-embed-text` (335 Mo, 100 % GPU). `nomic-embed-text` reste l'embedding.
- **Chaque changement de `num_ctx` recharge le modèle.** LiteLLM envoyait 2048, 4096 ou 8192 selon
  l'entrée, et `OLLAMA_MAX_LOADED_MODELS=1` déchargeait le modèle de chat à chaque embedding (RAG).
- **LiteLLM ignorait les réglages de `qwen`.** Ils étaient sous `extra_body`, qu'ollama reçoit hors de
  `options` : `num_ctx: 4096` et l'échantillonnage n'étaient pas appliqués.
- **`llama3.2` renvoyait 404.** LiteLLM (workstation et TrueNAS) demande `llama3.2:3b`, tag absent
  (seul `llama3.2:latest` existait). C'est le repli de `qwen` sur le LiteLLM de TrueNAS.

## vLLM : non

vLLM 0.33 accepte encore le compute 7.5, mais sans FlashAttention 2 (repli Triton), en fp16
seulement, et sa prise en charge GGUF est « expérimentale ». Il réserve la VRAM à l'avance, et il
gère mal le déchargement partiel sur le CPU et le changement de modèle. Sur 6 Go partagés avec le
bureau, pour un seul utilisateur, ollama (llama.cpp) reste le bon choix. vLLM ne se justifie qu'avec
une carte de 16 Go ou plus et des requêtes concurrentes.

## Fait dans ce dépôt

[`stabilize-workstation.yml`](../playbooks/stabilize-workstation.yml) :

| Quoi | Pourquoi |
| --- | --- |
| `nvidia-gpu-textfile.service` ([script](../files/nvidia-gpu-textfile.sh)) : un `nvidia-smi -l 15` écrit `nvidia_gpu_*` (utilisation, VRAM, température, puissance, horloge, ventilateur) dans le dossier textfile de node_exporter | Prometheus (TrueNAS) lit déjà `:9100` : pas de nouveau port, ni de règle ufw, ni de job. Un seul processus, aucune ligne de journal par mesure. |
| Drop-in [`ollama.service.d/workstation.conf`](../files/etc/systemd/system/ollama.service.d/workstation.conf) | Le script d'installation d'ollama réécrit `ollama.service` à chaque mise à jour : sans drop-in, on perd `OLLAMA_MODELS` et tout le réglage. Le drop-in remet aussi un `PATH` court : le script copie celui du shell qui l'a lancé. |
| `OLLAMA_MAX_LOADED_MODELS=2` | Le modèle de chat (2,5-3,7 Go) et l'embedding (0,3 Go) tiennent ensemble. |
| `EnvironmentFile=-/etc/ollama/ollama.env` | Accueille `OLLAMA_API_KEY` (fichier 0600), hors de l'unité lisible par tous. |
| [`ollama.service`](../files/etc/systemd/system/ollama.service) | Copie de l'unité que le script écrit : plus aucun réglage ni secret dedans. |

## Appliqué le 7 novembre, hors dépôt

- ollama 0.30.11 → 0.40.15 (`install.sh` officiel ; il s'arrête avant les pilotes quand `nvidia-smi`
  répond). `OLLAMA_API_KEY` déplacée dans `/etc/ollama/ollama.env` (root, 0600) avant la mise à jour ;
  l'unité réécrite n'en contient plus.
- LiteLLM workstation (sauvegarde `~/.litellm/litellm_config.yaml-2026-11-07`) :
  - `qwen` → `ollama_chat/qwen3.5:4b`, `num_ctx: 32768`, `think: false`, outils et vision déclarés.
    `think: false` arrive bien à ollama, et un `reasoning_effort` envoyé par le client ne le
    réactive pas.
  - `llama3.2` → `ollama_chat/llama3.2`.
  - Entrées `llama3.1`, `llama3.8b` et `deepseek-coder-v2` retirées.
- Modèles supprimés (`ollama rm`, 64 Go libérés sur `/data`) : `llama3.3`,
  `deepseek-coder-v2:16b-lite-base-q2_K`, `llama3:8b`, `llama3.1`, `mistral`, `deepseek-r1:8b`. Tag
  `llama3.2:3b` recréé (même empreinte que `latest`, aucun espace en plus) pour le LiteLLM de TrueNAS.

## Test avec FastAPI Sample (7 novembre)

FastAPI Sample lancé en local (`fastapi run --port 8099`) avec `LITELLM_URL=http://127.0.0.1:4000`,
`DEFAULT_CHAT_MODEL=qwen` et la clé `fastapi-sample-upstream` (celle du second saut TrueNAS →
workstation, limitée à `qwen`). `POST /run`, `qwen3.5:4b` à 100 % GPU :

| Question | Réponse | Durée |
| --- | --- | --- |
| Explication en anglais (sans outil) | Correcte, 2 phrases | 3,9 s (chargement compris) |
| « Who is Alban Andrieu? Use your profile tool. » | Le modèle appelle `fetch_my_profile` ; l'outil échoue : `albanandrieu.com` répond HTTP 402 | 3,1 s |
| Résumé en français | Correct, 1 phrase | 1,4 s |

La chaîne complète depuis TrueNAS (`fastapi-qwen`) n'est pas testée : ses clés ne sont pas encore
injectées (nabla-compose `docs/runbooks/fastapi-sample-litellm.md`).

## Propositions

| # | Proposition | État au 7/11 |
| --- | --- | --- |
| 1 | Révoquer `OLLAMA_API_KEY` (affichée pendant l'audit) et mettre la nouvelle dans `/etc/ollama/ollama.env` | Clé déplacée ; **rotation à faire à la main** sur ollama.com |
| 2 | Mettre ollama à jour | Fait : 0.40.15, aucun gain de vitesse mesuré |
| 3 | `qwen` → `qwen3.5:4b`, 32k, réflexion coupée | Fait, testé avec FastAPI Sample |
| 4 | Code : `qwen3.5:4b` à la place de `qwen2.5-coder:7b` | Aucune entrée LiteLLM ni outil n'utilise `qwen2.5-coder:7b` (4,7 Go) ; gardé, à supprimer si inutile |
| 5 | Retirer les `num_ctx` sous 8192 et les entrées qui débordent sur le CPU | Fait côté workstation. Le LiteLLM de TrueNAS (nabla-compose `apps/litellm/config.yaml`) gardait `llama3.1`, `llama3.8b` et `deepseek-coder-v2`, qui renvoient 404 : **retirés et redéployés le 13/11** ([nabla-compose#371](https://github.com/AlbanAndrieu/nabla-compose/pull/371)) : le LiteLLM de TrueNAS ne les liste plus. La route `qwen` de TrueNAS utilise toujours `qwen3:4b` : ne pas le supprimer |
| 6 | Supprimer les 6 modèles trop gros | Fait, 64 Go libérés |
| 7 | Embedding `qwen3-embedding:0.6b` | Abandonné : 30 fois plus lent, ne tient pas à côté du modèle de chat |
| 8 | `qwen3.5:35b-a3b` (MoE) avec les experts en RAM via `llama-server --n-cpu-moe` ; estimation non mesurée : 12 à 22 tok/s | Pas fait (22 Go à télécharger, llama.cpp à installer) |

Vu pendant les tests, non corrigé :

- Le LiteLLM de la workstation ne s'authentifie pas auprès de Redis (« invalid username-password
  pair », 5 048 fois avant le redémarrage du 7/11) : cache et compteurs de dépenses inactifs. Cause
  et correctif : [stabilisation](stabilisation-workstation-truenas.md#workstation-reste-à-faire), n° 1.
- `fastapi-sample/promptfooconfig.yaml` évalue encore `ollama:chat:llama3:8b`, supprimé.

Relevé du 13/11 : GPU à 43 °C, sans ralentissement, 0,7 Go de VRAM pris par Claude Desktop, Chrome
et Slack ; aucun modèle chargé. En 14 jours, ollama a reçu 55 `/api/generate`, 5 `/api/chat` et
7 `/api/embed` ; LiteLLM, 27 requêtes de chat en 24 h, dont 2 en erreur 500 : les routes Azure
`gpt-4.1` et `gpt-4.1-mini` répondent « Connection error » après 5 essais, et les replis de
`llama3.2` et `gemma3` envoient vers elles les requêtes locales qui échouent. Ces endpoints
appartiennent à une autre organisation : à retirer, ou à confirmer par l'opérateur.
`qwen2.5-coder:7b` s'est chargé avec 0 couche sur 29 sur le GPU, donc sur le CPU seul.
`~/.litellm/litellm_config.yaml` n'est ni versionné ni sauvegardé par Restic.

Pour refaire la mesure : `/api/generate` avec `"think": false`, `num_predict: 256`, température 0,
puis `ollama ps` pour le placement CPU/GPU.

## Choix du modèle du 13/11 : `bonsai-2:9b`

Claude Desktop, Chrome et Slack prennent maintenant 1 Go de VRAM au lieu de 0,55 Go : `qwen3.5:4b` en
32k ne tient plus dans la carte (88 % GPU, 15 à 21 tok/s au lieu de 57). Même banc pour chaque
modèle, ollama 0.40.15, contexte 32k, `think: false`, température 0. Raisonnement : 10 questions à
réponse exacte (horaires, pourcentages, logique, jours de la semaine en français).

| Modèle | GPU | Taille | Génération | Outil, JSON, aiguille dans 10k tokens | Raisonnement |
| --- | --- | --- | --- | --- | --- |
| `bonsai-2:9b` (Qwen3.5 9B ternaire, Q2_0) | 100 % | 3,4 Go | 53 tok/s | oui, oui, oui | **10/10** |
| `qwen3.5:4b` | 88 % | 3,9 Go | 15-21 tok/s | oui, oui, oui | 9/10 |
| `bonsai-2:4b` | 100 % | 2,3 Go | 79 tok/s | oui, oui, oui | 9/10 |
| `qwen3.5:2b` | 100 % | 2,6 Go | 73 tok/s | oui, oui, oui | 9/10 |
| `llama3.2:3b` | 90 % | 4,2 Go | 23 tok/s | oui, oui, oui | 7/10 |
| `qwen3:4b` | 75 % | 5,0 Go | 8 tok/s | oui (tard, voir plus bas), oui, oui | 8/10 |
| `gemma3` (4B) | — | — | — | pas d'appel d'outil (HTTP 400) | — |

`bonsai-2:9b` (Prism ML, Apache 2.0, architecture `qwen35`, 9,0 milliards de paramètres) est un
9B qui pèse le poids d'un 4B : vision, outils et 262k de contexte. Mis en place :

- LiteLLM workstation : `qwen` → `ollama_chat/bonsai-2:9b`, toujours 32k et `think: false`
  (sauvegarde `~/.litellm/litellm_config.yaml-2026-11-13`). Vérifié à travers LiteLLM : réponse en
  1 s, `get_weather(Lyon)` appelé, image décrite, 100 % GPU.
- `nomic-embed-text` chargé à côté passe à 74 % CPU : 32 morceaux de 400 tokens en 1,75 s au lieu de
  0,5 s. Acceptable pour 7 appels d'embedding en 14 jours.
- Non retenus : `qwen3.5:9b` en Q4 (6,6 Go, déborde) ; `qwen3.5:35b-a3b` (22 Go, 15 Go libres sur le
  LV des modèles, surtout sur le CPU) ; Gemma 4 E4B (6,6 Go et plus).

Retour arrière : remettre `ollama_chat/qwen3.5:4b` dans l'entrée `qwen`, puis
`docker restart litellm-litellm-1`. Il déborde même en 16k (15 % CPU, 36 tok/s, embedding chargé).

Vérifié le 14/11 :

- **`qwen3:4b` appelle bien l'outil, mais tard.** Même avec `think: false`, il écrit d'abord 340 tokens
  de réflexion dans la réponse visible (« Okay, the user is asking… ») : le banc, limité à 256 tokens,
  coupait avant l'appel. Il faut 9 s en 8k et 398 s en 32k (débordement CPU), contre 27 tokens et
  moins d'une seconde pour `bonsai-2:9b`.
- **`think` ne recharge pas le modèle** (chargement à 0 s), seul `num_ctx` le fait. Avec la réflexion,
  `bonsai-2:9b` passe de 9 à 30 s sur une question d'horaire, de 27 à 76 tokens sur un appel d'outil.
- **Open WebUI** (TrueNAS, `DEFAULT_MODELS=qwen`) passe par la route `qwen` du LiteLLM de TrueNAS,
  servie par `bonsai-2:9b` depuis nabla-compose#373, déployée le 14/11 : chat, `get_weather(Lyon)` et
  image vérifiés à travers le LiteLLM de TrueNAS, aucun rechargement sur la workstation.
- **Reactive Resume** (route `rr-json`, `qwen2.5:3b` en 8k) : avec son vrai prompt de chat et son
  outil `patch_resume`, `bonsai-2:9b` réussit 3 modifications sur 3 (remplacer, ajouter avec `-`,
  supprimer), `qwen2.5:3b` 2 sur 3 (aucun appel pour un ajout). Sortie JSON structurée correcte pour
  les deux. Les deux modèles ne tiennent pas ensemble sur le GPU : alterner les routes les recharge.

## Un seul modèle de chat sur le GPU (14/11)

Règle : toute route LiteLLM vers l'ollama de la workstation utilise `bonsai-2:9b` avec
`num_ctx: 32768`. `think` ne recharge pas le modèle, un autre modèle ou un autre `num_ctx` si.

| Route | Réglage | Clients |
| --- | --- | --- |
| `qwen` | `think: false` | Open WebUI, OpenRAG, FastAPI Sample (`fastapi-qwen`), Homarr, Langfuse |
| `qwen-think` | `think: true`, environ 3 fois plus lent | à choisir dans Open WebUI pour les questions difficiles |
| `rr-json` | `think: false`, température 0 | Reactive Resume |
| `embedding` | `nomic-embed-text`, 2e modèle autorisé (`OLLAMA_MAX_LOADED_MODELS=2`) | RAG, mémoire d'OpenClaw |

- Workstation (`~/.litellm/litellm_config.yaml`, sauvegarde `-2026-11-14`) : `qwen-think` ajoutée,
  `llama3.2` et `gemma3` retirées avec leurs replis. En alternant `qwen`, `qwen-think` et `rr-json`
  à travers LiteLLM : aucun chargement de modèle dans le journal d'ollama, une seule instance.
- TrueNAS ([nabla-compose#374](https://github.com/AlbanAndrieu/nabla-compose/pull/374)) : mêmes
  routes, et `default_fallbacks` passe de `llama3.2` à `qwen` (toute route en échec chargeait
  `llama3.2` sur le GPU). Un test vérifie la règle sur chaque route vers `172.17.0.57:11434`.
  **Déployé le 14/11.** La clé `openwebui` autorise désormais `qwen`, `qwen-think`,
  `workstation-qwen`, `gpt-4.1(-mini)` et `embedding` (mise à jour par `/key/update` : le script
  d'enregistrement ne touche pas une clé existante). Vérifié depuis le conteneur Open WebUI, avec
  sa clé : ces six modèles listés ; `qwen` 2,4 s, `qwen-think` 8,6 s avec réflexion ; `llama3.2`
  refusé (403) ; `rr-json` répond aussi par TrueNAS. Aucun chargement de modèle sur la workstation.
- OpenClaw n'utilise aucun modèle de chat local : `gpt-4.1` et l'embedding seulement.
- Non vérifié : les flows Langflow (choix du modèle stocké dans sa base) ; les appels directs à
  ollama, hors LiteLLM, peuvent toujours demander un autre modèle tant qu'il est installé.
