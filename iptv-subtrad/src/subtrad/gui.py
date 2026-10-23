"""Interface graphique : une page web servie par ce Mac (127.0.0.1), à ouvrir dans Chrome.

Le serveur ne répond qu'aux requêtes locales portant le jeton de la session, pour qu'aucun
autre site ouvert dans le navigateur ne puisse piloter le programme.
"""

from __future__ import annotations

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
from dataclasses import asdict, dataclass
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
from .subtitles import save_subtitles
from .translate import DEFAULT_MODEL, ClaudeTranslator, TranslationPipeline

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
TRANSLATION_WORKERS = 4  # lots envoyés à Claude en même temps
READY_CUES = 10  # démarrage rapide : répliques traduites avant d'ouvrir la vidéo


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

    DEFAULTS = {"playlist_source": "", "api_key": "", "model": DEFAULT_MODEL,
                "depuis": "fr", "vers": "id", "lecteur": "vlc", "whisper": "on"}
    CHOICES = {"lecteur": set(PLAYERS), "whisper": {"on", "off"}, "model": set(MODELS)}

    def __init__(self, directory: Path):
        self.path = directory / "config.json"
        self.data = dict(self.DEFAULTS)
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

    def public(self) -> dict:
        return {
            "model": self.data["model"], "depuis": self.data["depuis"],
            "vers": self.data["vers"], "has_api_key": bool(self.api_key()),
            "api_key_from_env": not self.data["api_key"] and bool(self.api_key()),
            "has_playlist_source": bool(self.data["playlist_source"]),
            "models": MODELS, "lecteur": self.data["lecteur"], "players": PLAYERS,
            "whisper": self.data["whisper"],
        }


