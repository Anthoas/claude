"""Extraction des sous-titres intégrés au conteneur (TS, MKV, MP4) avec ffprobe/ffmpeg.

Sert de solution de repli quand le flux n'est pas un HLS avec pistes WebVTT séparées.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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

    @property
    def is_text(self) -> bool:
        return self.codec in TEXT_CODECS


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise FfmpegMissing(f"{binary} introuvable : installe ffmpeg (https://ffmpeg.org)")
    return path


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


def extract_text_track(
    url: str,
    track: EmbeddedTrack,
    duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> list[Cue]:
    """Extrait une piste texte. Sur un flux réseau, ffmpeg doit lire tout le fichier.

    `on_progress(fraction)` est appelé pendant la lecture (0 à 1) quand `duration`, la
    durée du fichier en secondes, est connue.
    """
    if not track.is_text:
        raise ValueError(
            f"La piste {track.index} ({track.codec}) est une image : il faudrait de l'OCR."
        )
    with tempfile.TemporaryDirectory(prefix="subtrad-") as tmp:
        out_path = Path(tmp) / "sous-titres.srt"
        with open(Path(tmp) / "ffmpeg.log", "w+", encoding="utf-8") as log:
            process = subprocess.Popen(
                [_require("ffmpeg"), "-v", "error", "-nostdin", "-y",
                 "-progress", "pipe:1", "-nostats", "-stats_period", "0.5",
                 "-i", url, "-map", f"0:s:{track.index}", "-f", "srt", str(out_path)],
                stdout=subprocess.PIPE, stderr=log, text=True,
            )
            try:
                for line in process.stdout:
                    position = parse_progress_line(line)
                    if position is not None and duration and on_progress:
                        on_progress(max(0.0, min(1.0, position / duration)))
                process.wait()
            except BaseException:
                process.kill()
                raise
            if process.returncode != 0:
                log.seek(0)
                raise RuntimeError(
                    f"ffmpeg n'a pas pu lire les sous-titres : {log.read().strip()[-300:]}"
                )
        if on_progress:
            on_progress(1.0)
        return parse_subtitles(out_path.read_text(encoding="utf-8", errors="replace"), "srt")
