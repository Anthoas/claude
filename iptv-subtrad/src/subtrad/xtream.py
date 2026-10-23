"""Catalogue Xtream Codes : séries regroupées par saison, films, affiches, résumés, catégories.

Beaucoup de fournisseurs IPTV donnent, en plus de la playlist M3U, un accès « Xtream Codes »
(player_api.php) avec le même identifiant et le même mot de passe que le lien de la playlist.
Il décrit les séries (saisons, épisodes, résumé, genre, note, affiche) et les films bien mieux
que les noms de la playlist. On s'en sert pour l'affichage sur la télé ; la lecture et la
traduction passent toujours par les vidéos de la playlist, retrouvées par leur numéro.

Les identifiants restent sur ce Mac : la télé ne reçoit que des noms, des images publiques et les
numéros des vidéos de la playlist.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import requests

from .cache import default_cache_path
from .playlist import Channel

REFRESH_SECONDS = 24 * 3600  # le catalogue est rechargé une fois par jour
INFO_SECONDS = 3600  # détail d'une série gardé une heure
TIMEOUT = 120
_LANG_RE = re.compile(r"^\W*([A-Z]{2,3})\W")  # « |FR| Titre », « FR| Titre »
_PREFIX_RE = re.compile(r"^(?:\s*\|?[A-Z]{2,3}(?:\s[^|\n]{0,12})?\|\s*)+")  # « |FR| », « |FR DV⁴ᴷ| »
_YEAR_RE = re.compile(r"\b((?:19|20)\d\d)\b")
_PATH_RE = re.compile(r"/(series|movie)/[^/]+/[^/]+/(\d+)\.(\w+)$")


def default_catalog_dir() -> Path:
    return default_cache_path().parent / "xtream"


def language_of(name: str) -> str:
    """Langue d'après le préfixe du nom (« |FR| … » → « FR »), « » si aucun."""
    m = _LANG_RE.match(name)
    return m.group(1) if m else ""


def clean_name(name: str) -> str:
    """Nom sans le préfixe de langue (« |FR| |IT| Titre » → « Titre »)."""
    return _PREFIX_RE.sub("", name).strip() or name.strip()


def year_of(*texts: str) -> str:
    for text in texts:
        found = _YEAR_RE.findall(text or "")
        if found:
            return found[-1]
    return ""


def duration_text(info: dict, movie: bool = False) -> str:
    """« 1 h 20 » ou « 56 min » d'après duration_secs (le champ « duration » est parfois faux).
    Pour un film, moins de 5 minutes veut dire que le fournisseur a compté en minutes."""
    try:
        seconds = int(info.get("duration_secs") or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        return info.get("duration") or ""
    if movie and seconds < 300:
        seconds *= 60
    hours, minutes = divmod(round(seconds / 60), 60)
    return f"{hours} h {minutes:02d}" if hours else f"{minutes} min"


def _first(value) -> str:
    """Une adresse, ou la première d'une liste (backdrop_path est parfois une liste)."""
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], str) else ""
    return value if isinstance(value, str) else ""


def _norm(text: str) -> str:
    from .gui import normalize  # même recherche que la page du Mac (accents, majuscules)

    return normalize(text)


@dataclass
class XtreamAccount:
    base: str  # http(s)://serveur[:port] de l'accès Xtream (celui du lien de la playlist)
    username: str
    password: str

    @classmethod
    def from_playlist_source(cls, source: str) -> "XtreamAccount | None":
        """Le lien « get.php?username=…&password=… » d'une playlist Xtream, sinon None."""
        if not source.startswith(("http://", "https://")):
            return None
        url = urlparse(source)
        query = parse_qs(url.query)
        user, password = query.get("username", [""])[0], query.get("password", [""])[0]
        if not user or not password:
            return None
        return cls(f"{url.scheme}://{url.netloc}", user, password)

    def secrets(self) -> list[str]:
        host = urlparse(self.base)
        return [s for s in (self.username, self.password, host.netloc, host.hostname) if s]


