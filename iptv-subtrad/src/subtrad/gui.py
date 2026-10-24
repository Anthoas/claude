"""Interface graphique : une page web servie par ce Mac (127.0.0.1), à ouvrir dans Chrome.

Le serveur ne répond qu'aux requêtes locales portant le jeton de la session, pour qu'aucun
autre site ouvert dans le navigateur ne puisse piloter le programme.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import anthropic

from . import transcribe
from .cache import TranslationCache, default_cache_path
from .errors import Cancelled, friendly_error
from .hls import HlsClient
from .live import Timeline, display_loop, run_live
from .pipeline import CueSource, NoSubtitles, check_subtitles, open_cue_source
from .player import MpvPlayer, VlcPlayer
from .playlist import Channel, fetch_playlist_text, parse_m3u
from .sources import SLOT_SIZE, Source, build_source, normalize_server
from .store import VideoStore
from .subtitles import Cue, load_subtitles, save_subtitles
from .tmdb import EpisodeGuide, TmdbClient
from .translate import DEFAULT_MODEL, ClaudeTranslator, TranslationPipeline
from .xtream import Catalog, XtreamAccount, XtreamClient

MODELS = {
    "claude-haiku-5-5": "Haiku (économique, conseillé)",
    "claude-sonnet-5-5": "Sonnet (plus fin, ~20x plus cher)",
}
KIND_LABELS = {"direct": "Direct", "film": "Film", "serie": "Série"}
PLAYERS = {
    "vlc": "VLC : la vidéo s'ouvre quand la traduction est terminée",
    "mpv": "mpv : démarrage rapide, la vidéo commence pendant la traduction",
}
PLAYER_NAMES = {"vlc": "VLC", "mpv": "mpv"}
LANGUAGE_LABELS = {"id": "Indonésien", "en": "Anglais", "fr": "Français"}
TRANSLATION_WORKERS = 4  # lots envoyés à Claude en même temps
READY_CUES = 10  # démarrage rapide : répliques traduites avant d'ouvrir la vidéo
TV_READY_STEP = "Prêt : la vidéo peut être regardée sur la télé."


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "subtrad"


def normalize(text: str) -> str:
    """Minuscules sans accents : « Télé » et « tele » se trouvent l'un l'autre."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


class Settings:
    """Réglages enregistrés sur ce Mac uniquement (le lien M3U contient souvent un mot de
    passe et la clé Claude en est un) : fichier lisible par l'utilisateur seul."""

    DEFAULTS = {"playlist_source": "", "sources": [], "next_slot": 0, "api_key": "",
                "model": DEFAULT_MODEL, "depuis": "fr", "vers": "id", "lecteur": "vlc",
                "whisper": "on", "tele": "off", "tele_code": "", "tmdb_key": ""}
    CHOICES = {"lecteur": set(PLAYERS), "whisper": {"on", "off"}, "model": set(MODELS),
               "tele": {"on", "off"}}

    def __init__(self, directory: Path):
        self.path = directory / "config.json"
        self.data = copy.deepcopy(self.DEFAULTS)
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))

    def __getitem__(self, key: str) -> str:
        return self.data[key]

    def update(self, **values: str) -> None:
        for key, value in values.items():
            if key in self.CHOICES and value not in self.CHOICES[key]:
                raise ValueError(f"Valeur inconnue pour « {key} » : {value}")
        self.data.update({k: v for k, v in values.items() if k in self.DEFAULTS})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def api_key(self) -> str:
        return self.data["api_key"] or os.environ.get("ANTHROPIC_API_KEY", "")

    def tv_code(self) -> str:
        """Code à 6 chiffres que la télé doit donner ; créé au premier besoin."""
        if not self.data["tele_code"]:
            self.new_tv_code()
        return self.data["tele_code"]

    def new_tv_code(self) -> str:
        self.update(tele_code=f"{secrets.randbelow(10**6):06d}")
        return self.data["tele_code"]

    def public(self) -> dict:
        return {
            "model": self.data["model"], "depuis": self.data["depuis"],
            "vers": self.data["vers"], "has_api_key": bool(self.api_key()),
            "api_key_from_env": not self.data["api_key"] and bool(self.api_key()),
            "models": MODELS, "lecteur": self.data["lecteur"], "players": PLAYERS,
            "whisper": self.data["whisper"], "tele": self.data["tele"],
            "tele_code": self.tv_code() if self.data["tele"] == "on" else "",
            "has_tmdb_key": bool(self.data["tmdb_key"]),
        }


