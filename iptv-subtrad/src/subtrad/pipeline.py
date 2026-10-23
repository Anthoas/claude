"""Enchaîne les étapes : trouver les sous-titres source d'un flux, puis les traduire."""

from __future__ import annotations

from dataclasses import dataclass

from . import extract
from .errors import friendly_error
from .hls import HlsClient, LiveStreamDetected, SubtitleTrack, choose_track, lang_matches
from .subtitles import Cue


class NoSubtitles(RuntimeError):
    pass


@dataclass
class SourceSubtitles:
    cues: list[Cue]
    origin: str  # description lisible de la piste utilisée
    # Direct : pas de répliques d'un bloc, la piste est à suivre en continu (live.py).
    live_track: SubtitleTrack | None = None


def fetch_source_subtitles(
    url: str,
    language: str = "fr",
    prefer_sdh: bool = False,
    hls: HlsClient | None = None,
) -> SourceSubtitles:
    """Récupère les sous-titres d'un flux dans la langue source voulue.

    1. Flux HLS avec pistes WebVTT séparées : le cas le plus simple et le plus rapide.
       Pour un direct, renvoie seulement la piste à suivre (`live_track`).
    2. Sinon, sous-titres texte intégrés au conteneur, extraits par ffmpeg (replay seulement).
    """
    hls = hls or HlsClient()
    errors = []

    try:
        tracks = hls.list_subtitle_tracks(url)
    except Exception as exc:  # flux non HLS, serveur qui refuse le GET...
        tracks, errors = [], [f"HLS : {friendly_error(exc)}"]
    track = choose_track(tracks, language, prefer_sdh)
    if track:
        origin = f"HLS {track.language} « {track.name} »"
        try:
            return SourceSubtitles(hls.download_track(track), origin)
        except LiveStreamDetected:
            return SourceSubtitles([], origin + " (direct)", live_track=track)
    if tracks:
        langs = ", ".join(sorted({t.language for t in tracks}))
        errors.append(f"HLS : aucune piste « {language} » (disponibles : {langs})")

    try:
        embedded = extract.probe_subtitle_tracks(url)
    except Exception as exc:
        embedded, errors = [], errors + [f"ffprobe : {friendly_error(exc)}"]
    for etrack in embedded:
        if etrack.is_text and lang_matches(etrack.language, language):
            if extract.stream_duration(url) is None:
                # ffmpeg lirait le direct sans fin ; seul le direct HLS + WebVTT est géré.
                raise NoSubtitles(
                    f"Direct avec sous-titres intégrés ({etrack.codec}) : non géré pour "
                    "l'instant, seuls les directs HLS avec pistes WebVTT le sont."
                )
            return SourceSubtitles(
                extract.extract_text_track(url, etrack),
                f"piste intégrée n°{etrack.index} ({etrack.codec}, {etrack.language})",
            )
    if embedded:
        desc = ", ".join(f"{t.index}:{t.codec}/{t.language or '?'}" for t in embedded)
        errors.append(f"intégrées : aucune piste texte « {language} » ({desc})")

    raise NoSubtitles("Aucun sous-titre exploitable trouvé.\n  " + "\n  ".join(errors))


@dataclass
class Compatibility:
    ok: bool
    message: str


def check_subtitles(
    url: str, language: str = "fr", hls: HlsClient | None = None
) -> Compatibility:
    """Dit, sans rien traduire, si `regarder` pourra exploiter les sous-titres de ce flux."""
    hls = hls or HlsClient()
    try:
        tracks = hls.list_subtitle_tracks(url)
    except Exception as exc:
        return Compatibility(False, f"Flux inaccessible : {friendly_error(exc)}")
    track = choose_track(tracks, language)
    if track:
        return Compatibility(True, f"Sous-titres « {track.language} » trouvés ({track.name}).")
    if tracks:
        langs = ", ".join(sorted({t.language or "?" for t in tracks}))
        return Compatibility(False, f"Sous-titres disponibles seulement en : {langs}.")

    try:
        embedded = extract.probe_subtitle_tracks(url, timeout=30)
    except Exception as exc:
        return Compatibility(False, "Flux illisible (ffprobe n'a pas pu l'ouvrir).")
    wanted = [t for t in embedded if lang_matches(t.language, language)]
    text = [t for t in wanted if t.is_text]
    if text:
        if extract.stream_duration(url, timeout=30) is None:
            return Compatibility(
                False, "Direct avec sous-titres intégrés : pas encore géré."
            )
        return Compatibility(True, f"Sous-titres « {language} » intégrés ({text[0].codec}).")
    if wanted:
        return Compatibility(False, "Sous-titres en image : il faudrait de l'OCR (pas encore géré).")
    if embedded:
        langs = ", ".join(sorted({t.language or "?" for t in embedded}))
        return Compatibility(False, f"Sous-titres intégrés seulement en : {langs}.")
    return Compatibility(False, "Aucun sous-titre dans ce flux.")
