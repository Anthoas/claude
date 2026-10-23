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

from .cache import TranslationCache, default_cache_path
from .errors import friendly_error
from .hls import HlsClient
from .live import run_live
from .pipeline import check_subtitles, fetch_source_subtitles
from .player import MpvPlayer
from .playlist import Channel, fetch_playlist_text, parse_m3u
from .subtitles import save_subtitles
from .translate import DEFAULT_MODEL, ClaudeTranslator, translate_cues

MODELS = {
    "claude-haiku-5-5": "Haiku (économique, conseillé)",
    "claude-sonnet-5-5": "Sonnet (plus fin, ~20x plus cher)",
}
KIND_LABELS = {"direct": "Direct", "film": "Film", "serie": "Série"}


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
                "depuis": "fr", "vers": "id"}

    def __init__(self, directory: Path):
        self.path = directory / "config.json"
        self.data = dict(self.DEFAULTS)
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))

    def __getitem__(self, key: str) -> str:
        return self.data[key]

    def update(self, **values: str) -> None:
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
            "models": MODELS,
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
    state: str = "running"  # running | playing | done | error
    phase: int = 1  # 1 = recherche des sous-titres, 2 = traduction, 3 = lecture
    step: str = "Recherche des sous-titres…"
    fraction: float | None = None  # avancement de l'étape en cours (0 à 1), None si inconnu
    done: int = 0
    total: int = 0
    usage: str = ""
    error: str = ""
    started_at: float = 0.0  # horodatage UNIX : la page en déduit le temps écoulé


class GuiApp:
    def __init__(
        self,
        settings: Settings,
        playlist_cache: Path,
        translator_factory: Callable[[Settings], ClaudeTranslator] | None = None,
        player_factory: Callable[[], MpvPlayer] | None = None,
        cache_factory: Callable[[], TranslationCache] | None = None,
        hls: HlsClient | None = None,
    ):
        self.settings = settings
        self.playlist_cache = playlist_cache
        self.library = Library()
        self.jobs: dict[str, Job] = {}
        self.make_translator = translator_factory or self._default_translator
        self.make_player = player_factory or MpvPlayer
        self.make_cache = cache_factory or TranslationCache
        self.hls = hls or HlsClient()
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
        return asdict(check_subtitles(self.library.get(index).url, self.settings["depuis"], self.hls))

    def watch(self, index: int) -> Job:
        channel = self.library.get(index)
        job = Job(id=uuid.uuid4().hex[:8], title=channel.name, started_at=time.time())
        self.jobs[job.id] = job
        threading.Thread(target=self._run_watch, args=(job, channel), daemon=True).start()
        return job

    def _run_watch(self, job: Job, channel: Channel) -> None:
        translator = None

        def status(message: str, fraction: float | None = None) -> None:
            job.step, job.fraction = message, fraction

        try:
            translator = self.make_translator(self.settings)
            source = fetch_source_subtitles(
                channel.url, self.settings["depuis"], hls=self.hls, on_status=status
            )
            cache = self.make_cache()
            if source.live_track:
                job.state, job.phase, job.fraction = "playing", 3, None
                job.step = "Direct : lecture dans mpv, traduction au fil de l'eau."
                run_live(channel.url, source.live_track, translator, self.make_player(), cache,
                         hls=self.hls)
            else:
                job.phase, job.fraction = 2, None
                job.total = len(source.cues)
                job.step = "Traduction des sous-titres par Claude…"

                def progress(done: int, total: int) -> None:
                    job.done = job.total - total + done  # le cache a pu en traduire une partie

                translated = translate_cues(source.cues, translator, cache, on_progress=progress)
                job.done, job.usage = job.total, translator.usage_summary()
                sub_path = Path(tempfile.mkdtemp(prefix="subtrad-")) / f"sous-titres.{self.settings['vers']}.srt"
                save_subtitles(translated, sub_path)
                job.state, job.phase = "playing", 3
                job.step = "Lecture en cours dans mpv."
                self.make_player().start(channel.url, sub_path, title=channel.name).wait()
            job.state, job.step = "done", "Terminé."
        except Exception as exc:
            job.state, job.error = "error", friendly_error(exc)
        finally:
            if translator is not None:
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
                values = {k: str(params[k]) for k in ("model", "depuis", "vers", "api_key") if k in params}
                if "api_key" in values and not values["api_key"]:
                    del values["api_key"]  # champ laissé vide : on garde la clé actuelle
                app.settings.update(**values)
                return self._json(app.settings.public())
            if (method, path) == ("POST", "/api/check"):
                return self._json(app.check(int(params["id"])))
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
