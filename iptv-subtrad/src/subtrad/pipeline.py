"""Enchaîne les étapes : trouver les sous-titres source d'un flux, puis les traduire."""

from __future__ import annotations

from dataclasses import dataclass

from . import extract
from .hls import HlsClient, choose_track, lang_matches
from .subtitles import Cue


class NoSubtitles(RuntimeError):
    pass


@dataclass
class SourceSubtitles:
    cues: list[Cue]
    origin: str  # description lisible de la piste utilisée


def fetch_source_subtitles(
    url: str,
    language: str = "fr",
    prefer_sdh: bool = False,
    hls: HlsClient | None = None,
) -> SourceSubtitles:
    """Récupère les sous-titres d'un flux dans la langue source voulue.

    1. Flux HLS avec pistes WebVTT séparées : le cas le plus simple et le plus rapide.
    2. Sinon, sous-titres texte intégrés au conteneur, extraits par ffmpeg.
    """
    hls = hls or HlsClient()
    errors = []

    try:
        tracks = hls.list_subtitle_tracks(url)
    except Exception as exc:  # flux non HLS, serveur qui refuse le GET...
        tracks, errors = [], [f"HLS : {exc}"]
    track = choose_track(tracks, language, prefer_sdh)
    if track:
        return SourceSubtitles(hls.download_track(track), f"HLS {track.language} « {track.name} »")
    if tracks:
        langs = ", ".join(sorted({t.language for t in tracks}))
        errors.append(f"HLS : aucune piste « {language} » (disponibles : {langs})")

    try:
        embedded = extract.probe_subtitle_tracks(url)
    except Exception as exc:
        embedded, errors = [], errors + [f"ffprobe : {exc}"]
    for etrack in embedded:
        if etrack.is_text and lang_matches(etrack.language, language):
            return SourceSubtitles(
                extract.extract_text_track(url, etrack),
                f"piste intégrée n°{etrack.index} ({etrack.codec}, {etrack.language})",
            )
    if embedded:
        desc = ", ".join(f"{t.index}:{t.codec}/{t.language or '?'}" for t in embedded)
        errors.append(f"intégrées : aucune piste texte « {language} » ({desc})")

    raise NoSubtitles("Aucun sous-titre exploitable trouvé.\n  " + "\n  ".join(errors))
