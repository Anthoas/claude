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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import requests

from .cache import default_cache_path
from .playlist import Channel
from .tmdb import EpisodeGuide, tmdb_size

REFRESH_SECONDS = 24 * 3600  # le catalogue est rechargé une fois par jour
INFO_SECONDS = 3600  # détail d'une série gardé une heure
TIMEOUT = 120
_LANG_RE = re.compile(r"^\W*([A-Z]{2,3})\W")  # « |FR| Titre », « FR| Titre »
_PREFIX_RE = re.compile(r"^(?:\s*\|?[A-Z]{2,3}(?:\s[^|\n]{0,12})?\|\s*)+")  # « |FR| », « |FR DV⁴ᴷ| »
_YEAR_RE = re.compile(r"\b((?:19|20)\d\d)\b")
_PATH_RE = re.compile(r"/(series|movie)/[^/]+/[^/]+/(\d+)\.(\w+)$")
_EPISODE_MARK = re.compile(r"\s*\bS\d{1,3}\s*E\d{1,4}\s*$", re.IGNORECASE)  # « … S06 E06 »


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


def rating_text(value) -> str:
    """« 7.373 » → « 7.4 », « 8 » → « 8 », 0 ou vide → « »."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:.1f}".rstrip("0").rstrip(".") if number > 0 else ""


_EPISODE_TITLE_RE = re.compile(r"S\d+\s*E\d+\s*-\s*(.+?)\s*$", re.IGNORECASE)


def episode_title(full_title: str, info: dict) -> str:
    """Vrai titre de l'épisode s'il existe : « … - S01 E01 - Il fabrique des réfrigérateurs »
    ou champ « name » ; « » sinon (le plus souvent : « Série - S01E01 »)."""
    m = _EPISODE_TITLE_RE.search(full_title or "")
    if m:
        return m.group(1)
    name = info.get("name") if isinstance(info.get("name"), str) else ""
    return "" if not name or re.search(r"S\d+\s*E\d+", name) else name.strip()


Status = Callable[[int], dict]


def video_status(status: "Status | None", vid: int) -> dict:
    """Prête, vue, avancement (0 à 1) d'une vidéo de la playlist."""
    s = status(vid) if status and vid >= 0 else {}
    return {"ready": bool(s.get("ready")), "watched": bool(s.get("watched")),
            "progress": float(s.get("progress") or 0.0)}


