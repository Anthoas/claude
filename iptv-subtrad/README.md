# subtrad — sous-titres IPTV traduits par IA

Récupère les sous-titres d'un flux vidéo (français par défaut), les traduit avec Claude
(indonésien par défaut) et lance la vidéo dans **mpv** ou **VLC** avec les sous-titres traduits.
Fonctionne en replay / VOD (mpv ou VLC) et en **direct** (mpv).

On traduit depuis la piste **française** plutôt que depuis l'anglais : on évite de traduire une
traduction, et le sens est mieux conservé.

> **Pas développeur ? Sur Mac ?** Suis la [notice pas à pas](NOTICE-MAC.md).

## Installation

Prérequis : Python 3.10+, [mpv](https://mpv.io) (recommandé) ou [VLC](https://www.videolan.org),
et [ffmpeg](https://ffmpeg.org) pour les sous-titres intégrés au flux.

```bash
cd iptv-subtrad
pip install -e .            # ou : pip install -e ".[dev]" pour lancer les tests
export ANTHROPIC_API_KEY=sk-ant-...
```

## Utilisation

```bash
# Interface graphique dans Chrome : coller le lien M3U, rechercher, vérifier, regarder
subtrad gui

# Lister les chaînes d'une playlist M3U (URL ou fichier local)
subtrad chaines ma_playlist.m3u --filtre arte

# Voir quelles pistes de sous-titres un flux propose
subtrad pistes "https://exemple.fr/film/master.m3u8"

# Récupérer, traduire et regarder : replay / VOD ou direct, détecté automatiquement
subtrad regarder "https://exemple.fr/film/master.m3u8"
subtrad regarder "https://exemple.fr/film/master.m3u8" --lecteur vlc --sme

# Direct : réglages de la marge de traduction et de la synchro
subtrad regarder "https://exemple.fr/direct/master.m3u8" --marge 8 --decalage -0.5

# Traduire un fichier de sous-titres déjà téléchargé
subtrad traduire episode.fr.srt -o episode.id.srt

# Tester sans flux : scène de 2 minutes en français, traduction affichée puis lue dans mpv
subtrad demo
subtrad demo --modele claude-sonnet-5-5   # modèle plus puissant (~20x plus cher), pour comparer
```

Options utiles : `--depuis fr --vers id` (langues), `--modele` (modèle Claude, défaut
`claude-haiku-5-5`, ~5 centimes pour un film ; `claude-sonnet-5-5` coûte ~20x plus), `--effort low|medium|high` (défaut `low`, plus rapide et moins cher : la
traduction de sous-titres n'a pas besoin d'une longue réflexion), `--lot 40` (répliques par
requête), `--sme` (préférer les sous-titres pour sourds et malentendants).

## Vitesse

- **Sous-titres intégrés à un MKV** : lecture rapide grâce à l'index du fichier (« Cues ») et
  à des requêtes HTTP « Range » : seuls les sous-titres sont téléchargés (~1 % du fichier),
  en quelques secondes au lieu de lire toute la vidéo. Repli automatique sur la lecture
  complète par ffmpeg si l'index ou le serveur ne le permettent pas (`mkv.py`).
- **Lecture complète** (MP4, MKV sans index) : les répliques sortent au fil de la lecture
  (`ffmpeg -flush_packets 1`) et partent aussitôt en traduction.
- **Traduction** : 4 lots envoyés en parallèle (`TranslationPipeline`), en même temps que la
  récupération des sous-titres.
- **Démarrage rapide** (lecteur mpv) : la vidéo démarre dès les premières répliques traduites,
  la suite est dessinée par-dessus l'image pendant la lecture. VLC, lui, attend la fin.

## Whisper

Sans sous-titres en texte, la voix est transcrite sur la machine (`transcribe.py`) :
- **whisper.cpp** (`brew install whisper-cpp`), utilisé en priorité : binaire déjà compilé
  (Metal sur Mac Apple), aucune dépendance Python ; le modèle `ggml-large-v3-turbo-q5_0.bin`
  (~550 Mo) est téléchargé dans `~/.cache/subtrad/whisper/` au premier usage ;
- **faster-whisper** (`pip install ".[whisper]"`), pour les autres systèmes.

Le son est lu par ffmpeg, découpé en morceaux de ~30 s sur les silences, et les
« hallucinations » connues de Whisper ([BLANK_AUDIO], « Sous-titres réalisés par… ») sont
retirées. `subtrad transcrire URL` produit un .srt sans traduire ; `subtrad regarder
--transcrire` l'utilise en repli.

## Le direct

La commande `regarder` reconnaît un direct (playlist HLS sans `#EXT-X-ENDLIST`) et passe dans
ce mode. Il demande **mpv** : VLC ne permet pas d'afficher des sous-titres au fil de l'eau.

- Un thread suit la playlist de sous-titres (deux fois par durée de segment), télécharge les
  nouveaux segments WebVTT et fait traduire les nouvelles répliques, avec les précédentes en
  contexte.
- mpv lit le flux **`--marge` segments derrière le direct** (6 par défaut, soit ~36 s avec des
  segments de 6 s) : c'est le temps laissé à la traduction pour arriver avant l'image.
- Les répliques sont calées sur l'horloge réelle du flux (`X-TIMESTAMP-MAP` des segments
  WebVTT, horloge MPEG-TS à 90 kHz) et dessinées en surimpression par mpv au bon moment.
- Si une traduction échoue (réseau, API), la réplique française s'affiche et le direct continue.

Réglages : `--marge N` si des sous-titres arrivent en retard, `--decalage S` si le texte est
en avance (S < 0) ou en retard (S > 0) sur la parole, `--taille` pour la taille du texte.

## Mémoire par vidéo

`store.py` garde dans `~/.cache/subtrad/videos/` les sous-titres d'origine (JSON) et la traduction
terminée (.srt) de chaque vidéo, et où en est sa lecture (`progress.json`), sous des noms dérivés d'une empreinte de l'adresse (jamais l'adresse
elle-même, qui contient souvent identifiant et mot de passe). Une vidéo déjà traduite s'ouvre
aussitôt, sans clé ni coût ; seul un travail complet est gardé (ni annulation, ni lot en échec).
Le badge « déjà traduit » et le bouton « Refaire » de la page s'appuient dessus.

## Accès depuis la télé

Activé dans ⚙ Réglages (« Regarder sur la télé »), `tele.py` ouvre un second serveur sur le port
8766 (`subtrad gui --port-tele N` pour un autre), joignable depuis le Wi-Fi de la maison pour
l'application Android TV. La page du Mac reste limitée à 127.0.0.1.

- Seules les adresses privées (réseau local) sont acceptées ; jamais d'ouverture sur Internet.
- Chaque requête porte l'en-tête `X-Subtrad-Code` : le code à 6 chiffres affiché dans les
  réglages (bouton « Changer le code »). 10 codes faux d'affilée bloquent l'appareil 5 minutes.
- La télé ne lance aucun lecteur sur le Mac : elle demande une **préparation** (récupération et
  traduction complètes, gardées dans la mémoire par vidéo), puis lit le flux avec le .srt.

| Requête | Rôle |
|---|---|
| `GET /tele/api/info` | nombre d'entrées, langue et nom de la piste traduite |
| `GET /tele/api/search?q=&kind=&group=&offset=&limit=` | recherche (avec `ready` par vidéo) |
| `GET /tele/api/groups?kind=` | catégories |
| `GET /tele/api/ready` | vidéos déjà traduites |
| `GET /tele/api/video?id=` | détails d'une vidéo, **adresse du flux comprise** |
| `POST /tele/api/check` `{"id"}` | sous-titres disponibles ? (sans frais) |
| `POST /tele/api/prepare` `{"id"}` | préparer (réutilise une préparation en cours) |
| `GET /tele/api/jobs` | préparations demandées par la télé (20 dernières, `channel_id` = vidéo) |
| `GET /tele/api/job?id=` | avancement d'une préparation |
| `POST /tele/api/cancel` `{"id"}` | annuler une préparation |
| `POST /tele/api/forget` `{"id"}` | supprimer une vidéo prête (traduction et sous-titres d'origine) |
| `POST /tele/api/progress` `{"id","position","duration","ended"}` | où en est la lecture (ms) ; « vu » au-delà de 90 % ou à la fin |
| `GET /tele/api/subtitles?id=` | le .srt traduit (404 tant qu'il n'est pas prêt) |

Les directs ne sont pas encore proposés à la télé.

### Catalogue Xtream Codes (`xtream.py`)

Quand le lien de la playlist est de la forme `…/get.php?username=…&password=…`, le même compte
donne accès à `player_api.php` : séries regroupées par saison, films, affiches, résumés, genres,
notes. Le catalogue est gardé dans `~/.cache/subtrad/xtream/catalog.json` (fichier privé) et
rechargé une fois par jour ; le détail d'une série est gardé une heure. Chaque épisode et chaque
film est relié à son entrée de la playlist par son numéro (`/series/…/<id>.<ext>`), si bien que
préparation, sous-titres et lecture utilisent les adresses habituelles (`id` = entrée de la playlist,
`-1` si absente). Les images qui contiennent l'identifiant, le mot de passe ou l'adresse d'un
serveur du fournisseur ne sont jamais transmises. Langue : `lang=FR` par défaut (préfixe du nom),
`lang=` pour tout.

| Requête | Rôle |
|---|---|
| `GET /tele/api/catalog` | `{"available": true}` si le lien est Xtream Codes |
| `GET /tele/api/catalog/categories?type=series\|movie&lang=FR` | catégories non vides, avec leur nombre |
| `GET /tele/api/catalog/series?category=&q=&offset=&limit=` | séries (nom, affiche, année, note, genre) |
| `GET /tele/api/catalog/series/info?id=SERIES_ID` | fiche : résumé, genre, saisons, épisodes (`id`, titre, image, durée, `ready`, `watched`, `progress`) et `next` (épisode à regarder) |
| `GET /tele/api/catalog/movies?category=&q=&offset=&limit=` | films (`vod_id`, `id`, affiche, `ready`) |
| `GET /tele/api/catalog/movie?id=VOD_ID` | fiche d'un film : résumé, durée, genre, `id`, `ready` |

Attention : l'abonnement actuel n'autorise **qu'une connexion vidéo à la fois**
(`max_connections: 1`). Une préparation sur le Mac pendant une lecture sur la télé peut être
coupée par le serveur (la reprise automatique de ffmpeg limite le problème).

## Cache

Chaque traduction affiche à la fin son coût estimé (tokens et dollars). Les prix sont dans
`PRICES` (`translate.py`).

Les traductions sont mises en cache dans `~/.cache/subtrad/translations.sqlite` : relancer un
même épisode ne coûte rien.

## Fonctionnement

```
flux (.m3u8 / .ts / .mkv)
  │
  ├─ HLS avec pistes WebVTT ─────► hls.py      (cas le plus courant, le plus rapide)
  └─ sous-titres texte intégrés ─► extract.py  (repli via ffprobe / ffmpeg)
  │
  ▼
répliques FR ──► translate.py (Claude, lots de 40, contexte des répliques précédentes, cache)
  │
  ▼
répliques ID ──► replay : fichier .srt ──► player.py (mpv ou VLC, --sub-file)
               └► direct : live.py ──► surimpression mpv calée sur l'horloge du flux
```

| Module | Rôle |
|---|---|
| `playlist.py` | lecture des playlists M3U IPTV (`#EXTINF`, `group-title`, `tvg-logo`...) |
| `hls.py` | pistes `#EXT-X-MEDIA:TYPE=SUBTITLES`, téléchargement et fusion des segments `.vtt` |
| `extract.py` | sous-titres intégrés au conteneur (SRT, ASS, mov_text...) via ffmpeg |
| `subtitles.py` | modèle `Cue` et conversions SRT / VTT / ASS (pysubs2) |
| `translate.py` | traduction par lots avec Claude, sortie JSON structurée, découpage si réponse trop longue |
| `cache.py` | cache SQLite des traductions |
| `live.py` | direct : suivi de la playlist, traduction au fil de l'eau, affichage synchronisé |
| `player.py` | lancement de mpv (pilotage par IPC, surimpression) ou VLC |
| `pipeline.py` | choix de la source : HLS, MKV indexé, lecture complète, Whisper |
| `mkv.py` | lecture rapide des sous-titres d'un MKV via son index et des requêtes « Range » |
| `transcribe.py` | transcription Whisper : découpage du son, moteurs whisper.cpp / faster-whisper |
| `gui.py`, `gui.html` | interface graphique : serveur local (127.0.0.1, jeton de session) et page web |
| `tele.py` | accès télé : serveur sur le Wi-Fi de la maison, protégé par un code |
| `xtream.py` | catalogue Xtream Codes (séries par saison, films, affiches, résumés) |

## Limites actuelles et prochaines étapes

- **Direct sans pistes WebVTT** (MPEG-TS brut avec sous-titres intégrés) : non géré, seul le
  direct HLS avec pistes WebVTT l'est.
- **Sous-titres en image** (DVB, PGS) ou **incrustés** : nécessitent de l'OCR (Tesseract).
- **Whisper en direct** : pas encore géré (films et séries seulement).
- **MP4 avec sous-titres** : pas encore de lecture rapide (l'index MP4 le permettrait aussi).
- **DASH (.mpd)** : pistes TTML/WebVTT à ajouter.
- **Contenu protégé par DRM** (Widevine) : ni mpv ni VLC ne peuvent le lire ; hors du périmètre.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Les tests n'appellent ni le réseau ni l'API : le flux HLS et le client Claude sont simulés.
