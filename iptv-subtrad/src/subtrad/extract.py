"""Extraction des sous-titres intégrés au conteneur (TS, MKV, MP4) avec ffprobe/ffmpeg.

Sert de solution de repli quand le flux n'est pas un HLS avec pistes WebVTT séparées.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Iterator

from .errors import Cancelled
from .subtitles import Cue, parse_subtitles

# Codecs texte : convertibles directement en SRT.
TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text", "ttml"}
# Codecs image : nécessiteraient de l'OCR (non géré pour l'instant).
BITMAP_CODECS = {"dvb_subtitle", "hdmv_pgs_subtitle", "dvd_subtitle", "xsub"}


class FfmpegMissing(RuntimeError):
    pass


@dataclass
class EmbeddedTrack:
    index: int  # index parmi les pistes de sous-titres (0:s:N)
    codec: str
    language: str
    title: str
    forced: bool = False  # seulement les passages en langue étrangère (quelques répliques)
    default: bool = False
    sdh: bool = False  # sous-titres pour sourds et malentendants (avec les bruits)

    @property
    def is_text(self) -> bool:
        return self.codec in TEXT_CODECS

    @property
    def looks_forced(self) -> bool:
        return self.forced or bool(re.search(r"forc", self.title, re.I))

    @property
    def looks_sdh(self) -> bool:
        return self.sdh or bool(re.search(r"sdh|sme|malentendant|hearing|\bcc\b", self.title, re.I))


def choose_embedded_track(
    tracks: list[EmbeddedTrack], language: str, prefer_sdh: bool = False
) -> EmbeddedTrack | None:
    """Meilleure piste TEXTE dans la langue voulue : jamais une piste « forcée » tant qu'une
    autre existe (elle ne contient que quelques répliques), puis selon la préférence SME,
    puis la piste par défaut."""
    from .hls import lang_matches

    candidates = [t for t in tracks if t.is_text and lang_matches(t.language, language)]
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t.looks_forced, t.looks_sdh != prefer_sdh, not t.default,
                                   t.index))
    return candidates[0]


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise FfmpegMissing(f"{binary} introuvable : installe ffmpeg (https://ffmpeg.org)")
    return path


def network_input_args(url: str) -> list[str]:
    """Options d'entrée de ffmpeg pour un fichier en ligne : certains serveurs IPTV coupent la
    connexion au bout de quelques centaines de Mo. Sans elles, ffmpeg s'arrête sans erreur
    (code 0) comme si le fichier était fini ; avec elles, il reprend là où il en était."""
    if not url.startswith(("http://", "https://")):
        return []
    return ["-reconnect", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "10"]


def check_complete(read_seconds: float, duration: float | None, what: str) -> None:
    """Refuse une lecture arrêtée nettement avant la fin connue du fichier. Valable pour le son,
    qui couvre toute la durée ; pas pour une piste de sous-titres, qui s'arrête à la dernière
    réplique, parfois des minutes avant la fin (générique)."""
    if duration and read_seconds < duration * 0.95:
        raise RuntimeError(
            f"Le serveur a coupé la lecture {what} à {int(read_seconds // 60)} min sur "
            f"{int(duration // 60)} min. Réessaie dans un moment (une autre lecture en cours "
            "sur le même abonnement peut en être la cause)."
        )


@dataclass
class ProbeResult:
    tracks: list[EmbeddedTrack]
    duration: float | None  # None : direct (durée inconnue)
    format_name: str  # ex. « matroska,webm », « mov,mp4,m4a,3gp,3g2,mj2 », « mpegts »


def probe(url: str, timeout: float = 60.0) -> ProbeResult:
    """Pistes de sous-titres, durée et format du fichier, en un seul appel à ffprobe."""
    out = subprocess.run(
        [_require("ffprobe"), "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=codec_name:stream_tags=language,title"
                          ":stream_disposition=forced,default,hearing_impaired"
                          ":format=duration,format_name",
         "-of", "json", url],
        capture_output=True, text=True, timeout=timeout, check=True,
    ).stdout
    data = json.loads(out or "{}")
    fmt = data.get("format", {})
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = None
    tracks = [
        EmbeddedTrack(
            index=i,
            codec=st.get("codec_name", ""),
            language=st.get("tags", {}).get("language", ""),
            title=st.get("tags", {}).get("title", ""),
            forced=bool(st.get("disposition", {}).get("forced")),
            default=bool(st.get("disposition", {}).get("default")),
            sdh=bool(st.get("disposition", {}).get("hearing_impaired")),
        )
        for i, st in enumerate(data.get("streams", []))
    ]
    return ProbeResult(tracks, duration, fmt.get("format_name", ""))


def probe_subtitle_tracks(url: str, timeout: float = 60.0) -> list[EmbeddedTrack]:
    out = subprocess.run(
        [_require("ffprobe"), "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=codec_name:stream_tags=language,title",
         "-of", "json", url],
        capture_output=True, text=True, timeout=timeout, check=True,
    ).stdout
    streams = json.loads(out or "{}").get("streams", [])
    return [
        EmbeddedTrack(
            index=i,
            codec=s.get("codec_name", ""),
            language=s.get("tags", {}).get("language", ""),
            title=s.get("tags", {}).get("title", ""),
        )
        for i, s in enumerate(streams)
    ]


def stream_duration(url: str, timeout: float = 60.0) -> float | None:
    """Durée du flux en secondes, None pour un direct (durée inconnue)."""
    out = subprocess.run(
        [_require("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", url],
        capture_output=True, text=True, timeout=timeout, check=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return None


def parse_progress_line(line: str) -> float | None:
    """Position de lecture en secondes d'après une ligne `-progress` de ffmpeg, sinon None."""
    key, _, value = line.strip().partition("=")
    if key not in ("out_time_us", "out_time_ms"):  # (out_time_ms est lui aussi en microsecondes)
        return None
    try:
        return int(value) / 1_000_000
    except ValueError:  # « N/A » au tout début
        return None


