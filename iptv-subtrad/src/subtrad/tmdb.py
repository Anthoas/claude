"""Titres, résumés et images des épisodes depuis TMDB (themoviedb.org), en français.

Le fournisseur IPTV ne donne presque jamais le titre ni le résumé d'un épisode. TMDB les a, avec
une clé gratuite que l'utilisateur colle dans les réglages (jamais affichée, jamais envoyée à la
télé). Les réponses sont gardées 30 jours sur ce Mac, dans des fichiers privés.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Callable

import requests

from .cache import default_cache_path

API = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p/w300"
KEEP_SECONDS = 30 * 24 * 3600
TIMEOUT = 20
# Mentions de qualité ou de version dans les noms IPTV, inutiles pour chercher sur TMDB.
_NOISE_RE = re.compile(r"\b(4K|UHD|FHD|HD|SD|3D|MULTI|VOSTFR|VOST|VF|VFF|VFQ|VO|DV)\b|\(H\.?26[45]\)|[⁴ᴷ]",
                       re.IGNORECASE)


def default_tmdb_dir() -> Path:
    return default_cache_path().parent / "tmdb"


def search_name(name: str) -> tuple[str, str]:
    """(titre à chercher, année) d'après un nom IPTV nettoyé : « Sense8 2015 FHD MULTI »."""
    year = ""
    m = re.search(r"\b((?:19|20)\d\d)\b", name)
    if m:
        year = m.group(1)
    title = re.sub(r"\(.*?\)", " ", name)  # titre original entre parenthèses, ou année
    title = _NOISE_RE.sub(" ", title)
    title = re.sub(r"\b(?:19|20)\d\d\b", " ", title)
    return re.sub(r"\s+", " ", title).strip(" -|"), year


def _real_title(name: str) -> str:
    """« Épisode 5 » (titre par défaut quand TMDB n'a pas de titre français) ne dit rien."""
    return "" if re.fullmatch(r"\s*(?:é|e)pisode\s*\d+\s*", name, re.IGNORECASE) else name.strip()


class TmdbClient:
    def __init__(self, key: str, session: requests.Session | None = None, language: str = "fr-FR"):
        self.key, self.language = key.strip(), language
        self.session = session or requests.Session()

    def get(self, path: str, **params) -> dict:
        headers = {}
        if "." in self.key and len(self.key) > 60:  # jeton « v4 » (lecture seule)
            headers["Authorization"] = f"Bearer {self.key}"
        else:  # clé « v3 »
            params["api_key"] = self.key
        params.setdefault("language", self.language)
        resp = self.session.get(API + path, params=params, headers=headers, timeout=TIMEOUT)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()

    def check(self) -> bool:
        """La clé est-elle acceptée par TMDB ?"""
        try:
            self.get("/configuration")
            return True
        except requests.HTTPError:
            return False


class EpisodeGuide:
    """Épisodes d'une série d'après TMDB, gardés 30 jours sur le disque."""

    def __init__(self, client_factory: Callable[[], TmdbClient | None], directory: Path | None = None,
                 clock: Callable[[], float] = time.time):
        self._client_factory = client_factory
        self.directory = Path(directory) if directory else default_tmdb_dir()
        self._clock = clock

    def available(self) -> bool:
        return self._client_factory() is not None

    def _cached(self, name: str, fetch: Callable[[], object]) -> object:
        path = self.directory / f"{name}.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if self._clock() - saved["saved_at"] < KEEP_SECONDS:
                return saved["data"]
        except (OSError, ValueError, KeyError):
            pass
        data = fetch()
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"saved_at": self._clock(), "data": data}, f, ensure_ascii=False)
        os.replace(tmp, path)
        return data

    def find_series(self, name: str, year: str = "") -> int | None:
        """Numéro TMDB d'une série d'après son nom IPTV (quand le fournisseur ne le donne pas)."""
        client = self._client_factory()
        if client is None:
            return None
        title, found_year = search_name(name)
        year = year or found_year
        if not title:
            return None
        key = hashlib.sha256(f"{title}\0{year}".encode()).hexdigest()[:24]

        def fetch():
            params = {"query": title}
            if year:
                params["first_air_date_year"] = year
            results = client.get("/search/tv", **params).get("results") or []
            if not results and year:  # année parfois décalée d'un an chez le fournisseur
                results = client.get("/search/tv", query=title).get("results") or []
            return results[0]["id"] if results else None

        return self._cached(f"search-{key}", fetch)

    def season(self, tv_id: int, season: int) -> dict[int, dict]:
        """{numéro d'épisode: {"title", "plot", "image", "air_date"}} (vide si inconnu)."""
        client = self._client_factory()
        if client is None:
            return {}

        def fetch():
            episodes = client.get(f"/tv/{int(tv_id)}/season/{int(season)}").get("episodes") or []
            return [{"episode": e.get("episode_number"), "title": _real_title(e.get("name") or ""),
                     "plot": e.get("overview") or "", "air_date": e.get("air_date") or "",
                     "image": IMAGES + e["still_path"] if e.get("still_path") else ""}
                    for e in episodes]

        data = self._cached(f"tv-{int(tv_id)}-s{int(season)}", fetch)
        return {int(e["episode"]): e for e in data if e.get("episode") is not None}