class XtreamClient:
    def __init__(self, account: XtreamAccount, session: requests.Session | None = None):
        self.account = account
        self.session = session or requests.Session()

    def call(self, action: str | None = None, **params) -> object:
        query = {"username": self.account.username, "password": self.account.password}
        if action:
            query["action"] = action
        query.update(params)
        resp = self.session.get(self.account.base + "/player_api.php", params=query, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()


class Catalog:
    """Le catalogue en mémoire, gardé sur le disque (fichier privé) et rechargé chaque jour."""

    LISTS = {  # nom du fichier : action Xtream
        "series_categories": "get_series_categories",
        "series": "get_series",
        "vod_categories": "get_vod_categories",
        "vod": "get_vod_streams",
    }

    def __init__(
        self,
        client_factory: Callable[[], XtreamClient | None],
        channels: Callable[[], list[Channel]],
        directory: Path | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self._client_factory = client_factory
        self._channels = channels
        self.directory = Path(directory) if directory else default_catalog_dir()
        self._clock = clock
        self._lock = threading.Lock()
        self._data: dict[str, list] | None = None
        self._loaded_at = 0.0
        self._refreshing = False
        self._info: dict[int, tuple[float, dict]] = {}
        self._index_for: list[Channel] | None = None
        self._index: dict[tuple[str, str], tuple[int, str]] = {}
        self._secrets: list[str] = []
        self._stream_hosts: set[str] = set()

    # --- disponibilité et chargement ---

    def available(self) -> bool:
        return self._client_factory() is not None

    def _client(self) -> XtreamClient:
        client = self._client_factory()
        if client is None:
            raise LookupError("La playlist n'est pas un lien Xtream Codes : catalogue indisponible.")
        self._secrets = client.account.secrets()
        return client

    def _fetch_all(self) -> dict[str, list]:
        client = self._client()
        data = {name: client.call(action) or [] for name, action in self.LISTS.items()}
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:  # mkstemp : lisible par l'utilisateur seul
            json.dump({"saved_at": self._clock(), **data}, f, ensure_ascii=False)
        os.replace(tmp, self.directory / "catalog.json")
        return data

    def _ensure(self) -> dict[str, list]:
        client = self._client_factory()
        if client is None:
            raise LookupError("La playlist n'est pas un lien Xtream Codes : catalogue indisponible.")
        self._secrets = client.account.secrets()
        with self._lock:
            if self._data is None:
                try:
                    saved = json.loads((self.directory / "catalog.json").read_text(encoding="utf-8"))
                    self._data = {k: saved[k] for k in self.LISTS}
                    self._loaded_at = float(saved.get("saved_at", 0))
                except (OSError, ValueError, KeyError):
                    self._data = self._fetch_all()
                    self._loaded_at = self._clock()
            stale = self._clock() - self._loaded_at > REFRESH_SECONDS
            if stale and not self._refreshing:
                self._refreshing = True
                threading.Thread(target=self._refresh, daemon=True).start()
            return self._data

    def _refresh(self) -> None:
        try:
            data = self._fetch_all()
            with self._lock:
                self._data, self._loaded_at, self._info = data, self._clock(), {}
        except Exception:
            pass  # on garde l'ancien catalogue ; nouvel essai au prochain affichage
        finally:
            self._refreshing = False

    def refresh_now(self) -> None:
        data = self._fetch_all()
        with self._lock:
            self._data, self._loaded_at, self._info = data, self._clock(), {}

    # --- lien avec la playlist ---

    def _video_index(self) -> dict[tuple[str, str], tuple[int, str]]:
        """(« series »|« movie », numéro) → (entrée de la playlist, extension)."""
        channels = self._channels()
        if self._index_for is not channels:
            index, hosts = {}, set()
            for i, channel in enumerate(channels):
                url = urlparse(channel.url)
                m = _PATH_RE.search(url.path)
                if m:
                    index[(m.group(1), m.group(2))] = (i, m.group(3))
                    hosts.add(url.netloc)
            self._index, self._index_for, self._stream_hosts = index, channels, hosts
        return self._index

    def video_id(self, kind: str, stream_id) -> int:
        found = self._video_index().get((kind, str(stream_id)))
        return found[0] if found else -1

    def _image(self, url) -> str:
        """Adresse d'image transmise à la télé, sauf si elle trahit le compte ou le serveur."""
        url = url if isinstance(url, str) else ""
        if not url.startswith(("http://", "https://")):
            return ""
        self._video_index()  # connaît alors aussi le serveur des vidéos
        hidden = self._secrets + sorted(self._stream_hosts)
        return "" if any(s and s in url for s in hidden) else url

    # --- listes ---

    def categories(self, kind: str, lang: str = "FR") -> list[dict]:
        data = self._ensure()
        items = data["series"] if kind == "series" else data["vod"]
        counts: dict[str, int] = {}
        for item in items:
            if not lang or language_of(item.get("name", "")) == lang:
                cat = str(item.get("category_id"))
                counts[cat] = counts.get(cat, 0) + 1
        cats = data["series_categories"] if kind == "series" else data["vod_categories"]
        return [{"id": str(c["category_id"]), "name": clean_name(c.get("category_name", "")),
                 "count": counts[str(c["category_id"])]}
                for c in cats if counts.get(str(c["category_id"]))]

    def _matching(self, items: list, category: str, query: str, lang: str) -> list:
        words = _norm(query).split()
        return [
            item for item in items
            if (not lang or language_of(item.get("name", "")) == lang)
            and (not category or str(item.get("category_id")) == category)
            and all(w in _norm(item.get("name", "")) for w in words)
        ]

    def series(self, category: str = "", query: str = "", lang: str = "FR",
               offset: int = 0, limit: int = 60) -> dict:
        found = self._matching(self._ensure()["series"], category, query, lang)
        page = found[offset: offset + limit]
        return {"total": len(found), "items": [{
            "series_id": s.get("series_id"), "name": clean_name(s.get("name", "")),
            "cover": self._image(s.get("cover")),
            "year": (s.get("releaseDate") or "")[:4] or year_of(s.get("name", "")),
            "rating": s.get("rating") or "", "genre": s.get("genre") or "",
        } for s in page]}

    def movies(self, category: str = "", query: str = "", lang: str = "FR",
               offset: int = 0, limit: int = 60, is_ready: Callable[[int], bool] | None = None) -> dict:
        found = self._matching(self._ensure()["vod"], category, query, lang)
        page = found[offset: offset + limit]
        items = []
        for v in page:
            vid = self.video_id("movie", v.get("stream_id"))
            items.append({
                "vod_id": v.get("stream_id"), "id": vid, "name": clean_name(v.get("name", "")),
                "cover": self._image(v.get("stream_icon")), "year": year_of(v.get("name", "")),
                "rating": v.get("rating") or "",
                "ready": bool(is_ready and vid >= 0 and is_ready(vid)),
            })
        return {"total": len(found), "items": items}

    # --- fiches ---

    def _series_info(self, series_id: int) -> dict:
        cached = self._info.get(series_id)
        if cached and self._clock() - cached[0] < INFO_SECONDS:
            return cached[1]
        info = self._client().call("get_series_info", series_id=series_id) or {}
        self._info[series_id] = (self._clock(), info)
        return info

    def series_detail(self, series_id: int, is_ready: Callable[[int], bool] | None = None) -> dict:
        data = self._ensure()
        summary = next((s for s in data["series"] if str(s.get("series_id")) == str(series_id)), None)
        if summary is None:
            raise KeyError("Série introuvable : le catalogue a peut-être changé.")
        info = self._series_info(int(series_id))
        about = info.get("info") or {}
        episodes = info.get("episodes") or {}
        if isinstance(episodes, list):  # certains serveurs : liste de saisons au lieu d'un dict
            episodes = {str(i + 1): season for i, season in enumerate(episodes)}
        names = {str(s.get("season_number")): s.get("name") or "" for s in info.get("seasons") or []}
        seasons = []
        for number in sorted(episodes, key=lambda n: int(n) if str(n).isdigit() else 0):
            items = []
            for e in sorted(episodes[number], key=lambda e: int(e.get("episode_num") or 0)):
                einfo = e.get("info") if isinstance(e.get("info"), dict) else {}
                vid = self.video_id("series", e.get("id"))
                items.append({
                    "id": vid, "episode": int(e.get("episode_num") or 0),
                    "title": clean_name(e.get("title") or ""),
                    "duration": duration_text(einfo), "air_date": einfo.get("air_date") or "",
                    "rating": einfo.get("rating") or "", "image": self._image(einfo.get("movie_image")),
                    "plot": einfo.get("plot") or "",
                    "ready": bool(is_ready and vid >= 0 and is_ready(vid)),
                })
            seasons.append({"season": int(number) if str(number).isdigit() else 0,
                            "name": names.get(str(number)) or f"Saison {number}", "episodes": items})
        return {
            "series_id": summary.get("series_id"), "name": clean_name(summary.get("name", "")),
            "cover": self._image(about.get("cover") or summary.get("cover")),
            "backdrop": self._image(_first(about.get("backdrop_path")) or _first(summary.get("backdrop_path"))),
            "plot": about.get("plot") or summary.get("plot") or "",
            "genre": about.get("genre") or summary.get("genre") or "",
            "cast": about.get("cast") or summary.get("cast") or "",
            "director": about.get("director") or summary.get("director") or "",
            "year": (about.get("releaseDate") or summary.get("releaseDate") or "")[:4],
            "rating": about.get("rating") or summary.get("rating") or "",
            "seasons": seasons,
        }

    def movie_detail(self, vod_id: int, is_ready: Callable[[int], bool] | None = None) -> dict:
        data = self._ensure()
        summary = next((v for v in data["vod"] if str(v.get("stream_id")) == str(vod_id)), None)
        if summary is None:
            raise KeyError("Film introuvable : le catalogue a peut-être changé.")
        info = (self._client().call("get_vod_info", vod_id=vod_id) or {}).get("info") or {}
        if not isinstance(info, dict):
            info = {}
        vid = self.video_id("movie", vod_id)
        return {
            "vod_id": summary.get("stream_id"), "id": vid, "name": clean_name(summary.get("name", "")),
            "cover": self._image(info.get("cover_big") or info.get("movie_image") or summary.get("stream_icon")),
            "plot": info.get("plot") or info.get("description") or "",
            "genre": info.get("genre") or "", "cast": info.get("cast") or info.get("actors") or "",
            "director": info.get("director") or "", "duration": duration_text(info, movie=True),
            "year": (info.get("releasedate") or "")[:4] or year_of(summary.get("name", "")),
            "rating": summary.get("rating") or info.get("rating") or "",
            "ready": bool(is_ready and vid >= 0 and is_ready(vid)),
        }
