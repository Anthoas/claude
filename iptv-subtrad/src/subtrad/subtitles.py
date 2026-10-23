"""Représentation des sous-titres et conversions (WebVTT, SRT, ASS...) via pysubs2."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, replace
from pathlib import Path

import pysubs2


@dataclass(frozen=True)
class Cue:
    """Une réplique : début et fin en millisecondes, texte brut (\\n = saut de ligne)."""

    start_ms: int
    end_ms: int
    text: str

    def with_text(self, text: str) -> "Cue":
        return replace(self, text=text)


def _strip_hls_headers(vtt: str) -> str:
    # X-TIMESTAMP-MAP (propre au HLS) perturbe le parseur de pysubs2.
    return "\n".join(
        line for line in vtt.splitlines() if not line.startswith("X-TIMESTAMP-MAP")
    )


def parse_subtitles(text: str, fmt: str | None = None) -> list[Cue]:
    """Parse un contenu de sous-titres. `fmt` : "vtt", "srt", "ass"... (auto si None)."""
    if fmt == "vtt" or text.lstrip("﻿").startswith("WEBVTT"):
        text, fmt = _strip_hls_headers(text), "vtt"
    if not text.strip() or text.strip() == "WEBVTT":
        return []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        subs = pysubs2.SSAFile.from_string(text, format_=fmt)
    return [
        Cue(e.start, e.end, e.plaintext.strip())
        for e in subs
        if not e.is_comment and e.plaintext.strip()
    ]


def load_subtitles(path: str | Path) -> list[Cue]:
    path = Path(path)
    return parse_subtitles(path.read_text(encoding="utf-8", errors="replace"))


def merge_cues(chunks: list[list[Cue]]) -> list[Cue]:
    """Fusionne les répliques de plusieurs segments HLS.

    Une réplique à cheval sur deux segments est répétée dans chacun : on dédoublonne.
    """
    seen: set[Cue] = set()
    merged: list[Cue] = []
    for chunk in chunks:
        for cue in chunk:
            if cue not in seen:
                seen.add(cue)
                merged.append(cue)
    merged.sort(key=lambda c: (c.start_ms, c.end_ms))
    return merged


def to_ssafile(cues: list[Cue]) -> pysubs2.SSAFile:
    subs = pysubs2.SSAFile()
    for cue in cues:
        event = pysubs2.SSAEvent(start=cue.start_ms, end=cue.end_ms)
        event.plaintext = cue.text
        subs.append(event)
    return subs


def save_subtitles(cues: list[Cue], path: str | Path) -> Path:
    """Écrit les répliques ; le format est déduit de l'extension (.srt, .vtt, .ass)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    to_ssafile(cues).save(str(path))
    return path
