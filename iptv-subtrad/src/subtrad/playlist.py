"""Lecture des playlists M3U / M3U8 « IPTV » (format #EXTM3U + #EXTINF)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests

# tvg-id="..." group-title="..." etc.
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


@dataclass
class Channel:
    name: str
    url: str
    attrs: dict[str, str] = field(default_factory=dict)
    source: str = ""  # nom de la source (playlist) d'où vient cette entrée

    @property
    def group(self) -> str:
        return self.attrs.get("group-title", "")

    @property
    def logo(self) -> str:
        return self.attrs.get("tvg-logo", "")

    @property
    def kind(self) -> str:
        """« film », « serie » ou « direct », d'après le chemin de l'URL (convention des
        serveurs IPTV : /movie/... et /series/...)."""
        path = urlparse(self.url).path.lower()
        if "/movie/" in path:
            return "film"
        if "/series/" in path:
            return "serie"
        return "direct"


def _split_extinf(line: str) -> tuple[str, str]:
    """Sépare les attributs du nom, à la première virgule hors guillemets."""
    in_quotes = False
    for i, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
        elif char == "," and not in_quotes:
            return line[:i], line[i + 1 :]
    return line, ""


def parse_m3u(text: str, source: str = "") -> list[Channel]:
    """Transforme le texte d'une playlist en liste de chaînes.

    Tolère les lignes vides, les commentaires et l'absence d'en-tête #EXTM3U.
    """
    channels: list[Channel] = []
    pending: tuple[str, dict[str, str]] | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            # #EXTINF:-1 tvg-id="x" group-title="y",Nom de la chaîne
            header, name = _split_extinf(line)
            attrs = dict(_ATTR_RE.findall(header))
            pending = (name.strip(), attrs)
        elif line.startswith("#"):
            continue
        else:
            name, attrs = pending if pending else (line, {})
            channels.append(Channel(name=name or line, url=line, attrs=attrs, source=source))
            pending = None

    return channels


# Les grosses playlists peuvent peser des dizaines de Mo et être lentes à générer.
PLAYLIST_TIMEOUT = (15, 180)  # (connexion, lecture) en secondes
MAX_PLAYLIST_BYTES = 300_000_000


def fetch_playlist_text(source: str) -> str:
    """Texte d'une playlist, depuis une URL http(s) ou un fichier local."""
    if not source.startswith(("http://", "https://")):
        return Path(source).read_text(encoding="utf-8", errors="replace")
    with requests.get(source, timeout=PLAYLIST_TIMEOUT, stream=True) as resp:
        resp.raise_for_status()
        body = bytearray()
        for chunk in resp.iter_content(chunk_size=1 << 20):
            body += chunk
            if len(body) > MAX_PLAYLIST_BYTES:
                raise ValueError("Playlist trop volumineuse (plus de 300 Mo).")
    return body.decode("utf-8", errors="replace")


def load_playlist(source: str) -> list[Channel]:
    """Charge une playlist depuis une URL http(s) ou un fichier local."""
    return parse_m3u(fetch_playlist_text(source))