def next_episode(seasons: list[dict]) -> dict:
    """Saison et épisode (indices) à proposer : celui en cours, sinon le suivant du dernier vu."""
    order = [(si, ei, e) for si, s in enumerate(seasons) if s["season"] > 0 for ei, e in enumerate(s["episodes"])]
    last = None
    for position, (si, ei, e) in enumerate(order):
        if e["progress"] > 0 and not e["watched"]:
            last = (position, False)
        elif e["watched"]:
            last = (position, True)
    if not order:
        return {"season": 0, "episode": 0}
    if last is None:
        index = 0
    else:
        index = min(last[0] + 1, len(order) - 1) if last[1] else last[0]
    return {"season": order[index][0], "episode": order[index][1]}


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
        channels: Callable[[], list[tuple[int, Channel]]],  # (numéro de la vidéo, vidéo)
        directory: Path | None = None,
        clock: Callable[[], float] = time.time,
        guide: EpisodeGuide | None = None,
    ):
        self._client_factory = client_factory
        self.guide = guide
        # Traduction des titres d'épisodes (branchée par GuiApp ; None : titres non traduits).
        # Renvoie {titre: traduction}, ou ({titre: traduction}, traduction en cours ?).
        self.title_translator: Callable[[list[str]], object] | None = None
        self._channels = channels
        self.directory = Path(directory) if directory else default_catalog_dir()
        self._clock = clock
        self._lock = threading.Lock()
        self._data: dict[str, list] | None = None
        self._loaded_at = 0.0
        self._refreshing = False
        self._info: dict[int, tuple[float, dict]] = {}
        self._index_for: list | None = None
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

    def reset(self) -> None:
        """Autre source (autre compte) : on oublie le catalogue, il sera redemandé au besoin."""
        with self._lock:
            self._data, self._loaded_at, self._info, self._index_for = None, 0.0, {}, None
        (self.directory / "catalog.json").unlink(missing_ok=True)

    def refresh_now(self) -> None:
        data = self._fetch_all()
        with self._lock:
            self._data, self._loaded_at, self._info = data, self._clock(), {}

    # --- lien avec la playlist ---

    def _video_index(self) -> dict[tuple[str, str], tuple[int, str]]:
        """(« series »|« movie », numéro Xtream) → (numéro de la vidéo dans subtrad, extension)."""
        channels = self._channels()
        if self._index_for is not channels:
            index, hosts = {}, set()
            for i, channel in channels:
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
        # « FR| COMÉDIE » → « COMÉDIE » ; « SD| NOUVEAUTÉS » garde son préfixe (qualité, pas langue).
        def label(name: str) -> str:
            return clean_name(name) if lang and language_of(name) == lang else name.strip()

        return [{"id": str(c["category_id"]), "name": label(c.get("category_name", "")),
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
            "rating": rating_text(s.get("rating")), "genre": s.get("genre") or "",
        } for s in page]}

    def movies(self, category: str = "", query: str = "", lang: str = "FR",
               offset: int = 0, limit: int = 60, status: Status | None = None) -> dict:
        found = self._matching(self._ensure()["vod"], category, query, lang)
        page = found[offset: offset + limit]
        items = []
        for v in page:
            vid = self.video_id("movie", v.get("stream_id"))
            items.append({
                "vod_id": v.get("stream_id"), "id": vid, "name": clean_name(v.get("name", "")),
                "cover": self._image(v.get("stream_icon")), "year": year_of(v.get("name", "")),
                "rating": rating_text(v.get("rating")), **video_status(status, vid),
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

    def series_detail(self, series_id: int, status: Status | None = None) -> dict:
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
        tmdb_ids = []  # le fournisseur cache souvent le numéro TMDB de la série dans info.id
        for number in sorted(episodes, key=lambda n: int(n) if str(n).isdigit() else 0):
            items = []
            for e in sorted(episodes[number], key=lambda e: int(e.get("episode_num") or 0)):
                einfo = e.get("info") if isinstance(e.get("info"), dict) else {}
                if str(einfo.get("id") or "").isdigit():
                    tmdb_ids.append(int(einfo["id"]))
                vid = self.video_id("series", e.get("id"))
                items.append({
                    "id": vid, "episode": int(e.get("episode_num") or 0),
                    "title": episode_title(e.get("title") or "", einfo),
                    "duration": duration_text(einfo), "air_date": einfo.get("air_date") or "",
                    "rating": rating_text(einfo.get("rating")), "image": self._image(einfo.get("movie_image")),
                    "plot": einfo.get("plot") or "", **video_status(status, vid),
                })
            seasons.append({"season": int(number) if str(number).isdigit() else 0,
                            "name": names.get(str(number)) or f"Saison {number}", "episodes": items})
        year = (about.get("releaseDate") or summary.get("releaseDate") or "")[:4]
        self._complete_with_tmdb(seasons, tmdb_ids, clean_name(summary.get("name", "")), year)
        titles_pending = self._translate_titles(seasons)
        for season in seasons:  # miniature nette pour la liste, grande image pour la fiche
            for e in season["episodes"]:
                e["image_large"] = tmdb_size(e["image"], "w780")
                e["image"] = tmdb_size(e["image"], "w300")
        return {
            "titles_pending": titles_pending,
            "series_id": summary.get("series_id"), "name": clean_name(summary.get("name", "")),
            "cover": self._image(about.get("cover") or summary.get("cover")),
            "backdrop": tmdb_size(self._image(_first(about.get("backdrop_path")) or _first(summary.get("backdrop_path"))),
                                  "w1280"),
            "plot": about.get("plot") or summary.get("plot") or "",
            "genre": about.get("genre") or summary.get("genre") or "",
            "cast": about.get("cast") or summary.get("cast") or "",
            "director": about.get("director") or summary.get("director") or "",
            "year": (about.get("releaseDate") or summary.get("releaseDate") or "")[:4],
            "rating": rating_text(about.get("rating") or summary.get("rating")),
            "seasons": seasons, "next": next_episode(seasons),
        }

    def episode_of(self, video_id: int, name: str, status: Status | None = None) -> dict | None:
        """Ce que l'onglet Séries montre pour cet épisode de la playlist (image, titres, résumé…),
        avec sa série et sa saison ; None si la série n'est pas retrouvée dans le catalogue.
        La série est retrouvée par le nom de l'épisode sans « S06 E06 »."""
        series_name = _EPISODE_MARK.sub("", name).strip()
        if not series_name or series_name == name.strip():
            return None
        series = self._ensure()["series"]
        found = [x for x in series if (x.get("name") or "").strip() == series_name] or \
                [x for x in series if _norm(x.get("name") or "").strip() == _norm(series_name).strip()]
        for summary in found:
            detail = self.series_detail(int(summary.get("series_id")), status)
            for season in detail["seasons"]:
                for e in season["episodes"]:
                    if e["id"] == video_id:
                        return {"series_id": detail["series_id"], "series_name": detail["name"],
                                "season": season["season"], "season_name": season["name"],
                                "titles_pending": detail["titles_pending"], "episode": e}
        return None

    def _complete_with_tmdb(self, seasons: list[dict], tmdb_ids: list[int], name: str, year: str) -> None:
        """Titres, résumés et images d'épisodes que le fournisseur ne donne pas (si clé TMDB)."""
        if self.guide is None or not self.guide.available():
            return
        try:
            tv_id = max(set(tmdb_ids), key=tmdb_ids.count) if tmdb_ids else self.guide.find_series(name, year)
            if not tv_id:
                return
            numbers = [s["season"] for s in seasons if s["season"] > 0]
            with ThreadPoolExecutor(max_workers=4) as pool:
                found = dict(zip(numbers, pool.map(lambda n: self.guide.season(tv_id, n), numbers)))
        except Exception:
            return  # TMDB injoignable ou clé refusée : on garde ce que donne le fournisseur
        for season in seasons:
            extra = found.get(season["season"]) or {}
            for e in season["episodes"]:
                more = extra.get(e["episode"])
                if more:
                    e["title"] = e["title"] or more["title"]
                    e["plot"] = e["plot"] or more["plot"]
                    e["image"] = e["image"] or more["image"]
                    e["air_date"] = e["air_date"] or more["air_date"]

    def _translate_titles(self, seasons: list[dict]) -> bool:
        """« title_translated » : le titre dans la langue de la traduction (indonésien).
        Renvoie True si des traductions arrivent bientôt (la télé redemande la fiche)."""
        episodes = [e for s in seasons for e in s["episodes"]]
        for e in episodes:
            e["title_translated"] = ""
        if self.title_translator is None:
            return False
        try:
            result = self.title_translator([e["title"] for e in episodes if e["title"]])
        except Exception:
            return False  # pas de clé, réseau, refus : les titres restent en français
        done, pending = result if isinstance(result, tuple) else (result, False)
        for e in episodes:
            e["title_translated"] = done.get(e["title"], "")
        return pending

    def movie_detail(self, vod_id: int, status: Status | None = None) -> dict:
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
            "rating": rating_text(summary.get("rating") or info.get("rating")), **video_status(status, vid),
        }