_PROGRESS_KEY_RE = re.compile(r"^[a-z_]+=")


def kill_when_cancelled(process: subprocess.Popen, cancel: threading.Event | None) -> None:
    """Tue `process` dès que `cancel` est déclenché (même s'il attend le réseau)."""
    if cancel is None:
        return

    def watch() -> None:
        while process.poll() is None:
            if cancel.wait(0.3):
                process.kill()
                return

    threading.Thread(target=watch, daemon=True).start()


def iter_text_track(
    url: str,
    track: EmbeddedTrack,
    duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> Iterator[Cue]:
    """Donne les répliques d'une piste texte au fur et à mesure que ffmpeg les lit.

    Sur un fichier réseau, ffmpeg doit lire tout le fichier ; on n'attend pas la fin pour
    commencer à traduire. `on_progress(fraction)` suit la lecture quand `duration` est connue.
    """
    if not track.is_text:
        raise ValueError(
            f"La piste {track.index} ({track.codec}) est une image : il faudrait de l'OCR."
        )
    process = subprocess.Popen(
        [_require("ffmpeg"), "-v", "error", "-nostdin",
         "-progress", "pipe:2", "-nostats", "-stats_period", "0.5",
         *network_input_args(url), "-i", url, "-map", f"0:s:{track.index}",
         # Écrire chaque réplique dès qu'elle est lue (sinon ffmpeg les garde en mémoire tampon).
         "-flush_packets", "1", "-f", "srt", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    errors: list[str] = []

    def read_stderr() -> None:
        for line in process.stderr:
            position = parse_progress_line(line)
            if position is not None:
                if duration and on_progress:
                    on_progress(max(0.0, min(1.0, position / duration)))
            elif line.strip() and not _PROGRESS_KEY_RE.match(line):
                errors.append(line.strip())

    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stderr_thread.start()
    kill_when_cancelled(process, cancel)
    try:
        block: list[str] = []
        for line in process.stdout:
            if line.strip():
                block.append(line.rstrip("\n"))
                continue
            if block:
                yield from parse_subtitles("\n".join(block) + "\n", "srt")
                block = []
        if block:
            yield from parse_subtitles("\n".join(block) + "\n", "srt")
        process.wait()
        stderr_thread.join(timeout=2)
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if process.returncode != 0:
            raise RuntimeError(
                "ffmpeg n'a pas pu lire les sous-titres : " + " ".join(errors)[-300:]
            )
        if on_progress:
            on_progress(1.0)
    finally:
        if process.poll() is None:  # consommateur arrêté en route (annulation, erreur)
            process.kill()
            process.wait()


def extract_text_track(
    url: str,
    track: EmbeddedTrack,
    duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> list[Cue]:
    """Extrait toute une piste texte (voir `iter_text_track`)."""
    return list(iter_text_track(url, track, duration, on_progress, cancel))
