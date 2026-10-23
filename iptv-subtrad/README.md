# subtrad — sous-titres IPTV traduits par IA

Récupère les sous-titres d'un flux vidéo (français par défaut), les traduit avec Claude
(indonésien par défaut) et lance la vidéo dans **mpv** ou **VLC** avec les sous-titres traduits.
Fonctionne en replay / VOD (mpv ou VLC) et en **direct** (mpv).

On traduit depuis la piste **française** plutôt que depuis l'anglais : on évite de traduire une
traduction, et le sens est mieux conservé.

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
```

Options utiles : `--depuis fr --vers id` (langues), `--modele` (modèle Claude, défaut
`claude-sonnet-5-5`), `--effort low|medium|high` (défaut `low`, plus rapide et moins cher : la
traduction de sous-titres n'a pas besoin d'une longue réflexion), `--lot 40` (répliques par
requête), `--sme` (préférer les sous-titres pour sourds et malentendants).

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

## Cache

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
| `pipeline.py` | enchaînement : trouver la bonne piste puis la récupérer |

## Limites actuelles et prochaines étapes

- **Direct sans pistes WebVTT** (MPEG-TS brut avec sous-titres intégrés) : non géré, seul le
  direct HLS avec pistes WebVTT l'est.
- **Sous-titres en image** (DVB, PGS) ou **incrustés** : nécessitent de l'OCR (Tesseract).
- **Pas de sous-titres du tout** : transcrire l'audio avec Whisper (faster-whisper), puis traduire.
- **DASH (.mpd)** : pistes TTML/WebVTT à ajouter.
- **Contenu protégé par DRM** (Widevine) : ni mpv ni VLC ne peuvent le lire ; hors du périmètre.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Les tests n'appellent ni le réseau ni l'API : le flux HLS et le client Claude sont simulés.
