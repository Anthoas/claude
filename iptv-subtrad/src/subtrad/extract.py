"""Extraction des sous-titres intégrés au conteneur (TS, MKV, MP4) avec ffprobe/ffmpeg.

Sert de solution de repli quand le flux n'est pas un HLS avec pistes WebVTT séparées.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

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


def extract_text_track(url: str, track: EmbeddedTrack, timeout: float | None = None) -> list[Cue]:
    """Extrait une piste texte en SRT. Sur un flux réseau, ffmpeg lit tout le flux."""
    if not track.is_text:
        raise ValueError(
            f"La piste {track.index} ({track.codec}) est une image : il faudrait de l'OCR."
        )
    out = subprocess.run(
        [_require("ffmpeg"), "-v", "error", "-i", url,
         "-map", f"0:s:{track.index}", "-f", "srt", "-"],
        capture_output=True, text=True, timeout=timeout, check=True,
    ).stdout
    return parse_subtitles(out, "srt")
