# subtrad — sous-titres IPTV traduits par IA

Récupère les sous-titres d'un flux vidéo (français par défaut), les traduit avec Claude
(indonésien par défaut) et lance la vidéo dans **mpv** ou **VLC** avec les sous-titres traduits.

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

# Récupérer, traduire et regarder (replay / VOD)
subtrad regarder "https://exemple.fr/film/master.m3u8"
subtrad regarder "https://exemple.fr/film/master.m3u8" --lecteur vlc --sme

# Traduire un fichier de sous-titres déjà téléchargé
subtrad traduire episode.fr.srt -o episode.id.srt
```

Options utiles : `--depuis fr --vers id` (langues), `--modele` (modèle Claude, défaut
`claude-opus-5-5`), `--effort low|medium|high` (défaut `low`, plus rapide et moins cher : la
traduction de sous-titres n'a pas besoin d'une longue réflexion), `--lot 40` (répliques par
requête), `--sme` (préférer les sous-titres pour sourds et malentendants).

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
répliques ID ──► fichier .srt ──► player.py (mpv ou VLC, --sub-file)
```

| Module | Rôle |
|---|---|
| `playlist.py` | lecture des playlists M3U IPTV (`#EXTINF`, `group-title`, `tvg-logo`...) |
| `hls.py` | pistes `#EXT-X-MEDIA:TYPE=SUBTITLES`, téléchargement et fusion des segments `.vtt` |
| `extract.py` | sous-titres intégrés au conteneur (SRT, ASS, mov_text...) via ffmpeg |
| `subtitles.py` | modèle `Cue` et conversions SRT / VTT / ASS (pysubs2) |
| `translate.py` | traduction par lots avec Claude, sortie JSON structurée, découpage si réponse trop longue |
| `cache.py` | cache SQLite des traductions |
| `player.py` | lancement de mpv (avec IPC pour recharger les sous-titres) ou VLC |
| `pipeline.py` | enchaînement : trouver la bonne piste puis la récupérer |

## Limites actuelles et prochaines étapes

- **Direct (TV en live)** : pas encore géré, la commande `regarder` le signale. Prochaine étape :
  interroger la playlist de sous-titres en boucle, traduire les nouvelles répliques et
  demander à mpv de recharger le fichier (`MpvPlayer.reload_subtitle()` est déjà prêt).
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
