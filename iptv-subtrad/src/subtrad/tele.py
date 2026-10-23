"""Accès depuis la télé : un second serveur, joignable sur le Wi-Fi de la maison, protégé par un code.

La page du Mac (gui.py) reste réservée à ce Mac. Ce serveur-ci sert l'application de la télé :
recherche, état des vidéos, préparation (récupération et traduction sur le Mac) et fichier .srt
traduit. Il refuse toute adresse qui n'est pas celle d'un appareil de la maison, et chaque requête
doit porter le code affiché dans les réglages ; trop de codes faux bloquent l'appareil un moment.
"""

from __future__ import annotations

import ipaddress
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from .errors import friendly_error

TV_PORT = 8766
MAX_FAILURES = 10  # codes faux d'affilée avant blocage
LOCK_SECONDS = 300  # durée du blocage


def lan_address() -> str | None:
    """Adresse de ce Mac sur le réseau de la maison (aucun paquet n'est envoyé)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.254.254.254", 9))  # choisit la carte réseau de la box
            address = probe.getsockname()[0]
        except OSError:
            return None
    return None if address.startswith("127.") or address == "0.0.0.0" else address


def is_home_client(ip: str) -> bool:
    """Vrai pour un appareil du réseau local (ou ce Mac), faux pour une adresse d'Internet."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


class Guard:
    """Compte les codes faux par appareil et bloque celui qui en enchaîne trop."""

    def __init__(self, max_failures: int = MAX_FAILURES, lock_seconds: float = LOCK_SECONDS):
        self.max_failures, self.lock_seconds = max_failures, lock_seconds
        self._lock = threading.Lock()
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def locked(self, ip: str) -> bool:
        with self._lock:
            return self._locked_until.get(ip, 0) > time.monotonic()

    def failure(self, ip: str) -> None:
        with self._lock:
            self._failures[ip] = self._failures.get(ip, 0) + 1
            if self._failures[ip] >= self.max_failures:
                self._locked_until[ip] = time.monotonic() + self.lock_seconds
                self._failures[ip] = 0

    def success(self, ip: str) -> None:
        with self._lock:
            self._failures.pop(ip, None)


class _TvHandler(BaseHTTPRequestHandler):
    app: object  # GuiApp
    guard: Guard

    def log_message(self, fmt, *args):  # le Terminal reste lisible
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        ip = self.client_address[0]
        if not is_home_client(ip):
            self._json({"error": "Accès réservé au réseau de la maison."}, 403)
            return False
        if self.guard.locked(ip):
            self._json({"error": "Trop de codes faux : réessaie dans quelques minutes."}, 429)
            return False
        if not secrets.compare_digest(self.headers.get("X-Subtrad-Code", ""), self.app.settings.tv_code()):
            self.guard.failure(ip)
            self._json({"error": "Code incorrect."}, 401)
            return False
        self.guard.success(ip)
        return True

    def do_GET(self):
        url = urlparse(self.path)
        self._api("GET", url.path, {k: v[-1] for k, v in parse_qs(url.query).items()})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(length, 65536)) or b"{}")
        except ValueError:
            return self._json({"error": "Requête invalide."}, 400)
        self._api("POST", urlparse(self.path).path, body)

    def _api(self, method: str, path: str, params: dict) -> None:
        if not self._authorized():
            return
        app = self.app
        try:
            if (method, path) == ("GET", "/tele/api/info"):
                return self._json({"app": "subtrad", "version": __version__,
                                   "count": len(app.library.channels), "kinds": app.library.kinds(),
                                   "language": app.settings["vers"],
                                   "subtitle_label": app.subtitle_label()})
            if (method, path) == ("GET", "/tele/api/search"):
                return self._json(app.search(
                    params.get("q", ""), params.get("kind", ""), params.get("group", ""),
                    int(params.get("offset", 0)), min(int(params.get("limit", 100)), 500)))
            if (method, path) == ("GET", "/tele/api/groups"):
                return self._json(app.library.groups(params.get("kind", "")))
            if (method, path) == ("GET", "/tele/api/ready"):
                return self._json(app.ready_videos(min(int(params.get("limit", 200)), 500)))
            if (method, path) == ("GET", "/tele/api/video"):
                return self._json(app.video_for_tv(int(params["id"])))
            if (method, path) == ("GET", "/tele/api/jobs"):
                return self._json(app.jobs_for_tv())
            if (method, path) == ("GET", "/tele/api/job"):
                return self._json(app.job_for_tv(str(params["id"])))
            if (method, path) == ("GET", "/tele/api/subtitles"):
                path_ = app.subtitles_for_tv(int(params["id"]))
                if path_ is None:
                    return self._json({"error": "Pas encore de sous-titres traduits pour cette vidéo."}, 404)
                return self._send(200, path_.read_bytes(), "application/x-subrip; charset=utf-8")
            if (method, path) == ("POST", "/tele/api/check"):
                return self._json(app.check(int(params["id"])))
            if (method, path) == ("POST", "/tele/api/prepare"):
                return self._json(app.prepare(int(params["id"])))
            if (method, path) == ("POST", "/tele/api/forget"):
                return self._json(app.forget(int(params["id"])))
            if (method, path) == ("POST", "/tele/api/cancel"):
                return self._json(app.cancel_for_tv(str(params["id"])))
            return self._json({"error": "Introuvable."}, 404)
        except KeyError as exc:
            return self._json({"error": friendly_error(exc).strip("'\"")}, 404)
        except Exception as exc:
            return self._json({"error": friendly_error(exc)}, 400)


class TvAccess:
    """Démarre ou arrête le serveur de la télé selon le réglage « Regarder sur la télé »."""

    def __init__(self, app, port: int = TV_PORT, host: str = "0.0.0.0"):
        self.app, self.port, self.host = app, port, host
        self.guard = Guard()
        self._server: ThreadingHTTPServer | None = None
        self.error = ""

    @property
    def active(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        if self._server is not None:
            return
        handler = type("TvHandler", (_TvHandler,), {"app": self.app, "guard": self.guard})
        try:
            self._server = ThreadingHTTPServer((self.host, self.port), handler)
        except OSError as exc:
            self.error = f"Impossible d'ouvrir le port {self.port} : {exc.strerror or exc}."
            return
        self.error = ""
        threading.Thread(target=self._server.serve_forever, name="subtrad-tele", daemon=True).start()

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()

    def apply(self, enabled: bool) -> None:
        self.start() if enabled else self.stop()

    def status(self) -> dict:
        port = self._server.server_address[1] if self._server else self.port
        address = lan_address() if self.host == "0.0.0.0" else self.host
        return {"active": self.active, "error": self.error,
                "address": f"{address}:{port}" if self.active and address else ""}
