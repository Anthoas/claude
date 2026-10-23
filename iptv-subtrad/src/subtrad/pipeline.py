"""Enchaîne les étapes : trouver les sous-titres source d'un flux, puis les traduire.

Par ordre de préférence (du plus rapide au plus lent) :
1. piste de sous-titres séparée d'un flux HLS : quelques petits fichiers à télécharger ;
2. sous-titres intégrés à un MKV : lecture rapide grâce à l'index du fichier (mkv.py) ;
3. sous-titres intégrés, autres cas : ffmpeg lit tout le fichier, les répliques sortent
   au fil de la lecture ;
4. aucun sous-titre en texte : transcription de la voix avec Whisper (si activée).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import extract, mkv
from .errors import friendly_error
from .hls import HlsClient, LiveStreamDetected, SubtitleTrack, choose_track, lang_matches
from .subtitles import Cue

log = logging.getLogger(__name__)


class NoSubtitles(RuntimeError):
    pass


# Rapporte l'avancement : (message lisible, fraction de 0 à 1 ou None si on ne sait pas).
StatusCallback = Callable[[str, "float | None"], None]
# Fabrique le moteur Whisper (transcribe.make_transcriber) ; None = transcription désactivée.
TranscriberFactory = Callable[[], object]


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    return f"{seconds // 60} min {seconds % 60:02d} s"


@dataclass
class CueSource:
    """D'où viennent les répliques et comment les obtenir."""

    origin: str  # description lisible
    kind: str  # "hls" | "mkv-index" | "ffmpeg" | "whisper" | "live"
    # Répliques par groupes, au fur et à mesure qu'elles sont obtenues.
    groups: Iterable[list[Cue]] = field(default_factory=list)
    # Direct HLS : la piste à suivre en continu (live.py) au lieu de `groups`.
    live_track: SubtitleTrack | None = None
    # Whisper : chaque groupe correspond à un morceau de son ; à traduire sans attendre.
    flush_each_group: bool = False


def open_cue_source(
    url: str,
    language: str = "fr",
    prefer_sdh: bool = False,
    hls: HlsClient | None = None,
    on_status: StatusCallback | None = None,
    cancel: threading.Event | None = None,
    transcriber_factory: TranscriberFactory | None = None,
) -> CueSource:
    hls = hls or HlsClient()
    reasons: list[str] = []

    def status(message: str, fraction: float | None = None) -> None:
        if on_status:
            on_status(message, fraction)

    # 1. Flux HLS avec pistes de sous-titres séparées.
    status("Recherche de pistes de sous-titres dans le flux…")
    try:
        tracks = hls.list_subtitle_tracks(url)
    except Exception as exc:  # flux non HLS, serveur qui refuse le GET...
        tracks, reasons = [], [f"HLS : {friendly_error(exc)}"]
    track = choose_track(tracks, language, prefer_sdh)
    if track:
        origin = f"HLS {track.language} « {track.name} »"
        status("Téléchargement des sous-titres…")
        try:
            return CueSource(origin, "hls", [hls.download_track(track)])
        except LiveStreamDetected:
            return CueSource(origin + " (direct)", "live", live_track=track)
    if tracks:
        langs = ", ".join(sorted({t.language for t in tracks}))
        reasons.append(f"HLS : aucune piste « {language} » (disponibles : {langs})")

    # 2 et 3. Sous-titres intégrés au fichier.
    status("Analyse du fichier (recherche des sous-titres intégrés)…")
    try:
        info = extract.probe(url)
    except Exception as exc:
        raise NoSubtitles(f"Fichier illisible : {friendly_error(exc)}") from None
    wanted = [t for t in info.tracks if lang_matches(t.language, language)]
    text_track = next((t for t in wanted if t.is_text), None)
    if text_track and info.duration is None:
        raise NoSubtitles("Direct avec sous-titres intégrés : pas encore géré.")
    if text_track:
        if "matroska" in info.format_name:
            source = _try_mkv_index(url, language, prefer_sdh, status, cancel)
            if source:
                return source
        return CueSource(
            f"sous-titres intégrés ({text_track.codec}), lecture complète du fichier", "ffmpeg",
            _ffmpeg_groups(url, text_track, info.duration, status, cancel),
        )
    if wanted:
        reasons.append("sous-titres en image (il faudrait de l'OCR)")
    elif info.tracks:
        reasons.append("sous-titres intégrés dans une autre langue")

    # 4. Transcription de la voix.
    if transcriber_factory is not None:
        if info.duration is None:
            raise NoSubtitles(
                "Direct sans sous-titres : la transcription en direct n'est pas encore gérée.")
        from .transcribe import iter_transcribed_cues

        transcriber = transcriber_factory()
        return CueSource(
            "transcription de la voix (Whisper)", "whisper",
            iter_transcribed_cues(url, transcriber, language, info.duration, on_status, cancel),
            flush_each_group=True,
        )
    raise NoSubtitles(
        "Aucun sous-titre exploitable trouvé" + (" : " + " ; ".join(reasons) if reasons else ".")
    )