class Library:
    """Toutes les sources en mémoire, avec un index de recherche.

    Chaque vidéo a un numéro qui ne bouge pas quand on ajoute, retire ou actualise une autre
    source : `slot * SLOT_SIZE + rang dans la source`. La page peut donc rester ouverte.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._parts: dict[int, list[Channel]] = {}
        self._ids: list[int] = []
        self.channels: list[Channel] = []
        self.entries: list[tuple[int, Channel]] = []  # (numéro stable, vidéo), recréée à chaque changement
        self._haystacks: list[str] = []
        self._index: dict[int, Channel] = {}

    def set_source(self, slot: int, channels: list[Channel]) -> int:
        with self._lock:
            self._parts[slot] = channels
            self._rebuild()
        return len(channels)

    def remove_source(self, slot: int) -> None:
        with self._lock:
            self._parts.pop(slot, None)
            self._rebuild()

    def load_text(self, text: str, slot: int = 0, source: str = "") -> int:
        return self.set_source(slot, parse_m3u(text, source))

    def _rebuild(self) -> None:
        ids, channels = [], []
        for slot in sorted(self._parts):
            for rank, channel in enumerate(self._parts[slot]):
                ids.append(slot * SLOT_SIZE + rank)
                channels.append(channel)
        self._ids, self.channels = ids, channels
        self.entries = list(zip(ids, channels))
        self._index = dict(zip(ids, channels))
        self._haystacks = [normalize(f"{c.name} {c.group}") for c in channels]

    def get(self, vid: int) -> Channel:
        with self._lock:
            if vid not in self._index:
                raise KeyError("Vidéo introuvable : la liste a changé, relance la recherche.")
            return self._index[vid]

    def _matching(self, query: str, kind: str, group: str, source: str = "") -> list[int]:
        words = normalize(query).split()
        return [
            pos for pos, (channel, hay) in enumerate(zip(self.channels, self._haystacks))
            if (not kind or channel.kind == kind)
            and (not group or channel.group == group)
            and (not source or channel.source == source)
            and all(w in hay for w in words)
        ]

    def search(self, query="", kind="", group="", offset=0, limit=100, source="") -> dict:
        with self._lock:
            found = self._matching(query, kind, group, source)
            items = [
                {"id": self._ids[pos], "name": self.channels[pos].name,
                 "group": self.channels[pos].group, "logo": self.channels[pos].logo,
                 "kind": self.channels[pos].kind, "source": self.channels[pos].source,
                 "kind_label": KIND_LABELS[self.channels[pos].kind]}
                for pos in found[offset : offset + limit]
            ]
        return {"total": len(found), "items": items}

    def groups(self, kind: str = "", source: str = "") -> list[dict]:
        counts: dict[str, int] = {}
        with self._lock:
            for channel in self.channels:
                if (channel.group and (not kind or channel.kind == kind)
                        and (not source or channel.source == source)):
                    counts[channel.group] = counts.get(channel.group, 0) + 1
        return [{"name": g, "count": n}
                for g, n in sorted(counts.items(), key=lambda x: normalize(x[0]))]

    def kinds(self) -> dict[str, int]:
        counts = {k: 0 for k in KIND_LABELS}
        with self._lock:
            for channel in self.channels:
                counts[channel.kind] += 1
        return counts


@dataclass
class Job:
    """Une lecture lancée depuis la page, suivie par la page toutes les secondes."""

    id: str
    title: str
    state: str = "running"  # running | playing | done | error | cancelled
    phase: int = 1  # 1 = récupération des sous-titres, 2 = traduction, 3 = lecture
    step: str = "Recherche des sous-titres…"
    fetch_step: str = ""  # ce que fait la récupération des sous-titres en ce moment
    fraction: float | None = None  # avancement de la récupération (0 à 1), None si inconnu
    fetch_done: bool = False
    found: int = 0  # répliques récupérées
    translated: int = 0  # répliques traduites
    player: str = ""
    note: str = ""
    usage: str = ""
    error: str = ""
    started_at: float = 0.0  # horodatage UNIX : la page en déduit le temps écoulé
    channel_id: int = -1  # entrée de la liste concernée
    channel_url: str = field(default="", repr=False)  # jamais envoyé à la page (identifiants)
    saved: bool = False  # les sous-titres traduits sont gardés : la prochaine ouverture sera immédiate
    target: str = "mac"  # mac = lecture sur ce Mac ; tele = préparation pour la télé (aucun lecteur ici)


def job_public(job: Job) -> dict:
    """Ce que la page voit d'une lecture : jamais l'adresse du flux (identifiants)."""
    data = asdict(job)
    data.pop("channel_url", None)
    return data


def _default_player(name: str):
    return MpvPlayer() if name == "mpv" else VlcPlayer()


class GuiApp:
    def __init__(
        self,
        settings: Settings,
        playlist_cache: Path,
        translator_factory: Callable[[Settings], ClaudeTranslator] | None = None,
        player_factory: Callable[[str], object] | None = None,
        cache_factory: Callable[[], TranslationCache] | None = None,
        hls: HlsClient | None = None,
        transcriber_factory: Callable[[], object] | None = None,
        whisper_backend: Callable[[], str | None] | None = None,
        store: VideoStore | None = None,
        catalog: Catalog | None = None,
    ):
        self.settings = settings
        self.playlist_dir = playlist_cache.parent / "playlists"  # une copie par source
        self.sources: list[Source] = []
        self.library = Library()
        self.jobs: dict[str, Job] = {}
        self._events: dict[str, tuple[threading.Event, threading.Event]] = {}
        self._players: dict[str, object] = {}
        self.make_translator = translator_factory or self._default_translator
        self.make_player = player_factory or _default_player
        self.make_cache = cache_factory or TranslationCache
        self.hls = hls or HlsClient()
        self.store = store or VideoStore()
        self._transcriber = None
        self._transcriber_factory = transcriber_factory or transcribe.make_transcriber
        self.whisper_backend = whisper_backend or transcribe.backend_name
        self._load_saved_sources(old_cache=playlist_cache)
        self.tv = None  # TvAccess, branché par run_gui
        self.guide = EpisodeGuide(self._tmdb_client)
        self.catalog = catalog or Catalog(self._xtream_client, lambda: self.library.entries, guide=self.guide)
        self.catalog.title_translator = self.translate_titles_soon
        self._titles_lock = threading.Lock()
        self._titles_running: set[str] = set()  # titres en cours de traduction (arrière-plan)

    @staticmethod
    def _default_translator(settings: Settings) -> ClaudeTranslator:
        if not settings.api_key():
            raise RuntimeError("Aucune clé Claude : renseigne-la dans les réglages (⚙).")
        return ClaudeTranslator(
            source=settings["depuis"], target=settings["vers"], model=settings["model"],
            client=anthropic.Anthropic(api_key=settings.api_key()),
        )

    def _whisper_enabled(self) -> bool:
        return self.settings["whisper"] == "on" and self.whisper_backend() is not None

    def _get_transcriber(self):
        if self._transcriber is None:  # le modèle se charge une fois pour toutes les vidéos
            self._transcriber = self._transcriber_factory()
        return self._transcriber

    # --- sources ---

    def _cache_file(self, source: Source) -> Path:
        return self.playlist_dir / f"{source.id}.m3u"

    def _save_sources(self) -> None:
        self.settings.update(sources=[src.to_dict() for src in self.sources])

    def _write_cache(self, source: Source, text: str) -> None:
        self.playlist_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._cache_file(source), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)

    def _load_saved_sources(self, old_cache: Path) -> None:
        """Relit les sources enregistrées depuis le disque (sans réseau), et reprend l'ancienne
        playlist unique des versions précédentes."""
        self.sources = [Source.from_dict(d) for d in self.settings["sources"]]
        old_link = self.settings["playlist_source"]
        if not self.sources and (old_link or old_cache.exists()):
            kind = "m3u" if old_link else "fichier"
            migrated = build_source(kind, "Playlist", slot=-1, url=old_link)
            migrated.slot = self._next_slot()
            self.sources.append(migrated)
            if old_cache.exists():
                text = old_cache.read_text(encoding="utf-8", errors="replace")
                self._write_cache(migrated, text)
                migrated.count = len(parse_m3u(text))
                old_cache.unlink(missing_ok=True)
            self.settings.update(playlist_source="")
            self._save_sources()
        for source in self.sources:
            path = self._cache_file(source)
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                source.count = self.library.set_source(source.slot, parse_m3u(text, source.name))

    def _next_slot(self) -> int:
        slot = max(self.settings["next_slot"], 1 + max((s.slot for s in self.sources), default=-1))
        self.settings.update(next_slot=slot + 1)  # un numéro n'est jamais réutilisé
        return slot

    def public_sources(self) -> list[dict]:
        return [src.public() for src in self.sources]

    def _find_source(self, source_id: str) -> Source:
        for source in self.sources:
            if source.id == source_id:
                return source
        raise KeyError("Source introuvable.")

    def _load_source(self, source: Source, text: str | None = None) -> int:
        """Télécharge (ou reçoit) la playlist d'une source, la garde sur le disque et l'indexe."""
        if text is None:
            text = fetch_playlist_text(source.playlist_url())
        if "#EXTINF" not in text:
            raise ValueError("Ce n'est pas une playlist M3U (aucune ligne #EXTINF) : vérifie "
                             "l'adresse, l'identifiant et le mot de passe.")
        self._write_cache(source, text)
        source.count = self.library.set_source(source.slot, parse_m3u(text, source.name))
        source.updated_at, source.error = time.time(), ""
        return source.count

    def add_source(self, kind: str, name: str = "", url: str = "", server: str = "",
                   username: str = "", password: str = "", text: str = "") -> dict:
        """Ajoute une source ; elle n'est enregistrée que si sa playlist se charge."""
        source = build_source(kind, name, slot=-1, url=url, server=server,
                              username=username, password=password)  # valide la saisie
        if kind == "fichier" and not text.strip():
            raise ValueError("Le fichier est vide.")
        taken = {src.name.casefold() for src in self.sources}
        base, n = source.name, 2
        while source.name.casefold() in taken:  # deux sources ne portent jamais le même nom
            source.name, n = f"{base} ({n})", n + 1
        source.slot = self._next_slot()
        self._load_source(source, text or None)  # lève une erreur si ça ne marche pas
        self.sources.append(source)
        self._save_sources()
        return source.public()

    def remove_source(self, source_id: str) -> dict:
        source = self._find_source(source_id)
        self.sources.remove(source)
        self.library.remove_source(source.slot)
        self._cache_file(source).unlink(missing_ok=True)
        self._save_sources()
        return {"removed": source_id}

    def refresh_sources(self, source_id: str = "") -> list[dict]:
        """Retélécharge une source (ou toutes) ; une source en panne n'arrête pas les autres."""
        targets = [self._find_source(source_id)] if source_id else list(self.sources)
        for source in targets:
            if not source.refreshable:
                continue
            try:
                self._load_source(source)
            except Exception as exc:
                source.error = friendly_error(exc)
        self._save_sources()
        return self.public_sources()

    def load_playlist(self, source: str = "", text: str = "") -> dict:
        """Ajoute une playlist (lien ou texte) : conservé pour la compatibilité."""
        if source:
            added = self.add_source("m3u", "Playlist", url=source)
        else:
            added = self.add_source("fichier", "Playlist", text=text)
        return {"count": added["count"]}

    # --- mémoire par vidéo ---

    def _store_args(self, channel: Channel) -> tuple[str, str, str, str]:
        return (channel.url, self.settings["depuis"], self.settings["vers"], self.settings["model"])

    def is_ready(self, channel: Channel) -> bool:
        return self.store.translation_file(*self._store_args(channel)) is not None

    def search(self, query="", kind="", group="", offset=0, limit=100, source="") -> dict:
        result = self.library.search(query, kind, group, offset, limit, source)
        for item in result["items"]:
            channel = self.library.get(item["id"])
            item["ready"] = self.is_ready(channel)
            item["watched"] = self.store.progress(channel.url)["watched"]
        return result

    def forget(self, index: int) -> dict:
        """Oublie les sous-titres gardés pour cette vidéo (pour tout refaire)."""
        self.store.forget(*self._store_args(self.library.get(index)))
        return {"ready": False}

    def translate_titles(self, texts: list[str]) -> dict[str, str]:
        """Titres d'épisodes traduits (ex. en indonésien), avec la mémoire de traduction des
        sous-titres : chaque titre n'est payé qu'une fois. Sans clé Claude : rien."""
        texts = [t for t in dict.fromkeys(texts) if t and t.strip()]
        if not texts or not self.settings.api_key() or self.settings["depuis"] == self.settings["vers"]:
            return {}
        translator = self.make_translator(self.settings)
        cache = self.make_cache()
        done = cache.get_many(translator.namespace, texts)
        todo = [t for t in texts if t not in done]
        for start in range(0, len(todo), 60):
            batch = todo[start:start + 60]
            new = {k: v for k, v in zip(batch, translator.translate_batch(batch, [])) if v and v != k}
            cache.put_many(translator.namespace, new)
            done.update(new)
        return done

    def translate_titles_soon(self, texts: list[str]) -> tuple[dict[str, str], bool]:
        """Comme translate_titles, sans faire attendre la télé : renvoie tout de suite les titres
        déjà traduits et lance les autres en arrière-plan. (traduits, traduction en cours ?)"""
        texts = [t for t in dict.fromkeys(texts) if t and t.strip()]
        if not texts or not self.settings.api_key() or self.settings["depuis"] == self.settings["vers"]:
            return {}, False
        translator = self.make_translator(self.settings)
        done = self.make_cache().get_many(translator.namespace, texts)
        todo = [t for t in texts if t not in done]
        if not todo:
            return done, False
        with self._titles_lock:
            todo = [t for t in todo if t not in self._titles_running]
            self._titles_running.update(todo)
        if todo:
            def work() -> None:
                try:
                    self.translate_titles(todo)
                except Exception:
                    pass  # réseau, refus : le titre restera en français
                finally:
                    with self._titles_lock:
                        self._titles_running.difference_update(todo)

            threading.Thread(target=work, name="subtrad-titres", daemon=True).start()
        return done, True

    def _tmdb_client(self) -> TmdbClient | None:
        key = self.settings["tmdb_key"]
        return TmdbClient(key) if key else None

    def _xtream_client(self) -> XtreamClient | None:
        """Le compte Xtream de la première source qui en a un : serveur + identifiant, ou lien
        « get.php?username=…&password=… »."""
        for source in self.sources:
            account = None
            if source.kind == "xtream":
                account = XtreamAccount(normalize_server(source.server), source.username, source.password)
            elif source.kind == "m3u":
                account = XtreamAccount.from_playlist_source(source.url)
            if account:
                return XtreamClient(account)
        return None

    def video_ready(self, index: int) -> bool:
        return self.is_ready(self.library.get(index))

    def catalog_request(self, path: str, params: dict) -> object:
        """Catalogue Xtream Codes, pour la télé comme pour cette page. `path` : la fin de
        l'adresse après « …/catalog » (« », « /categories », « /series », « /series/info »,
        « /movies », « /movie »)."""
        catalog = self.catalog
        lang = params.get("lang", "FR")
        page = {"category": params.get("category", ""), "query": params.get("q", ""), "lang": lang,
                "offset": int(params.get("offset", 0)), "limit": min(int(params.get("limit", 60)), 200)}
        if path == "":
            return {"available": catalog.available()}
        if path == "/categories":
            return catalog.categories(params.get("type", "series"), lang)
        if path == "/series":
            return catalog.series(**page)
        if path == "/series/info":
            return catalog.series_detail(int(params["id"]), self.video_status)
        if path == "/movies":
            return catalog.movies(**page, status=self.video_status)
        if path == "/movie":
            return catalog.movie_detail(int(params["id"]), self.video_status)
        raise LookupError("Introuvable.")

    def play_original(self, index: int) -> Job:
        """« Regarder en français » : la vidéo telle quelle, sans sous-titres traduits."""
        channel = self.library.get(index)
        job = Job(id=uuid.uuid4().hex[:8], title=channel.name, started_at=time.time(), channel_id=index,
                  channel_url=channel.url, state="playing", phase=3, fetch_done=True,
                  step="Lecture en français, sans traduction.")
        self.jobs[job.id] = job
        self._events[job.id] = (threading.Event(), threading.Event())

        def run() -> None:
            try:
                player = self._start_player(job, self.settings["lecteur"], channel.url, title=channel.name)
                player.wait()
                job.state, job.step = "done", "Terminé."
            except Exception as exc:
                job.state, job.error = "error", friendly_error(exc)
            finally:
                self._players.pop(job.id, None)

        threading.Thread(target=run, daemon=True).start()
        return job

    def video_status(self, index: int) -> dict:
        """Prête (traduite) et regardée : badges et reprise de la lecture sur la télé."""
        channel = self.library.get(index)
        return {"ready": self.is_ready(channel), **self.store.progress(channel.url)}

    def save_progress(self, index: int, position_ms: int, duration_ms: int, ended: bool = False) -> dict:
        return self.store.save_progress(self.library.get(index).url, position_ms, duration_ms, ended)

    # --- télé ---

    def tv_status(self) -> dict:
        return self.tv.status() if self.tv else {"active": False, "error": "", "address": ""}

    def apply_tv(self) -> None:
        if self.tv:
            self.tv.apply(self.settings["tele"] == "on")

    def ready_videos(self, limit: int = 200) -> dict:
        """Les vidéos déjà traduites (prêtes à regarder sur la télé)."""
        channels = self.library.entries
        names = self.store.translated_names()
        candidates = [(i, c) for i, c in channels if c.kind != "direct" and names
                      and self.store.translation_path(*self._store_args(c)).name in names]
        items = [{"id": i, "name": c.name, "group": c.group, "logo": c.logo, "kind": c.kind,
                  "kind_label": KIND_LABELS[c.kind], "ready": True,
                  "watched": self.store.progress(c.url)["watched"]}
                 for i, c in candidates if self.is_ready(c)]
        return {"total": len(items), "items": items[:limit]}

    def video_for_tv(self, index: int) -> dict:
        """Tout ce qu'il faut à la télé pour lire une vidéo, adresse du flux comprise : cette
        réponse ne part que vers un appareil de la maison qui a donné le bon code."""
        channel = self.library.get(index)
        return {"id": index, "name": channel.name, "group": channel.group, "logo": channel.logo,
                "kind": channel.kind, "ready": self.is_ready(channel), "url": channel.url,
                **self.store.progress(channel.url),
                "subtitle_label": self.subtitle_label(), "language": self.settings["vers"]}

    def subtitles_for_tv(self, index: int) -> Path | None:
        return self.store.translation_file(*self._store_args(self.library.get(index)))

    def prepare(self, index: int) -> dict:
        """Récupère et traduit sur ce Mac, pour la télé. Une préparation déjà en cours pour la
        même vidéo est réutilisée plutôt que relancée (et payée) une seconde fois."""
        for job in self.jobs.values():
            if job.target == "tele" and job.channel_id == index and job.state == "running":
                return job_public(job)
        return job_public(self.watch(index, target="tele"))

    def jobs_for_tv(self, limit: int = 20) -> list[dict]:
        """Préparations demandées par la télé, les plus récentes d'abord : la télé peut fermer la
        fiche d'une vidéo et suivre son avancement depuis la liste."""
        jobs = [j for j in reversed(list(self.jobs.values())) if j.target == "tele"]
        return [job_public(j) for j in jobs[:limit]]

    def job_for_tv(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if job is None or job.target != "tele":
            raise KeyError("Préparation introuvable.")
        return job_public(job)

    def cancel_for_tv(self, job_id: str) -> dict:
        self.job_for_tv(job_id)
        return job_public(self.cancel(job_id))

    # --- sous-titres et lecture ---

    def check(self, index: int) -> dict:
        return asdict(check_subtitles(self.library.get(index).url, self.settings["depuis"],
                                      self.hls, whisper_available=self._whisper_enabled()))

    def watch(self, index: int, target: str = "mac") -> Job:
        channel = self.library.get(index)
        job = Job(id=uuid.uuid4().hex[:8], title=channel.name, started_at=time.time(),
                  channel_id=index, channel_url=channel.url, target=target)
        self.jobs[job.id] = job
        # (annulation demandée, arrêt de tout travail en cours : annulation ou vidéo fermée)
        self._events[job.id] = (threading.Event(), threading.Event())
        threading.Thread(target=self._run_watch, args=(job, channel), daemon=True).start()
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.jobs[job_id]
        cancelled, halt = self._events.get(job_id, (None, None))
        if cancelled is not None:
            cancelled.set()
            halt.set()
        player = self._players.get(job_id)
        if player is not None:
            player.stop()
        return job

    def _run_watch(self, job: Job, channel: Channel) -> None:
        cancelled, halt = self._events[job.id]
        translator = None

        def status(message: str, fraction: float | None = None) -> None:
            job.fetch_step, job.fraction = message, fraction

        try:
            ready = self.store.translation_file(*self._store_args(channel))
            if ready:  # déjà fait : rien à récupérer, rien à traduire, rien à payer
                if job.target == "tele":
                    job.found = job.translated = len(load_subtitles(ready))
                    job.fetch_done, job.saved = True, True
                    job.note = "Sous-titres déjà prêts (traduits lors d'un essai précédent) : aucun coût."
                    job.state, job.step = "done", TV_READY_STEP
                else:
                    self._play_saved(job, channel, ready, cancelled)
                    job.state, job.step = "done", "Terminé."
                return
            translator = self.make_translator(self.settings)
            saved = self.store.load_source(channel.url, self.settings["depuis"])
            if saved:  # sous-titres d'origine déjà récupérés : on saute la lecture du fichier
                cues, origin = saved
                job.note = "Sous-titres d'origine déjà récupérés lors d'un essai précédent."
                source = CueSource(f"{origin} (gardés)", "saved", [cues])
            else:
                source = open_cue_source(
                    channel.url, self.settings["depuis"], hls=self.hls, on_status=status,
                    cancel=halt, on_note=lambda message: setattr(job, "note", message),
                    transcriber_factory=self._get_transcriber if self._whisper_enabled() else None,
                )
            cache = self.make_cache()
            if job.target == "tele":
                if source.live_track:
                    raise NoSubtitles("Les directs ne sont pas encore possibles sur la télé.")
                self._translate_everything(job, source, translator, cache, halt)
                job.state, job.step = "done", TV_READY_STEP
                return
            if source.live_track:
                self._play_live(job, channel, source, translator, cache, cancelled)
            elif self.settings["lecteur"] == "mpv":
                self._play_progressive(job, channel, source, translator, cache, cancelled, halt)
            else:
                self._play_after_translation(job, channel, source, translator, cache, halt)
            if cancelled.is_set():
                raise Cancelled()
            job.state, job.step = "done", "Terminé."
        except Exception as exc:
            if cancelled.is_set() or isinstance(exc, Cancelled):
                job.state, job.step = "cancelled", "Annulé."
            else:
                job.state, job.error = "error", friendly_error(exc)
        finally:
            halt.set()  # plus rien ne doit tourner pour cette vidéo
            self._players.pop(job.id, None)
            if translator is not None:
                job.usage = translator.usage_summary()

    def subtitle_label(self) -> str:
        """Nom de la piste dans le menu du lecteur, ex. « Indonésien (traduit) »."""
        vers = self.settings["vers"]
        return f"{LANGUAGE_LABELS.get(vers, vers)} (traduit)"

    def _start_player(self, job: Job, name: str, url: str, **kwargs):
        player = self.make_player(name)
        self._players[job.id] = player
        job.player = PLAYER_NAMES[name]
        player.start(url, **kwargs)
        return player

    def _play_saved(self, job: Job, channel: Channel, path: Path, cancelled) -> None:
        """Rouvre une vidéo dont la traduction est déjà gardée : le lecteur démarre aussitôt."""
        name = self.settings["lecteur"]
        job.found = job.translated = len(load_subtitles(path))
        job.fetch_done, job.phase, job.saved = True, 3, True
        job.note = "Sous-titres déjà prêts (traduits lors d'un essai précédent) : aucun coût."
        job.state = "playing"
        job.step = f"Lecture en cours dans {PLAYER_NAMES[name]}."
        player = self._start_player(job, name, channel.url, subtitle=path, title=channel.name,
                                    subtitle_label=self.subtitle_label())
        player.wait()
        if cancelled.is_set():
            raise Cancelled()

    def _play_live(self, job, channel, source: CueSource, translator, cache, cancelled) -> None:
        if self.settings["lecteur"] != "mpv":
            job.note = "Direct : mpv est utilisé, VLC ne sait pas afficher des sous-titres au fil de l'eau."
        job.state, job.phase, job.fetch_done = "playing", 3, True
        job.step = "Direct : lecture dans mpv, traduction au fil de l'eau."
        player = self.make_player("mpv")
        self._players[job.id] = player
        job.player = "mpv"
        run_live(channel.url, source.live_track, translator, player, cache, hls=self.hls,
                 should_stop=cancelled.is_set)

    def _pipeline(self, job: Job, translator, cache, halt, **kwargs) -> TranslationPipeline:
        def on_batch(cues) -> None:
            job.translated = pipeline.translated

        pipeline = TranslationPipeline(translator, cache, workers=TRANSLATION_WORKERS,
                                       on_batch=on_batch, cancel=halt, **kwargs)
        return pipeline

    def _feed(self, job: Job, source: CueSource, pipeline: TranslationPipeline, halt,
              originals: list[Cue]) -> None:
        for group in source.groups:
            if halt.is_set():
                raise Cancelled()
            originals.extend(group)
            pipeline.add(group)
            job.found = pipeline.found
            if source.flush_each_group:
                pipeline.flush()
        job.fetch_done, job.fraction = True, 1.0
        if source.kind != "saved":  # récupération terminée : on la garde pour ne pas la refaire
            self.store.save_source(job.channel_url, self.settings["depuis"], originals, source.origin)

    def _save_translation(self, job: Job, translated: list[Cue], failed: int) -> None:
        if translated and not failed:  # jamais une traduction à moitié faite
            self.store.save_translation(job.channel_url, self.settings["depuis"],
                                        self.settings["vers"], self.settings["model"], translated)
            job.saved = True

    def _play_after_translation(self, job, channel, source: CueSource, translator, cache, halt):
        """VLC : tout est récupéré et traduit (en parallèle), puis la vidéo s'ouvre."""
        translated = self._translate_everything(job, source, translator, cache, halt)
        name = f"sous-titres.{self.settings['vers']}.srt"
        sub_path = Path(tempfile.mkdtemp(prefix="subtrad-")) / name
        save_subtitles(translated, sub_path)
        player = self._start_player(job, "vlc", channel.url, subtitle=sub_path, title=channel.name,
                                    subtitle_label=self.subtitle_label())
        job.state, job.phase, job.step = "playing", 3, "Lecture en cours dans VLC."
        player.wait()

    def _translate_everything(self, job, source: CueSource, translator, cache, halt) -> list[Cue]:
        """Récupère et traduit toutes les répliques (en parallèle), puis garde le résultat."""
        pipeline = self._pipeline(job, translator, cache, halt)
        originals: list[Cue] = []
        try:
            job.step = "Récupération et traduction des sous-titres…"
            self._feed(job, source, pipeline, halt, originals)
            job.phase, job.step = 2, "Traduction des dernières répliques…"
            translated = pipeline.finish()
        finally:
            pipeline.close()
        if halt.is_set():  # annulé pendant les derniers lots : on n'ouvre pas la vidéo
            raise Cancelled()
        if not translated:
            raise NoSubtitles("Aucune réplique trouvée dans ce fichier.")
        job.usage = translator.usage_summary()
        self._save_translation(job, translated, pipeline.failed)
        return translated

    def _play_progressive(self, job, channel, source: CueSource, translator, cache, cancelled, halt):
        """mpv : la vidéo démarre dès les premières répliques traduites ; la suite arrive
        pendant la lecture et s'affiche par-dessus l'image au bon moment."""
        timeline = Timeline(keep_ms=10**12)  # en replay on garde tout (retour en arrière)
        pipeline = self._pipeline(job, translator, cache, halt, first_batch_size=READY_CUES,
                                  keep_original_on_error=True)
        original_on_batch = pipeline.on_batch

        def on_batch(cues) -> None:
            timeline.add(cues)
            original_on_batch(cues)

        pipeline.on_batch = on_batch
        feeder_errors: list[BaseException] = []
        feeder_done = threading.Event()
        originals: list[Cue] = []

        def feed() -> None:
            try:
                self._feed(job, source, pipeline, halt, originals)
                self._save_translation(job, pipeline.finish(), pipeline.failed)
            except BaseException as exc:
                feeder_errors.append(exc)
            finally:
                pipeline.close()
                feeder_done.set()

        threading.Thread(target=feed, name="subtrad-feed", daemon=True).start()
        job.step = "Préparation des premières répliques…"
        while pipeline.translated < READY_CUES and not feeder_done.is_set():
            if cancelled.is_set():
                raise Cancelled()
            time.sleep(0.2)
        if feeder_errors and not pipeline.translated:
            raise feeder_errors[0]
        player = self._start_player(job, "mpv", channel.url, title=channel.name,
                                    hide_original_subs=True)
        job.state, job.phase = "playing", 3
        job.step = "Lecture en cours dans mpv (la suite des sous-titres arrive pendant la lecture)."
        display_loop(player, timeline, should_stop=cancelled.is_set)
        if cancelled.is_set():
            player.stop()
        player.wait()
        halt.set()  # vidéo fermée : inutile de continuer à récupérer et traduire
        feeder_done.wait(timeout=5)
        if feeder_errors and not isinstance(feeder_errors[0], Cancelled):
            job.note = f"Sous-titres interrompus : {friendly_error(feeder_errors[0])}"
        job.usage = translator.usage_summary()


class _Handler(BaseHTTPRequestHandler):
    app: GuiApp
    token: str
    page: str

    def log_message(self, fmt, *args):  # le Terminal reste lisible
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _allowed(self, needs_token: bool) -> bool:
        # Refuse les noms d'hôte étrangers (« DNS rebinding ») et, pour l'API, l'absence de jeton.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        return not needs_token or secrets.compare_digest(
            self.headers.get("X-Subtrad-Token", ""), self.token
        )

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            if not self._allowed(needs_token=False):
                return self._send(403, b"Interdit", "text/plain; charset=utf-8")
            return self._send(200, self.page.encode(), "text/html; charset=utf-8")
        self._api("GET", url.path, {k: v[-1] for k, v in parse_qs(url.query).items()})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json({"error": "Requête invalide."}, 400)
        self._api("POST", urlparse(self.path).path, body)

    def _api(self, method: str, path: str, params: dict) -> None:
        if not self._allowed(needs_token=True):
            return self._json({"error": "Accès refusé."}, 403)
        app = self.app
        try:
            if (method, path) == ("GET", "/api/state"):
                return self._json({**app.settings.public(), "count": len(app.library.channels),
                                   "whisper_backend": app.whisper_backend(),
                                   "sources": app.public_sources(),
                                   "kinds": app.library.kinds(), "tele_status": app.tv_status()})
            if path.startswith("/api/catalog"):
                try:
                    return self._json(app.catalog_request(path[len("/api/catalog"):], params))
                except LookupError as exc:
                    return self._json({"error": friendly_error(exc).strip("'\"")}, 404)
            if (method, path) == ("GET", "/api/ready"):
                return self._json(app.ready_videos())
            if (method, path) == ("GET", "/api/video"):
                vid = int(params["id"])
                return self._json({"id": vid, **app.video_status(vid)})
            if (method, path) == ("POST", "/api/prepare"):
                return self._json(app.prepare(int(params["id"])))
            if (method, path) == ("POST", "/api/play_original"):
                return self._json(job_public(app.play_original(int(params["id"]))))
            if (method, path) == ("GET", "/api/search"):
                return self._json(app.search(
                    params.get("q", ""), params.get("kind", ""), params.get("group", ""),
                    int(params.get("offset", 0)), min(int(params.get("limit", 100)), 500),
                    params.get("source", "")))
            if (method, path) == ("GET", "/api/groups"):
                return self._json(app.library.groups(params.get("kind", ""),
                                                     params.get("source", "")))
            if (method, path) == ("GET", "/api/jobs"):
                return self._json([job_public(j) for j in reversed(list(app.jobs.values()))])
            if (method, path) == ("GET", "/api/sources"):
                return self._json(app.public_sources())
            if (method, path) == ("POST", "/api/sources"):
                fields = ("kind", "name", "url", "server", "username", "password", "text")
                return self._json(app.add_source(**{k: str(params.get(k, "")) for k in fields}))
            if (method, path) == ("POST", "/api/sources/delete"):
                return self._json(app.remove_source(str(params["id"])))
            if (method, path) == ("POST", "/api/sources/refresh"):
                return self._json(app.refresh_sources(str(params.get("id", ""))))
            if (method, path) == ("POST", "/api/settings"):
                values = {k: str(params[k]) for k in
                          ("model", "depuis", "vers", "api_key", "lecteur", "whisper", "tele", "tmdb_key")
                          if k in params}
                for secret in ("api_key", "tmdb_key"):
                    if secret in values and not values[secret].strip():
                        del values[secret]  # champ laissé vide : on garde la clé actuelle
                tmdb_ok = None
                if "tmdb_key" in values:  # nouvelle clé TMDB : on vérifie qu'elle marche
                    tmdb_ok = TmdbClient(values["tmdb_key"]).check()
                    if not tmdb_ok:
                        del values["tmdb_key"]
                app.settings.update(**values)
                if params.get("nouveau_code_tele"):
                    app.settings.new_tv_code()
                app.apply_tv()
                return self._json({**app.settings.public(), "tele_status": app.tv_status(), "tmdb_ok": tmdb_ok})
            if (method, path) == ("POST", "/api/check"):
                return self._json(app.check(int(params["id"])))
            if (method, path) == ("POST", "/api/forget"):
                return self._json(app.forget(int(params["id"])))
            if (method, path) == ("POST", "/api/cancel"):
                return self._json(job_public(app.cancel(str(params["id"]))))
            if (method, path) == ("POST", "/api/watch"):
                return self._json(job_public(app.watch(int(params["id"]))))
            return self._json({"error": "Introuvable."}, 404)
        except Exception as exc:
            return self._json({"error": friendly_error(exc)}, 400)


