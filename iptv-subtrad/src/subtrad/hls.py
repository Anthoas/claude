"""Découverte et téléchargement des pistes de sous-titres d'un flux HLS (.m3u8)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

import requests

from .subtitles import Cue, merge_cues, parse_subtitles

# KEY=valeur ou KEY="valeur, avec virgules"
_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')

# Codes de langue équivalents (ISO 639-1 / 639-2 B / 639-2 T).
_LANG_ALIASES = {
    "fr": {"fr", "fra", "fre"},
    "en": {"en", "eng"},
    "id": {"id", "ind"},
}


class LiveStreamNotSupported(RuntimeError):
    pass


def parse_attributes(attr_list: str) -> dict[str, str]:
    return {k: v.strip('"') for k, v in _ATTR_RE.findall(attr_list)}


def lang_matches(track_lang: str, wanted: str) -> bool:
    track = track_lang.lower().split("-")[0]
    wanted = wanted.lower()
    return track in _LANG_ALIASES.get(wanted, {wanted})


@dataclass
class SubtitleTrack:
    uri: str
    language: str
    name: str
    group_id: str
    default: bool = False
    forced: bool = False
    # Sous-titres pour sourds et malentendants (descriptions de sons, etc.)
    sdh: bool = False


@dataclass
class MediaPlaylist:
    segments: list[str]
    target_duration: float
    media_sequence: int
    ended: bool  # EXT-X-ENDLIST présent : VOD / replay, sinon direct


def is_master_playlist(text: str) -> bool:
    return "#EXT-X-STREAM-INF" in text or "#EXT-X-MEDIA:" in text


def parse_subtitle_tracks(master: str, base_url: str) -> list[SubtitleTrack]:
    tracks = []
    for line in master.splitlines():
        if not line.startswith("#EXT-X-MEDIA:"):
            continue
        attrs = parse_attributes(line.split(":", 1)[1])
        if attrs.get("TYPE") != "SUBTITLES" or "URI" not in attrs:
            continue
        tracks.append(
            SubtitleTrack(
                uri=urljoin(base_url, attrs["URI"]),
                language=attrs.get("LANGUAGE", ""),
                name=attrs.get("NAME", ""),
                group_id=attrs.get("GROUP-ID", ""),
                default=attrs.get("DEFAULT") == "YES",
                forced=attrs.get("FORCED") == "YES",
                sdh="describes-music-and-sound" in attrs.get("CHARACTERISTICS", ""),
            )
        )
    return tracks


def parse_media_playlist(text: str, base_url: str) -> MediaPlaylist:
    segments, target, sequence = [], 0.0, 0
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-TARGETDURATION:"):
            target = float(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            sequence = int(line.split(":", 1)[1])
        elif line and not line.startswith("#"):
            segments.append(urljoin(base_url, line))
    return MediaPlaylist(segments, target, sequence, ended="#EXT-X-ENDLIST" in text)


def choose_track(
    tracks: list[SubtitleTrack], language: str, prefer_sdh: bool = False
) -> SubtitleTrack | None:
    """Choisit la meilleure piste dans la langue voulue.

    Les pistes « forcées » (seulement les passages en langue étrangère) sont écartées
    en priorité ; on préfère ou non les sous-titres sourds et malentendants.
    """
    candidates = [t for t in tracks if lang_matches(t.language, language)]
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t.forced, t.sdh != prefer_sdh, not t.default))
    return candidates[0]


class HlsClient:
    def __init__(self, session: requests.Session | None = None, timeout: float = 30.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def get_text(self, url: str) -> str:
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        # Le WebVTT est toujours en UTF-8, même si le serveur annonce autre chose.
        resp.encoding = "utf-8"
        return resp.text

    def list_subtitle_tracks(self, url: str) -> list[SubtitleTrack]:
        text = self.get_text(url)
        if not is_master_playlist(text):
            return []
        return parse_subtitle_tracks(text, url)

    def download_track(self, track: SubtitleTrack) -> list[Cue]:
        """Télécharge une piste complète (VOD/replay) et renvoie ses répliques."""
        text = self.get_text(track.uri)
        if text.lstrip("﻿").startswith("WEBVTT"):
            # Certains services pointent directement vers un fichier .vtt unique.
            return parse_subtitles(text, "vtt")
        playlist = parse_media_playlist(text, track.uri)
        if not playlist.ended:
            raise LiveStreamNotSupported(
                "Flux en direct : la traduction au fil de l'eau n'est pas encore implémentée."
            )
        chunks = [parse_subtitles(self.get_text(seg), "vtt") for seg in playlist.segments]
        return merge_cues(chunks)