def _try_mkv_index(url, language, prefer_sdh, status, cancel) -> CueSource | None:
    status("Lecture rapide des sous-titres grâce à l'index du fichier…")
    try:
        cues, track = mkv.read_mkv_subtitles(
            url, language, prefer_sdh, cancel=cancel,
            on_progress=lambda f: status(f"Lecture rapide des sous-titres : {f:.0%}", f),
        )
    except mkv.MkvFastPathUnavailable as exc:
        log.info("Lecture rapide impossible (%s) : lecture complète.", exc)
        status(f"Lecture rapide impossible ({exc}) : il faut lire tout le fichier…")
        return None
    except Exception as exc:  # réseau capricieux : la lecture complète reste possible
        if cancel is not None and cancel.is_set():
            raise
        log.info("Lecture rapide interrompue (%s) : lecture complète.", friendly_error(exc))
        return None
    return CueSource(f"sous-titres intégrés ({track.codec}), lecture rapide", "mkv-index", [cues])


def _ffmpeg_groups(url, track, duration, status, cancel) -> Iterable[list[Cue]]:
    started = time.monotonic()

    def progress(fraction: float) -> None:
        elapsed = time.monotonic() - started
        text = f"Lecture du fichier pour en extraire les sous-titres : {fraction:.0%}"
        if fraction >= 0.03:
            remaining = elapsed * (1 - fraction) / fraction
            text += (" (presque terminé)" if remaining < 3
                     else f" (environ {format_duration(remaining)} restantes)")
        status(text, fraction)

    status("Lecture du fichier pour en extraire les sous-titres (peut prendre plusieurs minutes)…")
    for cue in extract.iter_text_track(url, track, duration, progress, cancel):
        yield [cue]


# --- Version « tout d'un coup », pour la ligne de commande -----------------------------------


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
    on_status: StatusCallback | None = None,
    transcriber_factory: TranscriberFactory | None = None,
) -> SourceSubtitles:
    """Récupère toutes les répliques d'un flux (ou la piste à suivre pour un direct)."""
    source = open_cue_source(url, language, prefer_sdh, hls, on_status,
                             transcriber_factory=transcriber_factory)
    if source.live_track:
        return SourceSubtitles([], source.origin, live_track=source.live_track)
    cues = [cue for group in source.groups for cue in group]
    return SourceSubtitles(cues, source.origin)


# --- Vérification sans rien traduire ----------------------------------------------------------


@dataclass
class Compatibility:
    ok: bool
    message: str
    mode: str = "no"  # "fast" | "slow" | "whisper" | "no"


def check_subtitles(
    url: str,
    language: str = "fr",
    hls: HlsClient | None = None,
    whisper_available: bool = False,
) -> Compatibility:
    """Dit si `regarder` pourra exploiter ce flux, et en combien de temps à peu près."""
    hls = hls or HlsClient()
    try:
        tracks = hls.list_subtitle_tracks(url)
    except Exception as exc:
        return Compatibility(False, f"Flux inaccessible : {friendly_error(exc)}")
    track = choose_track(tracks, language)
    if track:
        return Compatibility(True, f"Sous-titres « {track.language} » trouvés ({track.name}).",
                             "fast")
    if tracks:
        langs = ", ".join(sorted({t.language or "?" for t in tracks}))
        return Compatibility(False, f"Sous-titres disponibles seulement en : {langs}.")

    try:
        info = extract.probe(url, timeout=30)
    except Exception:
        return Compatibility(False, "Flux illisible (ffprobe n'a pas pu l'ouvrir).")
    wanted = [t for t in info.tracks if lang_matches(t.language, language)]
    text = [t for t in wanted if t.is_text]
    if text and info.duration is None:
        return Compatibility(False, "Direct avec sous-titres intégrés : pas encore géré.")
    if text:
        codec = text[0].codec
        if "matroska" in info.format_name:
            try:
                mkv.MkvSubtitleReader(url).load_index(language)
                return Compatibility(
                    True, f"Sous-titres « {language} » intégrés ({codec}) : lecture rapide.",
                    "fast")
            except Exception:
                pass
        return Compatibility(
            True, f"Sous-titres « {language} » intégrés ({codec}), mais il faudra lire tout le "
                  "fichier : plusieurs minutes.", "slow")
    reason = ("sous-titres en image" if wanted else
              "sous-titres dans une autre langue" if info.tracks else "aucun sous-titre")
    if whisper_available and info.duration is not None:
        return Compatibility(
            True, f"Pas de sous-titres utilisables ({reason}) : la voix sera transcrite par "
                  "Whisper (plus long).", "whisper")
    if wanted:
        return Compatibility(False, "Sous-titres en image : il faudrait de l'OCR (pas encore géré).")
    if info.tracks:
        langs = ", ".join(sorted({t.language or "?" for t in info.tracks}))
        return Compatibility(False, f"Sous-titres intégrés seulement en : {langs}.")
    return Compatibility(False, "Aucun sous-titre dans ce flux.")