def make_server(app: GuiApp, port: int = 8765) -> tuple[ThreadingHTTPServer, str]:
    """Crée le serveur sur le premier port libre à partir de `port` ; renvoie (serveur, jeton)."""
    token = secrets.token_urlsafe(24)
    page = resources.files("subtrad").joinpath("gui.html").read_text(encoding="utf-8")
    handler = type("Handler", (_Handler,), {
        "app": app, "token": token, "page": page.replace("__TOKEN__", token),
    })
    for candidate in range(port, port + 20) if port else [0]:
        try:
            return ThreadingHTTPServer(("127.0.0.1", candidate), handler), token
        except OSError:
            continue
    raise OSError(f"Aucun port libre entre {port} et {port + 19}.")


def open_in_chrome(url: str) -> None:
    if sys.platform == "darwin" and shutil.which("open"):
        if subprocess.run(["open", "-a", "Google Chrome", url]).returncode == 0:
            return
    webbrowser.open(url)


def run_gui(port: int = 8765, open_browser: bool = True, tv_port: int | None = None) -> int:
    from .tele import TV_PORT, TvAccess

    settings = Settings(config_dir())
    app = GuiApp(settings, default_cache_path().parent / "playlist.m3u")  # (ancien fichier, migré)
    server, _ = make_server(app, port)
    app.tv = TvAccess(app, port=tv_port or TV_PORT)
    app.apply_tv()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Interface ouverte sur {url}")
    tv = app.tv_status()
    if tv["active"]:
        print(f"Accès télé ouvert sur le Wi-Fi de la maison : {tv['address']} (code dans ⚙ Réglages).")
    elif tv["error"]:
        print(f"Accès télé impossible : {tv['error']}")
    print("Laisse cette fenêtre du Terminal ouverte. Pour arrêter : Ctrl + C.")
    if open_browser:
        open_in_chrome(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt de l'interface.")
    finally:
        app.tv.stop()
        server.server_close()
    return 0