class Library:
    """La playlist en mémoire, avec un index de recherche."""

    def __init__(self):
        self._lock = threading.Lock()
        self.channels: list[Channel] = []
        self._haystacks: list[str] = []

    def load_text(self, text: str) -> int:
        channels = parse_m3u(text)
        haystacks = [normalize(f"{c.name} {c.group}") for c in channels]
        with self._lock:
            self.channels, self._haystacks = channels, haystacks
        return len(channels)

    def get(self, index: int) -> Channel:
        with self._lock:
            if not 0 <= index < len(self.channels):
                raise KeyError(f"Entrée {index} introuvable : recharge la playlist.")
            return self.channels[index]

    def _matching(self, query: str, kind: str, group: str) -> list[int]:
        words = normalize(query).split()
        return [
            i for i, (channel, hay) in enumerate(zip(self.channels, self._haystacks))
            if (not kind or channel.kind == kind)
            and (not group or channel.group == group)
            and all(w in hay for w in words)
        ]

    def search(self, query="", kind="", group="", offset=0, limit=100) -> dict:
        with self._lock:
            found = self._matching(query, kind, group)
            items = [
                {"id": i, "name": self.channels[i].name, "group": self.channels[i].group,
                 "logo": self.channels[i].logo, "kind": self.channels[i].kind,
                 "kind_label": KIND_LABELS[self.channels[i].kind]}
                for i in found[offset : offset + limit]
            ]
        return {"total": len(found), "items": items}

    def groups(self, kind: str = "") -> list[dict]:
        counts: dict[str, int] = {}
        with self._lock:
            for channel in self.channels:
                if channel.group and (not kind or channel.kind == kind):
                    counts[channel.group] = counts.get(channel.group, 0) + 1
        return [{"name": g, "count": n} for g, n in sorted(counts.items(), key=lambda x: normalize(x[0]))]

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
    ):
        self.settings = settings
        self.playlist_cache = playlist_cache
        self.library = Library()
        self.jobs: dict[str, Job] = {}
        self._events: dict[str, tuple[threading.Event, threading.Event]] = {}
        self._players: dict[str, object] = {}
        self.make_translator = translator_factory or self._default_translator
        self.make_player = player_factory or _default_player
        self.make_cache = cache_factory or TranslationCache
        self.hls = hls or HlsClient()
        self._transcriber = None
        self._transcriber_factory = transcriber_factory or transcribe.make_transcriber
        self.whisper_backend = whisper_backend or transcribe.backend_name
        if playlist_cache.exists():
            self.library.load_text(playlist_cache.read_text(encoding="utf-8", errors="replace"))

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

    # --- playlist ---

    def load_playlist(self, source: str = "", text: str = "") -> dict:
        if source:
            text = fetch_playlist_text(source.strip())
        if "#EXTINF" not in text:
            raise ValueError("Ce n'est pas une playlist M3U (aucune ligne #EXTINF).")
        count = self.library.load_text(text)
        self.playlist_cache.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.playlist_cache, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if source:
            self.settings.update(playlist_source=source.strip())
        return {"count": count}

    def refresh_playlist(self) -> dict:
        if not self.settings["playlist_source"]:
            raise ValueError("Aucun lien enregistré : colle d'abord le lien de la playlist.")
        return self.load_playlist(source=self.settings["playlist_source"])

    # --- sous-titres et lecture ---

    def check(self, index: int) -> dict:
        return asdict(check_subtitles(self.library.get(index).url, self.settings["depuis"],
                                      self.hls, whisper_available=self._whisper_enabled()))

    def watch(self, index: int) -> Job:
        channel = self.library.get(index)
        job = Job(id=uuid.uuid4().hex[:8], title=channel.name, started_at=time.time())
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
            translator = self.make_translator(self.settings)
            source = open_cue_source(
                channel.url, self.settings["depuis"], hls=self.hls, on_status=status,
                cancel=halt, on_note=lambda message: setattr(job, "note", message),
                transcriber_factory=self._get_transcriber if self._whisper_enabled() else None,
            )
            cache = self.make_cache()
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

    def _start_player(self, job: Job, name: str, url: str, **kwargs):
        player = self.make_player(name)
        self._players[job.id] = player
        job.player = PLAYER_NAMES[name]
        player.start(url, **kwargs)
        return player

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

    def _feed(self, job: Job, source: CueSource, pipeline: TranslationPipeline, halt) -> None:
        for group in source.groups:
            if halt.is_set():
                raise Cancelled()
            pipeline.add(group)
            job.found = pipeline.found
            if source.flush_each_group:
                pipeline.flush()
        job.fetch_done, job.fraction = True, 1.0

    def _play_after_translation(self, job, channel, source: CueSource, translator, cache, halt):
        """VLC : tout est récupéré et traduit (en parallèle), puis la vidéo s'ouvre."""
        pipeline = self._pipeline(job, translator, cache, halt)
        try:
            job.step = "Récupération et traduction des sous-titres…"
            self._feed(job, source, pipeline, halt)
            job.phase, job.step = 2, "Traduction des dernières répliques…"
            translated = pipeline.finish()
        finally:
            pipeline.close()
        if halt.is_set():  # annulé pendant les derniers lots : on n'ouvre pas la vidéo
            raise Cancelled()
        if not translated:
            raise NoSubtitles("Aucune réplique trouvée dans ce fichier.")
        job.usage = translator.usage_summary()
        name = f"sous-titres.{self.settings['vers']}.srt"
        sub_path = Path(tempfile.mkdtemp(prefix="subtrad-")) / name
        save_subtitles(translated, sub_path)
        player = self._start_player(job, "vlc", channel.url, subtitle=sub_path, title=channel.name)
        job.state, job.phase, job.step = "playing", 3, "Lecture en cours dans VLC."
        player.wait()

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

        def feed() -> None:
            try:
                self._feed(job, source, pipeline, halt)
                pipeline.finish()
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
                                   "kinds": app.library.kinds()})
            if (method, path) == ("GET", "/api/search"):
                return self._json(app.library.search(
                    params.get("q", ""), params.get("kind", ""), params.get("group", ""),
                    int(params.get("offset", 0)), min(int(params.get("limit", 100)), 500)))
            if (method, path) == ("GET", "/api/groups"):
                return self._json(app.library.groups(params.get("kind", "")))
            if (method, path) == ("GET", "/api/jobs"):
                return self._json([asdict(j) for j in reversed(list(app.jobs.values()))])
            if (method, path) == ("POST", "/api/playlist"):
                return self._json(app.load_playlist(params.get("source", ""), params.get("text", "")))
            if (method, path) == ("POST", "/api/playlist/refresh"):
                return self._json(app.refresh_playlist())
            if (method, path) == ("POST", "/api/settings"):
                values = {k: str(params[k]) for k in
                          ("model", "depuis", "vers", "api_key", "lecteur", "whisper") if k in params}
                if "api_key" in values and not values["api_key"]:
                    del values["api_key"]  # champ laissé vide : on garde la clé actuelle
                app.settings.update(**values)
                return self._json(app.settings.public())
            if (method, path) == ("POST", "/api/check"):
                return self._json(app.check(int(params["id"])))
            if (method, path) == ("POST", "/api/cancel"):
                return self._json(asdict(app.cancel(str(params["id"]))))
            if (method, path) == ("POST", "/api/watch"):
                return self._json(asdict(app.watch(int(params["id"]))))
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


def run_gui(port: int = 8765, open_browser: bool = True) -> int:
    settings = Settings(config_dir())
    app = GuiApp(settings, default_cache_path().parent / "playlist.m3u")
    server, _ = make_server(app, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Interface ouverte sur {url}")
    print("Laisse cette fenêtre du Terminal ouverte. Pour arrêter : Ctrl + C.")
    if open_browser:
        open_in_chrome(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt de l'interface.")
    finally:
        server.server_close()
    return 0
