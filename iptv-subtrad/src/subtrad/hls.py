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


# Horloge MPEG-TS : 90 kHz, compteur sur 33 bits (repasse à zéro toutes les ~26,5 h).
_MPEGTS_HZ = 90_000
_MPEGTS_WRAP_MS = (1 << 33) * 1000 // _MPEGTS_HZ

_TIMESTAMP_MAP_RE = re.compile(r"X-TIMESTAMP-MAP=(.*)")
_VTT_TIME_RE = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})")


class NotAPlaylist(ValueError):
    pass


class LiveStreamDetected(RuntimeError):
    """La piste est un direct : elle se suit en continu (voir live.py), pas d'un bloc."""


def _vtt_time_ms(value: str) -> int:
    match = _VTT_TIME_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Horodatage WebVTT invalide : {value!r}")
    h, m, s, ms = match.groups()
    return ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def timestamp_offset_ms(vtt: str) -> int:
    """Décalage à ajouter aux temps d'un segment WebVTT pour obtenir l'horloge de la vidéo.

    `X-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000` signifie : le temps LOCAL du WebVTT
    correspond à l'horodatage MPEGTS (90 kHz) de la vidéo. Sans cette ligne, les temps sont
    déjà sur l'horloge de la vidéo.
    """
    for line in vtt.splitlines()[:10]:
        match = _TIMESTAMP_MAP_RE.match(line.strip())
        if match:
            attrs = dict(part.split(":", 1) for part in match.group(1).split(","))
            mpegts_ms = int(attrs.get("MPEGTS", "0")) * 1000 // _MPEGTS_HZ
            return mpegts_ms - _vtt_time_ms(attrs.get("LOCAL", "00:00.000"))
    return 0


def parse_vtt_segment(vtt: str) -> list[Cue]:
    """Parse un segment WebVTT et place ses répliques sur l'horloge de la vidéo."""
    offset = timestamp_offset_ms(vtt)
    return [
        Cue(c.start_ms + offset, c.end_ms + offset, c.text) for c in parse_subtitles(vtt, "vtt")
    ]


class PtsUnwrapper:
    """Rend les horodatages continus quand le compteur MPEG-TS repasse par zéro.

    ffmpeg (et donc mpv) fait la même correction côté vidéo, par rapport au premier
    horodatage vu.
    """

    def __init__(self):
        self.reference: int | None = None

    def __call__(self, ms: int) -> int:
        if self.reference is None:
            self.reference = ms
        if ms < self.reference - _MPEGTS_WRAP_MS // 2:
            ms += _MPEGTS_WRAP_MS
        return ms


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
    MAX_BYTES = 5_000_000

    def __init__(self, session: requests.Session | None = None, timeout: float = 30.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def get_text(self, url: str) -> str:
        """Télécharge une playlist ou un segment WebVTT.

        Lecture en flux et bornée : une URL de chaîne en MPEG-TS brut renverrait sinon une
        vidéo sans fin.
        """
        with self.session.get(url, timeout=self.timeout, stream=True) as resp:
            resp.raise_for_status()
            body = b""
            for chunk in resp.iter_content(chunk_size=65536):
                if not body and not chunk.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(
                    (b"#EXTM3U", b"WEBVTT")
                ):
                    raise NotAPlaylist(f"{url} n'est ni une playlist HLS ni du WebVTT.")
                body += chunk
                if len(body) > self.MAX_BYTES:
                    raise NotAPlaylist(f"{url} : réponse trop volumineuse pour une playlist.")
        # Le WebVTT est toujours en UTF-8, même si le serveur annonce autre chose.
        return body.decode("utf-8", errors="replace").lstrip("\ufeff")

    def list_subtitle_tracks(self, url: str) -> list[SubtitleTrack]:
        try:
            text = self.get_text(url)
        except NotAPlaylist:
            return []  # flux TS/MKV/MP4 direct : pas de pistes HLS séparées
        if not is_master_playlist(text):
            return []
        return parse_subtitle_tracks(text, url)

    def download_track(self, track: SubtitleTrack) -> list[Cue]:
        """Télécharge une piste complète (VOD/replay) et renvoie ses répliques.

        Les temps restent relatifs au début du programme (LOCAL du WebVTT) : c'est ce
        qu'attend un fichier .srt chargé dans mpv ou VLC.
        """
        text = self.get_text(track.uri)
        if text.lstrip("﻿").startswith("WEBVTT"):
            # Certains services pointent directement vers un fichier .vtt unique.
            return parse_subtitles(text, "vtt")
        playlist = parse_media_playlist(text, track.uri)
        if not playlist.ended:
            raise LiveStreamDetected(f"La piste {track.uri} est un direct.")
        chunks = [parse_subtitles(self.get_text(seg), "vtt") for seg in playlist.segments]
        return merge_cues(chunks)
