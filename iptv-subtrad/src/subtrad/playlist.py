"""Lecture des playlists M3U / M3U8 « IPTV » (format #EXTM3U + #EXTINF)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

# tvg-id="..." group-title="..." etc.
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


@dataclass
class Channel:
    name: str
    url: str
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def group(self) -> str:
        return self.attrs.get("group-title", "")

    @property
    def logo(self) -> str:
        return self.attrs.get("tvg-logo", "")


def _split_extinf(line: str) -> tuple[str, str]:
    """Sépare les attributs du nom, à la première virgule hors guillemets."""
    in_quotes = False
    for i, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
        elif char == "," and not in_quotes:
            return line[:i], line[i + 1 :]
    return line, ""


def parse_m3u(text: str) -> list[Channel]:
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
            channels.append(Channel(name=name or line, url=line, attrs=attrs))
            pending = None

    return channels


def load_playlist(source: str, timeout: float = 30.0) -> list[Channel]:
    """Charge une playlist depuis une URL http(s) ou un fichier local."""
    if source.startswith(("http://", "https://")):
        resp = requests.get(source, timeout=timeout)
        resp.raise_for_status()
        text = resp.text
    else:
        text = Path(source).read_text(encoding="utf-8", errors="replace")
    return parse_m3u(text)
